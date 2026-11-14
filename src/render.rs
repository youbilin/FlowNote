use crate::{config::DisplayCfg, panel::ClientTraffic};
use serde::Serialize;
use time::{macros::format_description, OffsetDateTime, UtcOffset};

const DAY_MS: i64 = 86_400_000;

pub fn human(bytes: i64) -> String {
    const K: f64 = 1024.0;
    let n = bytes.max(0);
    let b = n as f64;
    if b >= K * K * K * K {
        format!("{:.2} TiB", b / (K * K * K * K))
    } else if b >= K * K * K {
        format!("{:.2} GiB", b / (K * K * K))
    } else if b >= K * K {
        format!("{:.2} MiB", b / (K * K))
    } else if b >= K {
        format!("{:.1} KiB", b / K)
    } else {
        format!("{n} B")
    }
}

pub fn fmt_ts(ms: i64, tz_h: i8) -> String {
    if ms <= 0 {
        return "-".into();
    }
    let off = UtcOffset::from_hms(tz_h, 0, 0).unwrap_or(UtcOffset::UTC);
    OffsetDateTime::from_unix_timestamp(ms.div_euclid(1000))
        .ok()
        .map(|d| d.to_offset(off))
        .and_then(|d| {
            d.format(format_description!(
                "[year]-[month]-[day] [hour]:[minute]:[second]"
            ))
            .ok()
        })
        .unwrap_or_else(|| "-".into())
}

fn tz_label(tz_h: i8) -> String {
    if tz_h >= 0 {
        format!("UTC+{tz_h}")
    } else {
        format!("UTC{tz_h}")
    }
}

pub fn status(t: &ClientTraffic, now_ms: i64) -> &'static str {
    if !t.enable {
        "已停用"
    } else if t.total > 0 && t.up.max(0).saturating_add(t.down.max(0)) >= t.total {
        "流量已用尽"
    } else if t.expiry_time > 0 && t.expiry_time <= now_ms {
        "已过期"
    } else {
        "正常"
    }
}

fn expiry_line(t: &ClientTraffic, d: &DisplayCfg, now_ms: i64) -> String {
    match t.expiry_time {
        0 => "不限".into(),
        e if e < 0 => format!("首次使用后 {} 天", e.saturating_abs() / DAY_MS),
        e => {
            let left = (e - now_ms).div_euclid(DAY_MS);
            let when = format!(
                "{} ({})",
                fmt_ts(e, d.tz_offset_hours),
                tz_label(d.tz_offset_hours)
            );
            if e > now_ms {
                format!("{when},剩余 {left} 天")
            } else {
                format!("{when},已过期")
            }
        }
    }
}

struct Calc {
    used: i64,
    remaining: Option<i64>,
    percent: Option<f64>,
}

fn calc(t: &ClientTraffic) -> Calc {
    let used = t.up.max(0).saturating_add(t.down.max(0));
    if t.total > 0 {
        Calc {
            used,
            remaining: Some((t.total - used).max(0)),
            percent: Some((used as f64 / t.total as f64 * 100.0).clamp(0.0, 100.0)),
        }
    } else {
        Calc {
            used,
            remaining: None,
            percent: None,
        }
    }
}

pub fn text(t: &ClientTraffic, d: &DisplayCfg, now_ms: i64) -> String {
    let c = calc(t);
    let quota = match c.percent {
        Some(p) => format!("{} / {} ({:.1}%)", human(c.used), human(t.total), p),
        None => format!("{} / 不限", human(c.used)),
    };
    let remaining = c.remaining.map(human).unwrap_or_else(|| "不限".into());
    format!(
        "{title}\n\
         ────────────────────────────\n\
         账号:    {email}\n\
         状态:    {status}\n\
         上传:    {up}\n\
         下载:    {down}\n\
         已用:    {quota}\n\
         剩余:    {remaining}\n\
         到期:    {expiry}\n\
         最近在线: {last}\n\
         ────────────────────────────\n\
         数据来自面板统计,可能有数秒到数十秒延迟。\n",
        title = d.title,
        email = t.email,
        status = status(t, now_ms),
        up = human(t.up),
        down = human(t.down),
        expiry = expiry_line(t, d, now_ms),
        last = fmt_ts(t.last_online, d.tz_offset_hours),
    )
}

#[derive(Serialize)]
struct JsonOut<'a> {
    email: &'a str,
    status: &'static str,
    enable: bool,
    up: i64,
    down: i64,
    used: i64,
    /// 0 = 不限
    total: i64,
    remaining: Option<i64>,
    percent_used: Option<f64>,
    /// 0 = 不限;负数 = 首次使用后起算的时长(毫秒)
    expiry_time_ms: i64,
    last_online_ms: i64,
    generated_at_ms: i64,
}

pub fn json(t: &ClientTraffic, now_ms: i64) -> String {
    let c = calc(t);
    serde_json::to_string_pretty(&JsonOut {
        email: &t.email,
        status: status(t, now_ms),
        enable: t.enable,
        up: t.up,
        down: t.down,
        used: c.used,
        total: t.total,
        remaining: c.remaining,
        percent_used: c.percent,
        expiry_time_ms: t.expiry_time,
        last_online_ms: t.last_online,
        generated_at_ms: now_ms,
    })
    .unwrap_or_else(|_| "{}".into())
        + "\n"
}

fn esc(s: &str) -> String {
    s.replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
}

fn page(d: &DisplayCfg, content: &str) -> String {
    include_str!("ui/page.html")
        .replace("@@STYLE@@", include_str!("ui/style.css"))
        .replace("@@TITLE@@", &esc(&d.title))
        .replace("@@CONTENT@@", content)
}

pub fn html(t: &ClientTraffic, d: &DisplayCfg, now_ms: i64) -> String {
    let c = calc(t);
    let st = status(t, now_ms);
    let low = c.percent.is_some_and(|p| p >= 90.0);
    let tone = if st != "正常" {
        "danger"
    } else if low {
        "warning"
    } else {
        "healthy"
    };
    let remaining = c.remaining.map(human).unwrap_or_else(|| "不限流量".into());
    let pct = c
        .percent
        .map(|p| format!("{p:.1}"))
        .unwrap_or_else(|| "0".into());
    let quota = if t.total > 0 {
        human(t.total)
    } else {
        "不限".into()
    };
    let progress = if t.total > 0 {
        format!("已使用 {pct}%")
    } else {
        "按需使用 · 无配额上限".into()
    };
    let notice = if st != "正常" {
        "当前账号不可用，请联系管理员确认配额或有效期。"
    } else if low {
        "剩余流量不足 10%，建议提前联系管理员，避免使用中断。"
    } else {
        "一切就绪，安心使用。这里仅展示你当前连接账号的数据。"
    };
    let content = format!(
        r#"
<section class="intro"><div><p class="eyebrow">YOUR CONNECTION, AT A GLANCE</p><h1>用量有数，连接有度。</h1><p class="muted">一眼了解流量与有效期，把余下的时间留给生活。</p></div><a class="refresh" href="/" aria-label="刷新流量数据">↻ <span>刷新数据</span></a></section>
<section class="dashboard {tone}" aria-label="我的流量概览">
<article class="balance"><div class="card-top"><span>剩余可用流量</span><span class="badge"><i></i>{st}</span></div><div class="balance-value">{remaining}</div><p class="balance-note">每一份余量，都心中有数。</p>
<div class="progress-label"><span>{progress}</span><span>总配额 {quota}</span></div><div class="track" role="progressbar" aria-label="流量使用比例" aria-valuemin="0" aria-valuemax="100" aria-valuenow="{pct}"><div style="width:{pct}%"></div></div><div class="usage"><div><span>累计已用</span><strong>{used}</strong></div><div><span>当前账号</span><strong class="account">{email}</strong></div></div><div class="balance-art" aria-hidden="true">≈</div></article>
<article class="details"><p class="eyebrow">PLAN DETAILS</p><h2>你的连接档案</h2><dl><div><dt>账号状态</dt><dd>{st}</dd></div><div><dt>到期时间</dt><dd>{expiry}</dd></div><div><dt>最近在线</dt><dd>{last}</dd></div></dl><p class="tiny">时间按 {tz} 显示。未激活套餐的有效期从首次使用起计算。</p></article>
</section>
<section class="transfer" aria-label="流量明细"><article><span class="direction">↑</span><div><p>累计上传</p><strong>{up}</strong></div><span class="metric-hint">UPLOAD</span></article><article><span class="direction">↓</span><div><p>累计下载</p><strong>{down}</strong></div><span class="metric-hint">DOWNLOAD</span></article></section>
<aside class="notice {tone}"><span aria-hidden="true">ⓘ</span><div><strong>{notice}</strong><p>面板统计可能延迟数秒到数十秒；点击刷新时，服务端可能复用短时间内的缓存。</p></div></aside>
<section class="help"><div><p class="eyebrow">JUST FOR YOU</p><h2>简单查询，不多打扰。</h2><p>无需登录、无需订阅。先连接你的节点，再打开此页即可。</p></div><details><summary>切换节点后，怎样查询新账号？</summary><p>关闭当前页面，切换到对应节点后重新打开查询链接。如果客户端复用了旧的代理连接，请断开并重连代理后再试。</p></details><details><summary>流量或有效期有疑问？</summary><p>这里展示的是面板统计，并非实时测速。配额调整、续期和账号状态问题，请联系给你提供节点的管理员。</p></details></section>
<div class="updated">本次查询时间 {updated} · 面板统计非实时</div>"#,
        used = human(c.used),
        email = esc(&t.email),
        expiry = esc(&expiry_line(t, d, now_ms)),
        last = fmt_ts(t.last_online, d.tz_offset_hours),
        tz = tz_label(d.tz_offset_hours),
        up = human(t.up),
        down = human(t.down),
        updated = fmt_ts(now_ms, d.tz_offset_hours)
    );
    page(d, &content)
}

pub fn error(d: &DisplayCfg, code: u16, title: &str, msg: &str) -> String {
    page(
        d,
        &format!(
            r#"<section class="error-card"><p class="eyebrow">CONNECTION NOTE / {code}</p><div class="error-icon" aria-hidden="true">≈</div><h1>{}</h1><p>{}</p><a href="/" class="refresh">返回首页 · 重新查询</a><p class="tiny">无需输入账号、订阅链接或面板密码。</p></section>"#,
            esc(title),
            esc(msg)
        ),
    )
}

/// Offline synthetic fixtures, never reads panel/logs or starts a server.
pub fn preview(dir: &std::path::Path) -> anyhow::Result<()> {
    std::fs::create_dir_all(dir)?;
    std::fs::write(dir.join("favicon.ico"), [])?;
    let now = 1_794_614_400_000;
    let sample = ClientTraffic {
        email: "weekend-user".into(),
        enable: true,
        up: 8 * 1024_i64.pow(3),
        down: 34 * 1024_i64.pow(3),
        total: 200 * 1024_i64.pow(3),
        expiry_time: now + 27 * DAY_MS,
        last_online: now - 90_000,
    };
    for (name, t) in [
        ("index", sample.clone()),
        (
            "low",
            ClientTraffic {
                down: 185 * 1024_i64.pow(3),
                ..sample.clone()
            },
        ),
        (
            "exhausted",
            ClientTraffic {
                down: sample.total,
                ..sample.clone()
            },
        ),
        (
            "expired",
            ClientTraffic {
                expiry_time: now - DAY_MS,
                ..sample.clone()
            },
        ),
        (
            "disabled",
            ClientTraffic {
                enable: false,
                ..sample.clone()
            },
        ),
        (
            "unlimited",
            ClientTraffic {
                total: 0,
                expiry_time: 0,
                ..sample.clone()
            },
        ),
        (
            "pending",
            ClientTraffic {
                expiry_time: -30 * DAY_MS,
                ..sample.clone()
            },
        ),
    ] {
        std::fs::write(
            dir.join(format!("{name}.html")),
            html(&t, &DisplayCfg::default(), now),
        )?;
    }
    for (code, title, msg) in [
        (403, "还没识别到你的节点", "请连接管理员提供的节点后重试。"),
        (502, "数据暂时没送达", "流量服务暂时无法连接，请稍后刷新。"),
    ] {
        std::fs::write(
            dir.join(format!("{code}.html")),
            error(&DisplayCfg::default(), code, title, msg),
        )?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sample() -> ClientTraffic {
        ClientTraffic {
            email: "alice".into(),
            enable: true,
            up: 1_048_576,
            down: 2_097_152,
            total: 10 * 1024 * 1024 * 1024,
            expiry_time: 1_767_225_600_000, // 2026-01-01T00:00:00Z
            last_online: 1_767_225_000_000,
        }
    }

    #[test]
    fn human_sizes() {
        assert_eq!(human(0), "0 B");
        assert_eq!(human(1536), "1.5 KiB");
        assert_eq!(human(3 * 1024 * 1024), "3.00 MiB");
        assert_eq!(human(5 * 1024 * 1024 * 1024), "5.00 GiB");
    }

    #[test]
    fn timestamp_with_offset() {
        assert_eq!(fmt_ts(1_767_225_600_000, 8), "2026-01-01 08:00:00");
        assert_eq!(fmt_ts(0, 8), "-");
    }

    #[test]
    fn status_logic() {
        let now = 1_700_000_000_000;
        let mut t = sample();
        assert_eq!(status(&t, now), "正常");
        t.enable = false;
        assert_eq!(status(&t, now), "已停用");
        t.enable = true;
        t.up = t.total;
        assert_eq!(status(&t, now), "流量已用尽");
        t.up = 0;
        assert_eq!(status(&t, 1_800_000_000_000), "已过期");
    }

    #[test]
    fn unlimited_quota_and_expiry() {
        let mut t = sample();
        t.total = 0;
        t.expiry_time = 0;
        let s = text(&t, &DisplayCfg::default(), 1_700_000_000_000);
        assert!(s.contains("/ 不限") && s.contains("到期:    不限"));
    }

    #[test]
    fn outputs_do_not_leak_extra_fields() {
        let j = json(&sample(), 1_700_000_000_000);
        assert!(j.contains("\"used\": 3145728"));
        assert!(!j.contains("uuid") && !j.contains("subId"));
        assert!(html(&sample(), &DisplayCfg::default(), 1_700_000_000_000).contains("alice"));
    }
    #[test]
    fn escapes_untrusted_values_and_handles_extremes() {
        let mut t = sample();
        t.email = "<script>alert(1)</script>".into();
        t.up = i64::MAX;
        t.down = i64::MAX;
        t.expiry_time = i64::MIN;
        let output = html(&t, &DisplayCfg::default(), 0);
        assert!(!output.contains("<script>"));
        assert!(output.contains("&lt;script&gt;"));
        assert!(output.contains("aria-valuenow=\"100.0\""));
        assert!(json(&t, 0).contains(&i64::MAX.to_string()));
        assert!(!error(&DisplayCfg::default(), 403, "<img>", "<script>").contains("<script>"));
    }
}
