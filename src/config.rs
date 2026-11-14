use anyhow::{bail, Context, Result};
use serde::Deserialize;
use std::{net::SocketAddr, path::PathBuf};

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Config {
    pub server: ServerCfg,
    pub tls: TlsCfg,
    pub xray: XrayCfg,
    pub panel: PanelCfg,
    #[serde(default)]
    pub display: DisplayCfg,
    #[serde(default)]
    pub history: HistoryCfg,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ServerCfg {
    #[serde(default = "d_listen")]
    pub listen: SocketAddr,
    pub domain: String,
    #[serde(default = "d_max_conns")]
    pub max_conns: usize,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TlsCfg {
    pub cert_file: PathBuf,
    pub key_file: PathBuf,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct XrayCfg {
    pub access_log: PathBuf,
    #[serde(default = "d_tag")]
    pub outbound_tag: String,
    #[serde(default = "d_lookup_ms")]
    pub lookup_timeout_ms: u64,
    #[serde(default = "d_entry_ttl")]
    pub entry_ttl_secs: u64,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PanelCfg {
    pub base_url: String,
    pub token: Option<String>,
    pub token_file: Option<PathBuf>,
    #[serde(default = "d_cache_ttl")]
    pub cache_ttl_secs: u64,
    #[serde(default = "d_timeout")]
    pub timeout_secs: u64,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DisplayCfg {
    #[serde(default = "d_title")]
    pub title: String,
    #[serde(default = "d_tz")]
    pub tz_offset_hours: i8,
}
impl Default for DisplayCfg {
    fn default() -> Self {
        Self {
            title: d_title(),
            tz_offset_hours: d_tz(),
        }
    }
}
#[derive(Debug, Clone, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct HistoryCfg {
    pub enabled: bool,
    pub directory: PathBuf,
    pub retention_days: u32,
    pub sample_interval_secs: u64,
}
impl Default for HistoryCfg {
    fn default() -> Self {
        Self {
            enabled: false,
            directory: "/var/lib/flownote/history".into(),
            retention_days: 30,
            sample_interval_secs: 3600,
        }
    }
}
fn d_listen() -> SocketAddr {
    "127.0.0.1:8686".parse().unwrap()
}
fn d_max_conns() -> usize {
    128
}
fn d_tag() -> String {
    "traffic-query".into()
}
fn d_lookup_ms() -> u64 {
    1500
}
fn d_entry_ttl() -> u64 {
    600
}
fn d_cache_ttl() -> u64 {
    5
}
fn d_timeout() -> u64 {
    5
}
fn d_title() -> String {
    "流量笺".into()
}
fn d_tz() -> i8 {
    8
}

impl Config {
    pub fn load(path: &str) -> Result<Self> {
        let raw = std::fs::read_to_string(path).with_context(|| format!("读取配置文件 {path}"))?;
        let cfg: Self = toml::from_str(&raw)
            .context("配置解析失败；v0.3 请使用 deploy/config.example.toml 模板")?;
        cfg.validate()?;
        Ok(cfg)
    }
    pub fn validate(&self) -> Result<()> {
        if !self.server.listen.ip().is_loopback() {
            bail!("server.listen 必须为回环地址，不能暴露公网或内网");
        }
        if !(1..=90).contains(&self.history.retention_days)
            || !(300..=86400).contains(&self.history.sample_interval_secs)
            || (self.history.enabled && !self.history.directory.is_absolute())
        {
            bail!("history requires an absolute directory, retention_days 1..=90 and sample_interval_secs 300..=86400");
        }
        let d = &self.server.domain;
        if d.len() > 253
            || !d.contains('.')
            || d.ends_with(".local")
            || d.parse::<std::net::IpAddr>().is_ok()
            || d.split('.').any(|label| {
                label.is_empty()
                    || label.len() > 63
                    || label.starts_with('-')
                    || label.ends_with('-')
                    || !label
                        .bytes()
                        .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == b'-')
            })
        {
            bail!("server.domain 必须为小写 ASCII 自有域名，不含协议、端口、路径；不支持 .local 和 IP");
        }
        if !(1..=1024).contains(&self.server.max_conns) {
            bail!("server.max_conns 必须在 1..=1024");
        }
        if !(100..=5000).contains(&self.xray.lookup_timeout_ms)
            || !(1..=600).contains(&self.xray.entry_ttl_secs)
        {
            bail!("日志等待时间必须为 100..=5000 ms，索引 TTL 必须为 1..=600 s");
        }
        if !(1..=60).contains(&self.panel.cache_ttl_secs)
            || !(1..=10).contains(&self.panel.timeout_secs)
        {
            bail!("面板缓存必须为 1..=60 s，超时必须为 1..=10 s");
        }
        if !(-23..=23).contains(&self.display.tz_offset_hours) {
            bail!("时区偏移必须在 -23..=23 小时");
        }
        let url =
            reqwest::Url::parse(&self.panel.base_url).context("panel.base_url 不是有效 URL")?;
        let local = url.host_str().is_some_and(|h| {
            h == "localhost"
                || h.trim_matches(['[', ']'])
                    .parse::<std::net::IpAddr>()
                    .is_ok_and(|ip| ip.is_loopback())
        });
        if !matches!(url.scheme(), "http" | "https")
            || (url.scheme() == "http" && !local)
            || !url.username().is_empty()
            || url.password().is_some()
            || url.query().is_some()
            || url.fragment().is_some()
        {
            bail!("面板只允许回环 HTTP 或有效证书 HTTPS，URL 不得含凭据、查询或片段");
        }
        Ok(())
    }
    pub fn resolve_token(&self) -> Result<String> {
        if let Ok(t) = std::env::var("XUI_API_TOKEN") {
            if !t.trim().is_empty() {
                return Ok(t.trim().to_owned());
            }
        }
        if let Some(p) = &self.panel.token_file {
            let t = std::fs::read_to_string(p)
                .context("无法读取面板 token 文件，请检查文件路径及服务用户权限")?;
            if !t.trim().is_empty() {
                return Ok(t.trim().to_owned());
            }
        }
        if let Some(t) = &self.panel.token {
            if !t.trim().is_empty() {
                return Ok(t.trim().to_owned());
            }
        }
        bail!("缺少 API token：设置 XUI_API_TOKEN / panel.token_file / panel.token")
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn sample() -> Config {
        toml::from_str(include_str!("../deploy/config.example.toml")).unwrap()
    }
    #[test]
    fn example_is_valid() {
        sample().validate().unwrap();
    }
    #[test]
    fn rejects_unsafe_configuration() {
        let mut c = sample();
        c.server.listen = "0.0.0.0:8686".parse().unwrap();
        assert!(c.validate().is_err());
        for domain in [
            "traffic.local",
            "https://traffic.example.com",
            "127.0.0.1",
            "-bad.example.com",
            "a..example.com",
        ] {
            let mut c = sample();
            c.server.domain = domain.into();
            assert!(c.validate().is_err());
        }
        for url in [
            "http://panel.example.com",
            "https://u:p@panel.example.com",
            "https://panel.example.com/?token=x",
        ] {
            let mut c = sample();
            c.panel.base_url = url.into();
            assert!(c.validate().is_err());
        }
    }
    #[test]
    fn accepts_secure_panel_and_ipv6_loopback() {
        for url in ["https://panel.example.com/base", "http://[::1]:2053/base"] {
            let mut c = sample();
            c.panel.base_url = url.into();
            c.validate().unwrap();
        }
    }
    #[test]
    fn legacy_config_disables_history_and_history_limits_are_checked() {
        let raw = include_str!("../deploy/config.example.toml")
            .split("[history]")
            .next()
            .unwrap();
        let c: Config = toml::from_str(raw).unwrap();
        assert!(!c.history.enabled);
        for days in [0, 91] {
            let mut c = sample();
            c.history.retention_days = days;
            assert!(c.validate().is_err());
        }
        let mut c = sample();
        c.history.directory = "relative".into();
        assert!(c.validate().is_err());
        let mut c = sample();
        c.history.sample_interval_secs = 1;
        assert!(c.validate().is_err());
    }
    #[test]
    fn rejects_legacy_debug_override() {
        let raw = include_str!("../deploy/config.example.toml").to_string()
            + "\n[debug]\nfake_email = 'alice'\n";
        assert!(toml::from_str::<Config>(&raw).is_err());
    }
}
