use crate::{config::DisplayCfg, history::Sample, panel::ClientTraffic};
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
    history: &'a [Sample],
    history_kind: &'static str,
}

pub fn json(t: &ClientTraffic, now_ms: i64) -> String {
    json_with_history(t, now_ms, &[])
}

pub fn json_with_history(t: &ClientTraffic, now_ms: i64, samples: &[Sample]) -> String {
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
        history: samples,
        history_kind: "query_samples_cumulative_bytes",
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
    html_with_history(t, d, now_ms, &[])
}

pub fn html_with_history(
    t: &ClientTraffic,
    d: &DisplayCfg,
    now_ms: i64,
    samples: &[Sample],
) -> String {
    let c = calc(t);
    let st = status(t, now_ms);
    let tone = if st != "正常" {
        "danger"
    } else if c.percent.is_some_and(|p| p >= 90.0) {
        "warning"
    } else {
        "healthy"
    };
    let remaining = c.remaining.map(human).unwrap_or_else(|| "不限".into());
    let pct = c
        .percent
        .map(|p| format!("{p:.1}"))
        .unwrap_or_else(|| "0".into());
    let quota = if t.total > 0 {
        human(t.total)
    } else {
        "不限".into()
    };
    let expiry = match t.expiry_time {
        0 => "不限期".into(),
        n if n < 0 => format!("激活后 {} 天", n.saturating_abs() / DAY_MS),
        n => fmt_ts(n, d.tz_offset_hours).chars().take(16).collect(),
    };
    let percent_label = if c.percent.is_some() {
        format!("已用 {pct}%")
    } else {
        "无限配额".into()
    };
    page(
        d,
        &format!(
            r#"
<section class="heading"><div><h1>流量概览</h1><p class="account">{email}</p></div><div class="actions"><span class="status {tone}"><i></i>{st}</span><a class="refresh" href="/" aria-label="刷新流量">↻</a></div></section>
<section class="overview" aria-label="流量数据">
<article class="balance"><span class="label">剩余流量</span><div class="balance-value">{remaining}</div><div class="progress-label"><span>{percent_label}</span><span>{quota}</span></div><div class="track" role="progressbar" aria-label="流量使用比例" aria-valuemin="0" aria-valuemax="100" aria-valuenow="{pct}"><div style="width:{pct}%"></div></div></article>
<div class="metrics"><article><span class="label">已用流量</span><strong>{used}</strong></article><article><span class="label">总配额</span><strong>{quota}</strong></article><article><span class="label"><b class="up">↑</b> 上传</span><strong>{up}</strong></article><article><span class="label"><b class="down">↓</b> 下载</span><strong>{down}</strong></article></div>
</section>
<section class="plan"><div><span class="label">到期时间 <small>{tz}</small></span><strong>{expiry}</strong></div><div><span class="label">最近在线</span><strong>{last}</strong></div></section>
<section class="history"><div class="chart-heading"><div><h2>用量记录</h2><p>查询采样 · 累计用量</p></div><div class="legend"><span class="up">● <span>上传</span></span><span class="down">● <span>下载</span></span></div></div>{chart}</section>
<p class="updated">更新于 {updated}</p>"#,
            email = esc(&t.email),
            used = human(c.used),
            up = human(t.up),
            down = human(t.down),
            tz = tz_label(d.tz_offset_hours),
            last = fmt_ts(t.last_online, d.tz_offset_hours)
                .chars()
                .take(16)
                .collect::<String>(),
            chart = chart(samples, d),
            updated = fmt_ts(now_ms, d.tz_offset_hours),
        ),
    )
}

fn chart(samples: &[Sample], d: &DisplayCfg) -> String {
    if samples.len() < 2 {
        return r#"<div class="chart-empty">暂无历史记录</div>"#.into();
    }
    let first = samples.first().unwrap().at_ms;
    let last = samples.last().unwrap().at_ms;
    let span = (last - first).max(1) as f64;
    let max = samples
        .iter()
        .map(|p| p.up.max(p.down))
        .max()
        .unwrap_or(1)
        .max(1);
    let mut up = String::new();
    let mut down = String::new();
    for (i, p) in samples.iter().enumerate() {
        let reset = i == 0 || p.up < samples[i - 1].up || p.down < samples[i - 1].down;
        let command = if reset { 'M' } else { 'L' };
        let x = (p.at_ms - first) as f64 / span * 704.0;
        up.push_str(&format!(
            "{command}{x:.1},{:.1} ",
            150.0 - p.up as f64 / max as f64 * 150.0
        ));
        down.push_str(&format!(
            "{command}{x:.1},{:.1} ",
            150.0 - p.down as f64 / max as f64 * 150.0
        ));
    }
    let date = |at| {
        fmt_ts(at, d.tz_offset_hours)
            .chars()
            .skip(5)
            .take(11)
            .collect::<String>()
    };
    format!(
        r#"<div class="chart-plot"><div class="y-axis" aria-hidden="true"><span>{max_label}</span><span>{half}</span><span>0</span></div><svg class="chart" viewBox="0 0 704 150" preserveAspectRatio="none" role="img" aria-label="按查询日期记录的累计上传下载流量，计数重置时断开曲线"><g class="grid"><path d="M0 0H704 M0 75H704 M0 150H704"/></g><path class="line up" d="{up}"/><path class="line down" d="{down}"/></svg></div><div class="chart-dates"><span>{start}</span><span>{end}</span></div>"#,
        max_label = human(max),
        half = human(max / 2),
        start = date(first),
        end = date(last)
    )
}

pub fn error(d: &DisplayCfg, code: u16, title: &str, msg: &str) -> String {
    page(
        d,
        &format!(
            r#"<section class="error-card"><p class="eyebrow">{code}</p><div class="error-icon" aria-hidden="true">≈</div><h1>{}</h1><p>{}</p><a href="/" class="error-action">重新查询</a></section>"#,
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
            if name == "pending" {
                html(&t, &DisplayCfg::default(), now)
            } else {
                let samples: Vec<_> = (0..14)
                    .map(|i| Sample {
                        at_ms: now - (13 - i) * DAY_MS,
                        up: (t.up as f64 * (i + 1) as f64 / 14.0) as i64,
                        down: (t.down as f64 * ((i + 1) as f64 / 14.0).powf(1.3)) as i64,
                    })
                    .collect();
                html_with_history(&t, &DisplayCfg::default(), now, &samples)
            },
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
    fn chart_uses_real_time_spacing_and_breaks_at_counter_reset() {
        let d = DisplayCfg::default();
        assert!(chart(&[], &d).contains("暂无历史记录"));
        let points = [
            Sample {
                at_ms: 1000,
                up: 10,
                down: 20,
            },
            Sample {
                at_ms: 2000,
                up: 20,
                down: 40,
            },
            Sample {
                at_ms: 5000,
                up: 1,
                down: 2,
            },
        ];
        let html = chart(&points, &d);
        assert!(html.contains("M0.0,112.5 L176.0,75.0 M704.0,146.2"));
        assert!(html.contains("查询日期") && !html.contains("NaN"));
        let zeros = [
            Sample {
                at_ms: 1000,
                up: 0,
                down: 0,
            },
            Sample {
                at_ms: 2000,
                up: 0,
                down: 0,
            },
        ];
        assert!(!chart(&zeros, &d).contains("NaN"));
    }
    #[test]
    fn success_page_has_metrics_without_marketing_or_faq() {
        let html = html(&sample(), &DisplayCfg::default(), 1000);
        for label in ["剩余流量", "上传", "下载", "总配额", "到期时间", "用量记录"]
        {
            assert!(html.contains(label));
        }
        assert!(
            !html.contains("<details>") && !html.contains("用量有数") && !html.contains("<script")
        );
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
