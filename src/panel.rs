//! 3x-ui 面板 API 客户端。只用一个接口:
//!   GET /panel/api/clients/traffic/{email}   (Authorization: Bearer <token>)

use crate::config::PanelCfg;
use anyhow::{anyhow, bail, Context, Result};
use reqwest::{Client, Url};
use serde::{Deserialize, Serialize};
use std::{
    collections::HashMap,
    time::{Duration, Instant},
};
use tokio::sync::Mutex;

fn yes() -> bool {
    true
}

/// 面板返回的 ClientTraffic 里我们关心的字段(故意不含 uuid / subId,避免泄露)。
#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct ClientTraffic {
    #[serde(default)]
    pub email: String,
    #[serde(default = "yes")]
    pub enable: bool,
    #[serde(default)]
    pub up: i64,
    #[serde(default)]
    pub down: i64,
    /// 总流量配额(字节),0 = 不限
    #[serde(default)]
    pub total: i64,
    /// 到期时间 Unix 毫秒;0 = 不限;负数 = 首次使用后起算的时长(毫秒)
    #[serde(default, rename = "expiryTime")]
    pub expiry_time: i64,
    #[serde(default, rename = "lastOnline")]
    pub last_online: i64,
}

#[derive(Deserialize)]
struct Envelope {
    #[serde(default)]
    success: bool,
    #[serde(default, rename = "msg")]
    _msg: String,
    obj: Option<ClientTraffic>,
}

pub struct PanelClient {
    http: Client,
    base: Url,
    token: String,
    ttl: Duration,
    cache: Mutex<HashMap<String, (Instant, ClientTraffic)>>,
}

impl PanelClient {
    pub fn new(cfg: &PanelCfg, token: String) -> Result<Self> {
        let http = Client::builder()
            .timeout(Duration::from_secs(cfg.timeout_secs))
            .redirect(reqwest::redirect::Policy::none())
            .no_proxy()
            .user_agent(concat!("flownote/", env!("CARGO_PKG_VERSION")))
            .build()?;
        let base = Url::parse(&cfg.base_url)
            .with_context(|| format!("panel.base_url 无效: {}", cfg.base_url))?;
        Ok(Self {
            http,
            base,
            token,
            ttl: Duration::from_secs(cfg.cache_ttl_secs),
            cache: Mutex::new(HashMap::new()),
        })
    }

    pub async fn traffic(&self, email: &str) -> Result<ClientTraffic> {
        let mut cache = self.cache.lock().await;
        if let Some((at, v)) = cache.get(email) {
            if at.elapsed() < self.ttl {
                return Ok(v.clone());
            }
        }

        let mut url = self.base.clone();
        url.path_segments_mut()
            .map_err(|_| anyhow!("panel.base_url 不能作为基础地址"))?
            .pop_if_empty()
            .extend(["panel", "api", "clients", "traffic"])
            .push(email); // push 会对 email 做百分号编码

        let resp = self
            .http
            .get(url)
            .bearer_auth(&self.token)
            .header("Accept", "application/json")
            .send()
            .await
            .map_err(|_| anyhow!("请求面板失败：检查服务连通性、证书及配置"))?;
        let status = resp.status();
        let mut resp = resp;
        let mut body = Vec::new();
        while let Some(chunk) = resp
            .chunk()
            .await
            .map_err(|_| anyhow!("读取面板响应失败"))?
        {
            if body.len() + chunk.len() > 64 * 1024 {
                bail!("面板响应超过 64 KiB");
            }
            body.extend_from_slice(&chunk);
        }
        let text = String::from_utf8(body).context("面板响应不是 UTF-8")?;
        if !status.is_success() {
            bail!("面板返回 HTTP {status}，检查 token 权限和 webBasePath");
        }
        let env: Envelope = serde_json::from_str(&text).context("面板响应格式无效")?;
        if !env.success {
            bail!("面板未返回有效的流量数据");
        }
        let t = env.obj.ok_or_else(|| anyhow!("面板未返回有效的流量数据"))?;
        if t.email != email {
            bail!("面板返回账号与查询账号不一致");
        }
        if t.up < 0 || t.down < 0 || t.total < 0 {
            bail!("面板未返回有效的流量数据");
        }
        if cache.len() >= 2048 {
            cache.retain(|_, (at, _)| at.elapsed() < self.ttl);
            if cache.len() >= 2048 {
                cache.clear();
            }
        }
        cache.insert(email.to_string(), (Instant::now(), t.clone()));
        Ok(t)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn deserializes_doc_example() {
        let j = r#"{"success":true,"obj":{"down":2097152,"email":"user1","enable":true,"expiryTime":1735689600000,
            "id":14825,"inboundId":1,"lastOnline":1735680000000,"lastSubFetch":1735680000000,"reset":0,
            "resetCount":0,"resetDay":0,"resetMax":0,"resetWeekday":0,"subId":"i7tvdpeffi0hvvf1",
            "total":10737418240,"up":1048576,"uuid":"e18c9a96-71bf-48d4-933f-8b9a46d4290c"}}"#;
        let e: Envelope = serde_json::from_str(j).unwrap();
        let t = e.obj.unwrap();
        assert_eq!((t.up, t.down, t.total), (1048576, 2097152, 10737418240));
        assert_eq!(t.expiry_time, 1735689600000);
        assert!(t.enable);
    }

    #[test]
    fn tolerates_missing_fields() {
        let e: Envelope = serde_json::from_str(r#"{"success":true,"obj":{"email":"x"}}"#).unwrap();
        let t = e.obj.unwrap();
        assert!(t.enable && t.up == 0 && t.total == 0);
    }
}
