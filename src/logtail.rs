//! 跟读 Xray access log,只提取"出站 tag == 查询出站"的行,
//! 建立 (客户端来源地址 → email) 的内存索引。其余日志行一律丢弃、不落盘。
//!
//! 目标行形如:
//!   2026/11/14 12:00:00.123456 from 203.0.113.5:51234 accepted tcp:6.6.6.6:80 [in-443 >> traffic-query] email: alice

use crate::proxy_proto::canon;
use anyhow::{Context, Result};
use regex::Regex;
use std::{
    collections::HashMap,
    io::SeekFrom,
    net::SocketAddr,
    path::{Path, PathBuf},
    sync::{Arc, Mutex},
    time::{Duration, Instant},
};
use tokio::{
    fs::File,
    io::{AsyncReadExt, AsyncSeekExt},
};

// ───────────────────────── 身份索引 ─────────────────────────

#[cfg(unix)]
fn file_identity(meta: &std::fs::Metadata) -> u64 {
    use std::os::unix::fs::MetadataExt;
    meta.ino()
}
#[cfg(not(unix))]
fn file_identity(meta: &std::fs::Metadata) -> u64 {
    meta.created()
        .ok()
        .and_then(|v| v.duration_since(std::time::UNIX_EPOCH).ok())
        .map(|v| v.as_nanos() as u64)
        .unwrap_or(0)
}

struct Entry {
    email: String,
    ambiguous: bool,
    at: Instant,
}

pub struct Index {
    map: Mutex<HashMap<SocketAddr, Entry>>,
    ttl: Duration,
}

impl Index {
    pub fn new(ttl: Duration) -> Self {
        Self {
            map: Mutex::new(HashMap::new()),
            ttl,
        }
    }

    pub fn insert(&self, src: SocketAddr, email: String) {
        let mut map = self.map.lock().unwrap();
        if map.len() >= 16384 && !map.contains_key(&src) {
            map.retain(|_, e| e.at.elapsed() < self.ttl);
            if map.len() >= 16384 {
                return;
            }
        }
        if let Some(e) = map.get_mut(&src) {
            if e.at.elapsed() < self.ttl && (e.ambiguous || e.email != email) {
                e.ambiguous = true;
                e.at = Instant::now();
                return;
            }
        }
        map.insert(
            src,
            Entry {
                email,
                ambiguous: false,
                at: Instant::now(),
            },
        );
    }

    pub fn get(&self, src: &SocketAddr) -> Option<String> {
        let m = self.map.lock().unwrap();
        m.get(src)
            .filter(|e| e.at.elapsed() < self.ttl && !e.ambiguous)
            .map(|e| e.email.clone())
    }

    pub fn sweep(&self) {
        let ttl = self.ttl;
        self.map.lock().unwrap().retain(|_, e| e.at.elapsed() < ttl);
    }

    /// 日志写入可能比连接到达晚几毫秒,轮询等一小会儿。
    pub async fn wait_for(&self, src: SocketAddr, max: Duration) -> Option<String> {
        let deadline = Instant::now() + max;
        loop {
            if let Some(e) = self.get(&src) {
                return Some(e);
            }
            if Instant::now() >= deadline {
                return None;
            }
            tokio::time::sleep(Duration::from_millis(25)).await;
        }
    }
}

// ───────────────────────── 行解析 ─────────────────────────

pub struct LogParser {
    re: Regex,
    tag: String,
}

impl LogParser {
    pub fn new(tag: &str) -> Self {
        // 兼容 `>>` / `->` 两种路由箭头,以及部分版本 from 后带 tcp:/udp: 前缀。
        let re = Regex::new(
            r"from (?:(?:tcp|udp):)?(?P<src>\S+) accepted (?P<dst>\S+) \[(?P<inb>[^\]]*?)\s*(?:>>|->)\s*(?P<out>[^\]\s]+)\](?:\s+email:\s*(?P<email>\S+))?",
        )
        .expect("regex");
        Self {
            re,
            tag: tag.to_string(),
        }
    }

    pub fn parse(&self, line: &str) -> Option<(SocketAddr, String)> {
        if !line.contains(self.tag.as_str()) {
            return None; // 绝大多数行在这里就被丢弃了
        }
        let c = self.re.captures(line)?;
        if c["out"] != self.tag {
            return None;
        }
        let email = c.name("email")?.as_str().to_string();
        let src: SocketAddr = c["src"].parse().ok()?;
        Some((canon(src), email))
    }
}

// ───────────────────────── 跟读循环 ─────────────────────────

struct Tail {
    file: File,
    pos: u64,
    ino: u64,
    partial: Vec<u8>,
}

pub async fn run(path: PathBuf, parser: LogParser, index: Arc<Index>) {
    let mut tail: Option<Tail> = None;
    let mut first = true;
    let mut last_sweep = Instant::now();
    let mut last_warn: Option<Instant> = None;
    loop {
        let mut delay = Duration::from_millis(100);
        if let Err(e) = step(&path, &parser, &index, &mut tail, first).await {
            tail = None;
            delay = Duration::from_secs(2);
            if last_warn.is_none_or(|t| t.elapsed() > Duration::from_secs(30)) {
                tracing::warn!("跟读 access log 失败(将持续重试): {e:#}");
                last_warn = Some(Instant::now());
            }
        }
        first = false;
        if last_sweep.elapsed() > Duration::from_secs(30) {
            index.sweep();
            last_sweep = Instant::now();
        }
        tokio::time::sleep(delay).await;
    }
}

async fn step(
    path: &Path,
    parser: &LogParser,
    index: &Index,
    tail: &mut Option<Tail>,
    first: bool,
) -> Result<()> {
    let meta = tokio::fs::metadata(path)
        .await
        .with_context(|| format!("stat {}", path.display()))?;
    let (ino, len) = (file_identity(&meta), meta.len());

    // 首次打开:从末尾开始,不回放历史;轮转/截断后:从头读新文件。
    let reopen = match tail {
        None => true,
        Some(t) => t.ino != ino || len < t.pos,
    };
    if reopen {
        let mut file = File::open(path)
            .await
            .with_context(|| format!("open {}", path.display()))?;
        let pos = if first { len } else { 0 };
        file.seek(SeekFrom::Start(pos)).await?;
        tracing::info!(path = %path.display(), pos, "开始跟读 access log");
        *tail = Some(Tail {
            file,
            pos,
            ino,
            partial: Vec::new(),
        });
    }

    let t = tail.as_mut().expect("tail set");
    let mut buf = vec![0u8; 64 * 1024];
    loop {
        let n = t.file.read(&mut buf).await?;
        if n == 0 {
            break;
        }
        t.pos += n as u64;
        t.partial.extend_from_slice(&buf[..n]);

        let mut start = 0;
        while let Some(off) = t.partial[start..].iter().position(|&b| b == b'\n') {
            let end = start + off;
            let line = String::from_utf8_lossy(&t.partial[start..end]);
            if let Some((src, email)) = parser.parse(line.trim_end()) {
                index.insert(src, email);
            }
            start = end + 1;
        }
        t.partial.drain(..start);
        if t.partial.len() > (1 << 20) {
            t.partial.clear(); // 异常超长行保护
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_target_line() {
        let p = LogParser::new("traffic-query");
        let l = "2026/11/14 12:00:00.123456 from 203.0.113.5:51234 accepted tcp:6.6.6.6:80 [in-443 >> traffic-query] email: alice";
        let (src, email) = p.parse(l).unwrap();
        assert_eq!(src, "203.0.113.5:51234".parse().unwrap());
        assert_eq!(email, "alice");
    }

    #[test]
    fn parses_ipv6_and_arrow_variant() {
        let p = LogParser::new("traffic-query");
        let l = "2026/11/14 12:00:00 from [2001:db8::1]:40000 accepted tcp:6.6.6.6:80 [in-443-tcp -> traffic-query] email: bob@example.com";
        let (src, email) = p.parse(l).unwrap();
        assert_eq!(src, "[2001:db8::1]:40000".parse().unwrap());
        assert_eq!(email, "bob@example.com");
    }

    #[test]
    fn parses_prefixed_from() {
        let p = LogParser::new("traffic-query");
        let l = "2026/11/14 12:00:00 from tcp:203.0.113.9:1234 accepted tcp:6.6.6.6:80 [in-1 >> traffic-query] email: carol";
        assert_eq!(p.parse(l).unwrap().1, "carol");
    }

    #[test]
    fn ignores_other_outbounds_and_lines() {
        let p = LogParser::new("traffic-query");
        assert!(p.parse("2026/11/14 12:00:00 from 1.2.3.4:5 accepted tcp:example.com:443 [in-443 >> direct] email: dave").is_none());
        // tag 只出现在别处(比如域名里)也不能误判
        assert!(p.parse("2026/11/14 12:00:00 from 1.2.3.4:5 accepted tcp:traffic-query.example.com:443 [in-443 >> direct] email: eve").is_none());
        assert!(p.parse("garbage").is_none());
    }

    #[test]
    fn line_without_email_is_ignored() {
        let p = LogParser::new("traffic-query");
        assert!(p.parse("2026/11/14 12:00:00 from 1.2.3.4:5 accepted tcp:6.6.6.6:80 [in-1 >> traffic-query]").is_none());
    }

    #[tokio::test]
    async fn index_wait_sees_late_insert() {
        let idx = Arc::new(Index::new(Duration::from_secs(60)));
        let src: SocketAddr = "1.2.3.4:5".parse().unwrap();
        let idx2 = idx.clone();
        tokio::spawn(async move {
            tokio::time::sleep(Duration::from_millis(80)).await;
            idx2.insert(src, "alice".into());
        });
        assert_eq!(
            idx.wait_for(src, Duration::from_millis(1000))
                .await
                .as_deref(),
            Some("alice")
        );
        assert!(idx
            .wait_for("9.9.9.9:9".parse().unwrap(), Duration::from_millis(60))
            .await
            .is_none());
    }
    #[test]
    fn conflicting_accounts_fail_closed() {
        let idx = Index::new(Duration::from_secs(60));
        let src = "1.2.3.4:1234".parse().unwrap();
        idx.insert(src, "alice".into());
        idx.insert(src, "bob".into());
        assert!(idx.get(&src).is_none());
        idx.insert(src, "bob".into());
        assert!(idx.get(&src).is_none());
    }
    #[tokio::test]
    async fn index_entries_expire() {
        let idx = Index::new(Duration::from_millis(1));
        let src = "1.2.3.4:1234".parse().unwrap();
        idx.insert(src, "alice".into());
        tokio::time::sleep(Duration::from_millis(10)).await;
        assert!(idx.get(&src).is_none());
    }
}
