use crate::config::TlsCfg;
use anyhow::{Context, Result};
use std::{fs::File, io::BufReader, sync::Arc};
use tokio_rustls::{rustls::ServerConfig, TlsAcceptor};

pub fn acceptor(cfg: &TlsCfg) -> Result<TlsAcceptor> {
    let mut cert = BufReader::new(File::open(&cfg.cert_file).context("无法打开 TLS 证书完整链")?);
    let certs = rustls_pemfile::certs(&mut cert).collect::<std::io::Result<Vec<_>>>()?;
    let mut key = BufReader::new(File::open(&cfg.key_file).context("无法打开 TLS 私钥")?);
    let key = rustls_pemfile::private_key(&mut key)?.context("PEM 文件中没有可用私钥")?;
    let provider = tokio_rustls::rustls::crypto::ring::default_provider();
    let mut tls = ServerConfig::builder_with_provider(Arc::new(provider))
        .with_safe_default_protocol_versions()?
        .with_no_client_auth()
        .with_single_cert(certs, key)?;
    tls.alpn_protocols = vec![b"http/1.1".to_vec()];
    Ok(TlsAcceptor::from(Arc::new(tls)))
}
