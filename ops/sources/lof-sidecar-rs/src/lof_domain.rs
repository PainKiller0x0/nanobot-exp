use std::{collections::HashMap, path::Path};

use chrono::{DateTime, Datelike, Duration as ChronoDuration, FixedOffset, Timelike, Utc};
use futures::{stream, StreamExt};
use reqwest::Client;
use scraper::{Html as ScraperHtml, Selector};
use serde::{Deserialize, Serialize};
const DEFAULT_COST: f64 = 0.0153;
const PREMIUM_THRESHOLD: f64 = 0.05;
const AMOUNT_THRESHOLD: f64 = 500_000.0;
const LIMIT_THRESHOLD: f64 = 100.0;
const CONSECUTIVE_DAYS: i64 = 3;

const QDII_CODES: [&str; 40] = [
    "159605", "159607", "159612", "159632", "159655", "159659", "159660", "159941", "160140",
    "160216", "160416", "160719", "160723", "161116", "161125", "161126", "161127", "161128",
    "161129", "161130", "161815", "162411", "162415", "162719", "163208", "164701", "164824",
    "164906", "165513", "501018", "513030", "513050", "513080", "513100", "513110", "513290",
    "513300", "513390", "513500", "513650",
];

#[derive(Debug, Clone)]
struct Fund {
    code: String,
    name: String,
    premium: Option<f64>,
    rt_nav: Option<f64>,
    rt_premium_pct: Option<f64>,
    latest_nav: Option<f64>,
    latest_premium_pct: Option<f64>,
    price: Option<f64>,
    change_pct: Option<f64>,
    amount: Option<f64>,
    limit: Option<f64>,
    suspended: bool,
    limit_text: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct BoardPoint {
    date: String,
    premium_pct: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub(crate) struct BoardRow {
    code: String,
    name: String,
    rt_nav: Option<f64>,
    pub(crate) rt_premium_pct: Option<f64>,
    latest_nav: Option<f64>,
    latest_premium_pct: Option<f64>,
    price: Option<f64>,
    change_pct: Option<f64>,
    amount_wan: Option<f64>,
    limit_text: String,
    suspended: bool,
    consecutive_days: i64,
    history: Vec<BoardPoint>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub(crate) struct BoardData {
    updated_at: DateTime<Utc>,
    pub(crate) rows: Vec<BoardRow>,
}

pub(crate) fn is_trading_session(now_utc: DateTime<Utc>) -> bool {
    let sh_tz = FixedOffset::east_opt(8 * 3600).expect("tz");
    let sh = now_utc.with_timezone(&sh_tz);
    let wd = sh.weekday().number_from_monday();
    if wd > 5 {
        return false;
    }
    let hm = sh.hour() * 60 + sh.minute();
    let morning = (9 * 60 + 30) <= hm && hm <= (11 * 60 + 30);
    let afternoon = (13 * 60) <= hm && hm <= (15 * 60);
    morning || afternoon
}

pub(crate) async fn run_native_report(
    client: &Client,
    script_dir: &Path,
    tag: &str,
) -> Result<(String, BoardData), String> {
    let history_path = script_dir.join("premium_history.json");

    let funds = fetch_all_funds(client).await;
    if funds.is_empty() {
        return Err("no fund data fetched".to_string());
    }

    let mut history = load_history(&history_path).await;
    update_history(&mut history, &funds);
    save_history(&history_path, &history).await;

    let report = generate_report(tag, &funds, &history);
    let board = build_board(&funds, &history);
    if report.trim().is_empty() {
        return Err("empty report generated".to_string());
    }
    Ok((report, board))
}

async fn fetch_all_funds(client: &Client) -> Vec<Fund> {
    let codes: Vec<String> = QDII_CODES.iter().map(|c| (*c).to_string()).collect();
    stream::iter(codes)
        .map(|code| async move { fetch_one(client, &code).await })
        .buffer_unordered(8)
        .collect::<Vec<Fund>>()
        .await
}

async fn fetch_one(client: &Client, code: &str) -> Fund {
    let url = format!("https://www.haoetf.com/qdii/{}", code);
    match client.get(url).send().await {
        Ok(resp) if resp.status().is_success() => match resp.text().await {
            Ok(body) => parse_fund_detail(&body, code).unwrap_or_else(|| fallback_fund(code)),
            Err(_) => fallback_fund(code),
        },
        _ => fallback_fund(code),
    }
}

fn parse_fund_detail(html: &str, code: &str) -> Option<Fund> {
    let doc = ScraperHtml::parse_document(html);
    let table_sel = Selector::parse("table").ok()?;
    let tr_sel = Selector::parse("tr").ok()?;
    let cell_sel = Selector::parse("th, td").ok()?;

    for table in doc.select(&table_sel) {
        let rows: Vec<Vec<String>> = table
            .select(&tr_sel)
            .map(|tr| {
                tr.select(&cell_sel)
                    .map(|c| c.text().collect::<Vec<_>>().join("").trim().to_string())
                    .collect::<Vec<String>>()
            })
            .filter(|r| !r.is_empty())
            .collect();

        if rows.len() < 2 {
            continue;
        }
        let header = &rows[0];
        let is_main_board = header.iter().any(|h| h.contains("实时估值"))
            && header.iter().any(|h| h.contains("最新估值"))
            && header.iter().any(|h| h.contains("现价"))
            && header.iter().any(|h| h.contains("成交额"));
        if !is_main_board {
            continue;
        }
        let maybe_row = rows.iter().skip(1).find(|r| {
            r.get(0)
                .map(|s| s.chars().filter(|c| c.is_ascii_digit()).collect::<String>() == code)
                .unwrap_or(false)
        });
        let Some(cols) = maybe_row else {
            continue;
        };

        let pick = |names: &[&str]| -> Option<String> {
            for name in names {
                if let Some(idx) = header.iter().position(|h| h.contains(name)) {
                    if let Some(v) = cols.get(idx) {
                        if !v.trim().is_empty() {
                            return Some(v.trim().to_string());
                        }
                    }
                }
            }
            None
        };

        let name = cols.get(1).cloned().unwrap_or_else(|| code.to_string());
        let rt_nav = pick(&["实时估值"]).and_then(|v| parse_float(&v));
        let rt_premium_pct = pick(&["实时溢价"]).and_then(|v| parse_float(&v));
        let latest_nav = pick(&["最新估值"]).and_then(|v| parse_float(&v));
        let latest_premium_pct = pick(&["最新溢价"]).and_then(|v| parse_float(&v));
        let premium = latest_premium_pct.map(|v| v / 100.0);
        let price = pick(&["现价"]).and_then(|v| parse_float(&v));
        let change_pct = pick(&["涨跌"]).and_then(|v| parse_float(&v));
        let amount =
            pick(&["成交额(万元)", "成交额"]).and_then(|v| parse_float(&v).map(|x| x * 10_000.0));

        let mut limit_text = pick(&["申购限额", "累计申购上限"]).unwrap_or_default();
        // Some pages drop optional middle columns, causing tail fields to shift.
        // In that case infer limit from the field before fee columns, but avoid "xx万份" min-unit values.
        if limit_text.is_empty() && cols.len() >= 4 {
            let tail = cols[cols.len() - 4].trim();
            let looks_like_limit = tail.contains("暂停")
                || tail.contains("不限")
                || tail.contains('元')
                || tail == "-";
            if looks_like_limit {
                limit_text = tail.to_string();
            }
        }

        let suspended = limit_text.contains("暂停");
        let limit = if suspended {
            Some(0.0)
        } else if limit_text.contains('无') || limit_text.contains("不限") {
            None
        } else {
            parse_float(&limit_text)
        };

        return Some(Fund {
            code: code.to_string(),
            name,
            premium,
            rt_nav,
            rt_premium_pct,
            latest_nav,
            latest_premium_pct,
            price,
            change_pct,
            amount,
            limit,
            suspended,
            limit_text,
        });
    }

    None
}

fn fallback_fund(code: &str) -> Fund {
    Fund {
        code: code.to_string(),
        name: code.to_string(),
        premium: None,
        rt_nav: None,
        rt_premium_pct: None,
        latest_nav: None,
        latest_premium_pct: None,
        price: None,
        change_pct: None,
        amount: None,
        limit: None,
        suspended: false,
        limit_text: String::new(),
    }
}

fn parse_float(input: &str) -> Option<f64> {
    let filtered: String = input
        .chars()
        .filter(|c| c.is_ascii_digit() || *c == '.' || *c == '-')
        .collect();
    if filtered.is_empty() {
        None
    } else {
        filtered.parse::<f64>().ok()
    }
}

type HistoryMap = HashMap<String, HashMap<String, f64>>;

async fn load_history(path: &Path) -> HistoryMap {
    match tokio::fs::read_to_string(path).await {
        Ok(content) => serde_json::from_str::<HistoryMap>(&content).unwrap_or_default(),
        Err(_) => HashMap::new(),
    }
}

async fn save_history(path: &Path, history: &HistoryMap) {
    if let Ok(content) = serde_json::to_string_pretty(history) {
        let _ = tokio::fs::write(path, content).await;
    }
}

fn update_history(history: &mut HistoryMap, funds: &[Fund]) {
    let sh_tz = FixedOffset::east_opt(8 * 3600).expect("tz");
    let today = Utc::now().with_timezone(&sh_tz).date_naive().to_string();
    let cutoff =
        (Utc::now().with_timezone(&sh_tz).date_naive() - ChronoDuration::days(30)).to_string();

    for f in funds {
        if let Some(p) = f.premium {
            history
                .entry(f.code.clone())
                .or_default()
                .insert(today.clone(), (p * 100.0 * 100.0).round() / 100.0);
        }
    }

    for (_code, dmap) in history.iter_mut() {
        dmap.retain(|k, _| k >= &cutoff);
    }
}

fn consecutive_days(history: &HistoryMap, code: &str, threshold_percent: f64, days: i64) -> i64 {
    let sh_tz = FixedOffset::east_opt(8 * 3600).expect("tz");
    let today = Utc::now().with_timezone(&sh_tz).date_naive();

    let mut c = 0;
    for i in 0..days {
        let d = today - ChronoDuration::days(i);
        let k = d.to_string();
        if let Some(v) = history.get(code).and_then(|m| m.get(&k)) {
            if *v >= threshold_percent {
                c += 1;
            } else {
                break;
            }
        } else if d.weekday().number_from_monday() <= 5 {
            break;
        }
    }
    c
}

fn format_limit(limit: Option<f64>, limit_text: &str) -> String {
    let raw = limit_text.trim();
    if raw.contains("暂停") {
        return "暂停申购".to_string();
    }
    if !raw.is_empty() && raw != "-" {
        return raw.to_string();
    }
    match limit {
        None => "-".to_string(),
        Some(v) if v >= 100_000_000.0 => format!("{:.0}亿", v / 100_000_000.0),
        Some(v) if v >= 10_000.0 => format!("{:.0}万", v / 10_000.0),
        Some(v) => format!("{:.0}元", v),
    }
}

fn generate_report(tag: &str, funds: &[Fund], history: &HistoryMap) -> String {
    let sh_tz = FixedOffset::east_opt(8 * 3600).expect("tz");
    let now = Utc::now().with_timezone(&sh_tz);

    let mut with_premium: Vec<&Fund> = funds.iter().filter(|f| f.premium.is_some()).collect();
    with_premium.sort_by(|a, b| {
        b.premium
            .partial_cmp(&a.premium)
            .unwrap_or(std::cmp::Ordering::Equal)
    });

    let premium_count = funds
        .iter()
        .filter(|f| f.premium.unwrap_or(0.0) > 0.0)
        .count();
    let suspended_count = funds.iter().filter(|f| f.suspended).count();

    let mut opportunities: Vec<(&Fund, f64, i64)> = Vec::new();
    for f in funds {
        if let Some(p) = f.premium {
            let amount_ok = f.amount.unwrap_or(0.0) >= AMOUNT_THRESHOLD;
            let limit_ok = f.limit.map(|v| v >= LIMIT_THRESHOLD).unwrap_or(true);
            let days = consecutive_days(history, &f.code, 5.0, CONSECUTIVE_DAYS);
            if p >= PREMIUM_THRESHOLD
                && amount_ok
                && !f.suspended
                && limit_ok
                && days >= CONSECUTIVE_DAYS
            {
                opportunities.push((f, p - DEFAULT_COST, days));
            }
        }
    }
    opportunities.sort_by(|a, b| {
        b.0.premium
            .partial_cmp(&a.0.premium)
            .unwrap_or(std::cmp::Ordering::Equal)
    });

    let mut lines = Vec::new();
    lines.push(format!(
        "📊 QDII-LOF套利监控 {} {}",
        now.format("%Y-%m-%d %H:%M"),
        tag
    ));
    lines.push("════════════════════════════════════════".to_string());
    lines.push(format!(
        "📦 共 {} 只QDII | 📈 {} 只有溢价 | 📉 {} 只暂停申购",
        funds.len(),
        premium_count,
        suspended_count
    ));
    lines.push(format!("💸 默认成本: {:.2}%", DEFAULT_COST * 100.0));
    lines.push("".to_string());

    lines.push("🔥 套利机会（溢价≥5% + 成交额≥50万 + 限额≥100元）".to_string());
    if opportunities.is_empty() {
        lines.push("   暂无符合条件的套利机会 ⏳".to_string());
    } else {
        for (f, profit, days) in opportunities.iter().take(10) {
            lines.push(format!(
                "🔥 [{}]{} 溢价{:.1}% 利润{:.1}% 限额:{} 连续{}天",
                f.code,
                f.name,
                f.premium.unwrap_or(0.0) * 100.0,
                profit * 100.0,
                format_limit(f.limit, &f.limit_text),
                days
            ));
        }
    }

    lines.push("".to_string());
    lines.push("📊 溢价率TOP10".to_string());
    for (idx, f) in with_premium.iter().take(10).enumerate() {
        let p = f.premium.unwrap_or(0.0) * 100.0;
        let level = if p >= 10.0 {
            "🔴"
        } else if p >= 5.0 {
            "🟠"
        } else {
            "🟡"
        };
        let pause = if f.suspended { "🚫暂停" } else { "" };
        let days = consecutive_days(history, &f.code, 5.0, CONSECUTIVE_DAYS);
        let badge = if days >= CONSECUTIVE_DAYS {
            "✅3天"
        } else if days > 0 {
            "📅2天"
        } else {
            ""
        };
        lines.push(format!(
            "   {}. [{}]{} {}{:.1}% {} {}",
            idx + 1,
            f.code,
            f.name,
            level,
            p,
            pause,
            badge
        ));
    }

    lines.push("".to_string());
    lines.push("⚠️ 高溢价但暂不符合".to_string());
    let mut shown = 0;
    for f in with_premium.iter() {
        let p = f.premium.unwrap_or(0.0);
        if p < PREMIUM_THRESHOLD {
            continue;
        }
        let amount_ok = f.amount.unwrap_or(0.0) >= AMOUNT_THRESHOLD;
        let limit_ok = f.limit.map(|v| v >= LIMIT_THRESHOLD).unwrap_or(true);
        let days = consecutive_days(history, &f.code, 5.0, CONSECUTIVE_DAYS);
        let eligible = amount_ok && !f.suspended && limit_ok && days >= CONSECUTIVE_DAYS;
        if eligible {
            continue;
        }
        let mut reasons = Vec::new();
        if f.suspended {
            reasons.push("🚫暂停申购".to_string());
        }
        if !amount_ok {
            reasons.push(format!("💧成交额{}", f.amount.unwrap_or(0.0)));
        }
        if !limit_ok {
            reasons.push(format!("🔒限额{}", format_limit(f.limit, &f.limit_text)));
        }
        if days < CONSECUTIVE_DAYS {
            reasons.push(format!("📅连续仅{}天(需3天)", days));
        }
        lines.push(format!(
            "  [{}]{} {:>5.2}% {}",
            f.code,
            f.name,
            p * 100.0,
            reasons.join(" | ")
        ));
        shown += 1;
        if shown >= 8 {
            break;
        }
    }
    if shown == 0 {
        lines.push("  暂无".to_string());
    }

    lines.join("\n")
}

fn build_board(funds: &[Fund], history: &HistoryMap) -> BoardData {
    let mut rows: Vec<BoardRow> = funds
        .iter()
        .map(|f| BoardRow {
            code: f.code.clone(),
            name: f.name.clone(),
            rt_nav: f.rt_nav,
            rt_premium_pct: f.rt_premium_pct,
            latest_nav: f.latest_nav,
            latest_premium_pct: f.latest_premium_pct,
            price: f.price,
            change_pct: f.change_pct,
            amount_wan: f.amount.map(|a| a / 10_000.0),
            limit_text: format_limit(f.limit, &f.limit_text),
            suspended: f.suspended,
            consecutive_days: consecutive_days(history, &f.code, 5.0, CONSECUTIVE_DAYS),
            history: history_points(history, &f.code, 30),
        })
        .collect();

    rows.sort_by(|a, b| {
        b.rt_premium_pct
            .unwrap_or(-9999.0)
            .partial_cmp(&a.rt_premium_pct.unwrap_or(-9999.0))
            .unwrap_or(std::cmp::Ordering::Equal)
    });

    BoardData {
        updated_at: Utc::now(),
        rows,
    }
}

fn history_points(history: &HistoryMap, code: &str, days: i64) -> Vec<BoardPoint> {
    let sh_tz = FixedOffset::east_opt(8 * 3600).expect("tz");
    let today = Utc::now().with_timezone(&sh_tz).date_naive();

    let mut points = Vec::new();
    for i in (0..days).rev() {
        let d = today - ChronoDuration::days(i);
        let k = d.to_string();
        if let Some(v) = history.get(code).and_then(|m| m.get(&k)) {
            points.push(BoardPoint {
                date: k,
                premium_pct: *v,
            });
        }
    }
    points
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;

    #[test]
    fn trading_session_matches_shanghai_market_hours() {
        let utc = Utc.with_ymd_and_hms(2026, 5, 13, 1, 45, 0).unwrap();
        assert!(is_trading_session(utc));

        let before_open = Utc.with_ymd_and_hms(2026, 5, 13, 1, 20, 0).unwrap();
        assert!(!is_trading_session(before_open));

        let weekend = Utc.with_ymd_and_hms(2026, 5, 16, 2, 0, 0).unwrap();
        assert!(!is_trading_session(weekend));
    }

    #[test]
    fn parse_float_handles_percent_and_money_text() {
        assert_eq!(parse_float("+5.32%"), Some(5.32));
        assert_eq!(parse_float("1,234.50万元"), Some(1234.50));
        assert_eq!(parse_float("暂停申购"), None);
    }

    #[test]
    fn format_limit_prefers_raw_limit_text() {
        assert_eq!(format_limit(Some(0.0), "暂停申购"), "暂停申购");
        assert_eq!(format_limit(None, "不限"), "不限");
        assert_eq!(format_limit(Some(20000.0), ""), "2万");
    }
}
