use crate::{config::HistoryCfg, panel::Snapshot};
use anyhow::{bail, Context, Result};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    fs,
    io::{Read, Write},
    path::Path,
    sync::Mutex,
};

const MAX_ACCOUNTS: usize = 1024;
const MAX_POINTS: usize = 4096;
const MAX_BYTES: u64 = 512 * 1024;

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Sample {
    pub at_ms: i64,
    pub up: i64,
    pub down: i64,
}

pub struct History {
    cfg: HistoryCfg,
    lock: Mutex<()>,
}
impl History {
    pub fn new(cfg: HistoryCfg) -> Self {
        Self {
            cfg,
            lock: Mutex::new(()),
        }
    }
    pub fn sample(&self, snapshot: &Snapshot) -> Result<Vec<Sample>> {
        if !self.cfg.enabled {
            return Ok(Vec::new());
        }
        let _guard = self
            .lock
            .lock()
            .map_err(|_| anyhow::anyhow!("history lock"))?;
        let dir = &self.cfg.directory;
        fs::create_dir_all(dir)?;
        if fs::symlink_metadata(dir)?.file_type().is_symlink() {
            bail!("history directory is a symlink");
        }
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            fs::set_permissions(dir, fs::Permissions::from_mode(0o700))?;
        }
        let id = format!("{:x}", Sha256::digest(snapshot.traffic.email.as_bytes()));
        let path = dir.join(format!("{id}.json"));
        let cutoff = snapshot
            .observed_at_ms
            .saturating_sub(i64::from(self.cfg.retention_days) * 86_400_000);
        let mut points = if path.try_exists()? {
            read_samples(&path)?
        } else {
            // Prune only our expired account files. Never touch unrelated state files.
            let mut count = 0;
            for entry in fs::read_dir(dir)? {
                let entry = entry?;
                let name = entry.file_name();
                let name = name.to_string_lossy();
                if name.len() != 69
                    || !name.ends_with(".json")
                    || !name[..64].bytes().all(|b| b.is_ascii_hexdigit())
                {
                    continue;
                }
                let meta = fs::symlink_metadata(entry.path())?;
                if !meta.is_file() {
                    continue;
                }
                if meta
                    .modified()?
                    .duration_since(std::time::UNIX_EPOCH)?
                    .as_millis()
                    < cutoff.max(0) as u128
                {
                    fs::remove_file(entry.path())?;
                } else {
                    count += 1;
                }
            }
            if count >= MAX_ACCOUNTS {
                bail!("history account limit");
            }
            Vec::new()
        };
        // Concurrent responses can reach the blocking worker out of order.
        if points
            .last()
            .is_some_and(|p| p.at_ms > snapshot.observed_at_ms)
        {
            return Ok(points);
        }
        points.retain(|p| p.at_ms >= cutoff);
        let t = &snapshot.traffic;
        let next = Sample {
            at_ms: snapshot.observed_at_ms,
            up: t.up,
            down: t.down,
        };
        let append = points.last().is_none_or(|p| {
            next.at_ms > p.at_ms
                && (next.at_ms - p.at_ms >= self.cfg.sample_interval_secs as i64 * 1000
                    || next.up < p.up
                    || next.down < p.down)
        });
        if append {
            points.push(next);
            if points.len() > MAX_POINTS {
                points.drain(..points.len() - MAX_POINTS);
            }
            // The temp name is private and opened exclusively. Atomic rename preserves previous data on failure.
            let temp = dir.join(format!("{id}.tmp"));
            let mut options = fs::OpenOptions::new();
            options.write(true).create_new(true);
            #[cfg(unix)]
            {
                use std::os::unix::fs::OpenOptionsExt;
                options.mode(0o600);
            }
            let write = (|| -> Result<()> {
                let mut file = options.open(&temp)?;
                file.write_all(&serde_json::to_vec(&points)?)?;
                file.sync_all()?;
                fs::rename(&temp, &path)?;
                Ok(())
            })();
            if write.is_err() && temp.is_file() {
                let _ = fs::remove_file(&temp);
            }
            write?;
        }
        Ok(points)
    }
}
fn read_samples(path: &Path) -> Result<Vec<Sample>> {
    let meta = fs::symlink_metadata(path)?;
    if !meta.is_file() || meta.len() > MAX_BYTES {
        bail!("invalid history file");
    }
    let mut bytes = Vec::new();
    fs::File::open(path)?
        .take(MAX_BYTES + 1)
        .read_to_end(&mut bytes)?;
    if bytes.len() as u64 > MAX_BYTES {
        bail!("history too large");
    }
    let samples: Vec<Sample> = serde_json::from_slice(&bytes).context("invalid history")?;
    if samples.len() > MAX_POINTS
        || samples
            .iter()
            .any(|p| p.at_ms <= 0 || p.up < 0 || p.down < 0)
        || samples.windows(2).any(|p| p[0].at_ms >= p[1].at_ms)
    {
        bail!("invalid history samples");
    }
    Ok(samples)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::panel::ClientTraffic;
    #[test]
    fn persists_isolates_deduplicates_prunes_and_records_reset() {
        let dir = std::env::temp_dir().join(format!(
            "flownote-history-{}-{}",
            std::process::id(),
            crate::now_ms()
        ));
        let cfg = HistoryCfg {
            enabled: true,
            directory: dir.clone(),
            retention_days: 1,
            sample_interval_secs: 300,
        };
        let mut s = Snapshot {
            traffic: ClientTraffic {
                email: "../../alice".into(),
                enable: true,
                up: 100,
                down: 200,
                total: 1000,
                expiry_time: 0,
                last_online: 0,
            },
            observed_at_ms: crate::now_ms(),
        };
        let store = History::new(cfg.clone());
        assert_eq!(store.sample(&s).unwrap().len(), 1);
        assert_eq!(store.sample(&s).unwrap().len(), 1);
        s.observed_at_ms += 300_000;
        s.traffic.up = 200;
        assert_eq!(store.sample(&s).unwrap().len(), 2);
        assert_eq!(History::new(cfg).sample(&s).unwrap().len(), 2);
        let mut stale = s.clone();
        stale.observed_at_ms -= 300_000;
        assert_eq!(store.sample(&stale).unwrap().len(), 2);
        s.traffic.email = "bob".into();
        assert_eq!(store.sample(&s).unwrap().len(), 1);
        s.traffic.email = "../../alice".into();
        s.observed_at_ms += 1;
        s.traffic.up = 0;
        assert_eq!(store.sample(&s).unwrap().len(), 3);
        s.observed_at_ms += 86_400_001;
        assert_eq!(store.sample(&s).unwrap().len(), 1);
        for entry in fs::read_dir(&dir).unwrap() {
            let p = entry.unwrap().path();
            assert!(!p.file_name().unwrap().to_string_lossy().contains("alice"));
            #[cfg(unix)]
            {
                use std::os::unix::fs::PermissionsExt;
                assert_eq!(
                    fs::metadata(&p).unwrap().permissions().mode() & 0o777,
                    0o600
                );
            }
            fs::write(&p, b"invalid").unwrap();
        }
        assert!(store.sample(&s).is_err());
        fs::remove_dir_all(dir).unwrap();
    }
    #[test]
    fn disabled_never_creates_state() {
        let store = History::new(HistoryCfg::default());
        let s = Snapshot {
            traffic: serde_json::from_str(r#"{"email":"a"}"#).unwrap(),
            observed_at_ms: 1000,
        };
        assert!(store.sample(&s).unwrap().is_empty());
    }
}
