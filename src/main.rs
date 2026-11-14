mod config;
mod history;
mod logtail;
mod panel;
mod proxy_proto;
mod render;
mod tls;

use anyhow::{bail, Context, Result};
use bytes::Bytes;
use config::{Config, Protocol};
use http_body_util::Full;
use hyper::{
    body::Incoming,
    header::{HeaderValue, CACHE_CONTROL, CONTENT_TYPE},
    server::conn::http1,
    service::service_fn,
    Method, Request, Response, StatusCode,
};
use hyper_util::rt::{TokioIo, TokioTimer};
use logtail::{Index, LogParser};
use panel::PanelClient;
use std::{
    convert::Infallible,
    sync::Arc,
    time::{Duration, SystemTime, UNIX_EPOCH},
};
use tokio::{
    net::{TcpListener, TcpStream},
    sync::Semaphore,
    time::timeout,
};
use tokio_rustls::TlsAcceptor;
use tracing::{debug, info, warn};
use tracing_subscriber::EnvFilter;

struct Ctx {
    cfg: Config,
    index: Arc<Index>,
    panel: PanelClient,
    history: Arc<history::History>,
    tls: Option<TlsAcceptor>,
}

#[tokio::main]
async fn main() -> Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(
            EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info")),
        )
        .init();
    let args: Vec<_> = std::env::args().skip(1).collect();
    if args.as_slice() == ["--version"] {
        println!("flownote {}", env!("CARGO_PKG_VERSION"));
        return Ok(());
    }
    if args.first().is_some_and(|v| v == "--preview") {
        let dir = args.get(1).context("用法：flownote --preview 输出目录")?;
        return render::preview(std::path::Path::new(dir));
    }
    let path = args
        .first()
        .cloned()
        .or_else(|| std::env::var("FLOWNOTE_CONFIG").ok())
        .unwrap_or_else(|| "/etc/flownote/config.toml".into());
    let cfg = Config::load(&path)?;
    let panel = PanelClient::new(&cfg.panel, cfg.resolve_token()?)?;
    if args.get(1).is_some_and(|v| v == "--check-panel") && args.len() == 3 {
        let t = panel.traffic(&args[2]).await?;
        println!("{}", render::text(&t.traffic, &cfg.display, now_ms()));
        return Ok(());
    }
    if args.len() > 1 {
        bail!("用法：flownote [配置路径] [--check-panel email] 或 flownote --preview 输出目录");
    }
    let tls = cfg.tls.as_ref().map(tls::acceptor).transpose()?;
    let index = Arc::new(Index::new(Duration::from_secs(cfg.xray.entry_ttl_secs)));
    tokio::spawn(logtail::run(
        cfg.xray.access_log.clone(),
        LogParser::new(&cfg.xray.outbound_tag),
        index.clone(),
    ));
    let listener = TcpListener::bind(cfg.server.listen).await?;
    info!(listen = %cfg.server.listen, domain = %cfg.server.domain, protocol = ?cfg.server.protocol, "FlowNote 已启动");
    let sem = Arc::new(Semaphore::new(cfg.server.max_conns));
    let history = Arc::new(history::History::new(cfg.history.clone()));
    let ctx = Arc::new(Ctx {
        history,
        cfg,
        index,
        panel,
        tls,
    });
    loop {
        let (stream, peer) = listener.accept().await?;
        if !peer.ip().is_loopback() {
            continue;
        }
        let Ok(permit) = sem.clone().try_acquire_owned() else {
            continue;
        };
        let ctx = ctx.clone();
        tokio::spawn(async move {
            let _permit = permit;
            match timeout(Duration::from_secs(30), serve(stream, ctx)).await {
                Ok(Ok(())) => {}
                Ok(Err(e)) => debug!("连接结束: {e:#}"),
                Err(_) => debug!("连接超时"),
            }
        });
    }
}

async fn serve(mut stream: TcpStream, ctx: Arc<Ctx>) -> Result<()> {
    let src = timeout(
        Duration::from_secs(3),
        proxy_proto::read_header(&mut stream),
    )
    .await??
    .map(proxy_proto::canon)
    .context("PROXY 头缺少 TCP 来源")?;
    if let Some(tls) = &ctx.tls {
        let stream = timeout(Duration::from_secs(5), tls.accept(stream)).await??;
        if !stream
            .get_ref()
            .1
            .server_name()
            .is_some_and(|s| s.eq_ignore_ascii_case(&ctx.cfg.server.domain))
        {
            bail!("TLS SNI 不匹配");
        }
        serve_http(stream, src, ctx).await
    } else {
        serve_http(stream, src, ctx).await
    }
}

async fn serve_http<S>(stream: S, src: std::net::SocketAddr, ctx: Arc<Ctx>) -> Result<()>
where
    S: tokio::io::AsyncRead + tokio::io::AsyncWrite + Unpin + Send + 'static,
{
    let email = Arc::new(
        ctx.index
            .wait_for(src, Duration::from_millis(ctx.cfg.xray.lookup_timeout_ms))
            .await,
    );
    let svc = service_fn(move |req| {
        let ctx = ctx.clone();
        let email = email.clone();
        async move {
            let head = req.method() == Method::HEAD;
            let https = ctx.cfg.server.protocol == Protocol::Https;
            let mut response = handle(req, ctx, email).await;
            if https {
                response.headers_mut().insert(
                    "strict-transport-security",
                    HeaderValue::from_static("max-age=31536000"),
                );
            }
            if head {
                *response.body_mut() = Full::new(Bytes::new());
            }
            Ok::<_, Infallible>(response)
        }
    });
    http1::Builder::new()
        .keep_alive(false)
        .max_buf_size(16 * 1024)
        .timer(TokioTimer::new())
        .header_read_timeout(Duration::from_secs(10))
        .serve_connection(TokioIo::new(stream), svc)
        .await?;
    Ok(())
}

fn now_ms() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis() as i64)
        .unwrap_or(0)
}
#[derive(PartialEq)]
enum Fmt {
    Text,
    Json,
    Html,
}
fn pick_format(req: &Request<Incoming>) -> Fmt {
    if req.uri().path() == "/json" {
        return Fmt::Json;
    }
    match req.uri().query() {
        Some("format=json") => return Fmt::Json,
        Some("format=text") => return Fmt::Text,
        Some("format=html") => return Fmt::Html,
        _ => {}
    }
    let accept = req
        .headers()
        .get("accept")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("");
    if accept.contains("text/html") {
        Fmt::Html
    } else if accept.contains("application/json") {
        Fmt::Json
    } else {
        Fmt::Text
    }
}
fn reply(status: StatusCode, ctype: &'static str, body: String) -> Response<Full<Bytes>> {
    let mut r = Response::new(Full::new(Bytes::from(body)));
    *r.status_mut() = status;
    let h = r.headers_mut();
    h.insert(CONTENT_TYPE, HeaderValue::from_static(ctype));
    h.insert(CACHE_CONTROL, HeaderValue::from_static("no-store, private"));
    for (key, value) in [
        ("content-security-policy", "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"),
        ("referrer-policy", "no-referrer"), ("x-content-type-options", "nosniff"),
        ("x-frame-options", "DENY"), ("permissions-policy", "camera=(), microphone=(), geolocation=()"),
        ("cross-origin-resource-policy", "same-origin"), ("connection", "close"),
        ("vary", "Accept"),
    ] { h.insert(key, HeaderValue::from_static(value)); }
    if status == StatusCode::METHOD_NOT_ALLOWED {
        h.insert("allow", HeaderValue::from_static("GET, HEAD"));
    }
    r
}
fn error(
    fmt: &Fmt,
    status: StatusCode,
    title: &str,
    msg: &str,
    cfg: &Config,
) -> Response<Full<Bytes>> {
    match fmt {
        Fmt::Html => reply(
            status,
            "text/html; charset=utf-8",
            render::error(&cfg.display, status.as_u16(), title, msg),
        ),
        Fmt::Json => reply(
            status,
            "application/json; charset=utf-8",
            serde_json::json!({"error": status.as_u16(), "message": msg}).to_string(),
        ),
        Fmt::Text => reply(
            status,
            "text/plain; charset=utf-8",
            format!("{title}: {msg}\n"),
        ),
    }
}
async fn handle(
    req: Request<Incoming>,
    ctx: Arc<Ctx>,
    email: Arc<Option<String>>,
) -> Response<Full<Bytes>> {
    let fmt = pick_format(&req);
    let host = req
        .headers()
        .get("host")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("");
    if !(host.eq_ignore_ascii_case(&ctx.cfg.server.domain)
        || host.eq_ignore_ascii_case(&format!(
            "{}:{}",
            ctx.cfg.server.domain,
            ctx.cfg.server.protocol.port()
        )))
        || req.uri().authority().is_some()
    {
        return error(
            &fmt,
            StatusCode::MISDIRECTED_REQUEST,
            "入口地址不正确",
            "请使用管理员提供的查询链接。",
            &ctx.cfg,
        );
    }
    if !matches!(*req.method(), Method::GET | Method::HEAD) {
        return error(
            &fmt,
            StatusCode::METHOD_NOT_ALLOWED,
            "请求方式不支持",
            "请直接打开查询链接。",
            &ctx.cfg,
        );
    }
    if req.uri().path() == "/favicon.ico" {
        return reply(StatusCode::NO_CONTENT, "image/x-icon", String::new());
    }
    if !matches!(req.uri().path(), "/" | "/json") {
        return error(
            &fmt,
            StatusCode::NOT_FOUND,
            "这页走丢了",
            "返回首页即可查询自己的流量。",
            &ctx.cfg,
        );
    }
    if req
        .uri()
        .query()
        .is_some_and(|q| !matches!(q, "format=json" | "format=text" | "format=html"))
    {
        return error(
            &fmt,
            StatusCode::BAD_REQUEST,
            "查询链接不正确",
            "使用原始查询链接即可，无需填写账号或其他参数。",
            &ctx.cfg,
        );
    }
    let Some(email) = email.as_ref() else {
        return error(
            &fmt,
            StatusCode::FORBIDDEN,
            "还没识别到你的节点",
            "请连接你的节点后重试。",
            &ctx.cfg,
        );
    };
    let t = match ctx.panel.traffic(email).await {
        Ok(t) => t,
        Err(e) => {
            warn!("面板查询失败: {e:#}");
            return error(
                &fmt,
                StatusCode::BAD_GATEWAY,
                "数据暂时没送达",
                "暂时无法获取流量，请稍后刷新。",
                &ctx.cfg,
            );
        }
    };
    let now = now_ms();
    let store = ctx.history.clone();
    let snapshot = t.clone();
    let samples = match tokio::task::spawn_blocking(move || store.sample(&snapshot)).await {
        Ok(Ok(samples)) => samples,
        _ => {
            warn!("History unavailable; current traffic remains available");
            Vec::new()
        }
    };
    let t = t.traffic;
    match fmt {
        Fmt::Json => reply(
            StatusCode::OK,
            "application/json; charset=utf-8",
            if samples.is_empty() {
                render::json(&t, now)
            } else {
                render::json_with_history(&t, now, &samples)
            },
        ),
        Fmt::Html => reply(
            StatusCode::OK,
            "text/html; charset=utf-8",
            render::html_with_history(&t, &ctx.cfg.display, now, &samples),
        ),
        Fmt::Text => reply(
            StatusCode::OK,
            "text/plain; charset=utf-8",
            render::text(&t, &ctx.cfg.display, now),
        ),
    }
}
