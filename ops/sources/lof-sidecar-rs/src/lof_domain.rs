use std::{collections::HashMap, path::Path};

use chrono::{
    DateTime, Datelike, Duration as ChronoDuration, FixedOffset, NaiveDate, Timelike, Utc,
};
use encoding_rs::Encoding;
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
    let mut fund = match client.get(url).send().await {
        Ok(resp) if resp.status().is_success() => match resp.text().await {
            Ok(body) => parse_fund_detail(&body, code).unwrap_or_else(|| fallback_fund(code)),
            Err(_) => fallback_fund(code),
        },
        _ => fallback_fund(code),
    };

    if is_etf_creation_unit_code(&fund.code) && !fund.suspended {
        if let Some(detail) = fetch_etf_barrier_detail(client, &fund.code).await {
            fund.limit_text = detail;
        }
    }

    fund
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

async fn fetch_etf_barrier_detail(client: &Client, code: &str) -> Option<String> {
    match code {
        "159941" => fetch_gffunds_etf_barrier(client, code).await,
        "513100" => fetch_guotai_etf_barrier(client, "513101").await,
        "513300" => fetch_chinaamc_etf_barrier(client, code).await,
        "159660" => {
            fetch_html_etf_barrier(
                client,
                &format!("https://www.99fund.com/main/products/pofund/{code}/ETFlist.shtml"),
                Some("gb18030"),
            )
            .await
        }
        "513390" | "513500" => {
            fetch_html_etf_barrier(
                client,
                &format!("https://www.bosera.com/fund/etfList.do?fundCode={code}"),
                None,
            )
            .await
        }
        "159632" => {
            fetch_html_etf_barrier(
                client,
                &format!("https://www.huaan.com.cn/etf/{code}/sgshqd.jsp"),
                Some("gb2312"),
            )
            .await
        }
        _ => None,
    }
}

async fn fetch_gffunds_etf_barrier(client: &Client, code: &str) -> Option<String> {
    let date = shanghai_today().format("%Y%m%d").to_string();
    let url = format!("http://www.gffunds.com.cn/proxy/pcflist/{code}?_time={date}");
    let html = fetch_text(client, &url, Some("utf-8")).await?;
    let min_unit =
        extract_div_id_value(&html, "CreationRedemptionUnit").and_then(|v| parse_float(&v));
    let min_value = extract_div_id_value(&html, "NAVperCU").and_then(|v| parse_float(&v));
    let creation = extract_div_id_value(&html, "Creation");
    let redemption = extract_div_id_value(&html, "Redemption");
    let status = format_creation_redemption_status(creation.as_deref(), redemption.as_deref());

    format_etf_barrier_detail(min_unit, min_value, None, status.as_deref())
}

async fn fetch_guotai_etf_barrier(client: &Client, pcf_code: &str) -> Option<String> {
    let date = shanghai_today().format("%Y-%m-%d").to_string();
    let body = serde_json::json!({
        "api": "info.etf",
        "params": {
            "code": pcf_code,
            "date": date,
        }
    })
    .to_string();
    let resp = post_guotai_etf_json(client, body).await?;
    if !resp.status().is_success() {
        return None;
    }
    let value: serde_json::Value = resp.json().await.ok()?;
    let mut min_unit = None;
    let mut min_value = None;
    let mut daily_limit = None;
    let mut status = None;

    if let Some(props) = value.pointer("/t-1/properties").and_then(|v| v.as_array()) {
        min_value = json_array_field(props, "NAVperCU");
    }
    if let Some(props) = value.pointer("/t/properties").and_then(|v| v.as_array()) {
        min_unit = json_array_field(props, "CreationRedemptionUnit");
        daily_limit = json_array_field(props, "CreationLimit")
            .or_else(|| json_array_field(props, "NetCreationLimit"));
        status = json_array_text(props, "CreationRedemptionSwitch");
    }

    format_etf_barrier_detail(min_unit, min_value, daily_limit, status.as_deref())
}

async fn post_guotai_etf_json(_client: &Client, body: String) -> Option<reqwest::Response> {
    let url = "https://e.gtfund.com/Etrade/Public/cochin/info.etf";
    let client = reqwest::Client::builder()
        .redirect(reqwest::redirect::Policy::none())
        .build()
        .ok()?;
    let resp = client
        .post(url)
        .header("Content-Type", "application/json; charset=utf-8")
        .header("User-Agent", "Mozilla/5.0")
        .header(
            "Referer",
            "https://e.gtfund.com/Etrade/Jijin/view/id/513100",
        )
        .body(body.clone())
        .send()
        .await
        .ok()?;
    if !resp.status().is_redirection() {
        return Some(resp);
    }

    let cookie = resp
        .headers()
        .get(reqwest::header::SET_COOKIE)
        .and_then(|v| v.to_str().ok())
        .and_then(|v| v.split(';').next())
        .map(str::to_string)?;

    client
        .post(url)
        .header("Content-Type", "application/json; charset=utf-8")
        .header("User-Agent", "Mozilla/5.0")
        .header(
            "Referer",
            "https://e.gtfund.com/Etrade/Jijin/view/id/513100",
        )
        .header(reqwest::header::COOKIE, cookie)
        .body(body)
        .send()
        .await
        .ok()
}

async fn fetch_chinaamc_etf_barrier(client: &Client, code: &str) -> Option<String> {
    let date = shanghai_today().format("%Y-%m-%d").to_string();
    let resp = client
        .post("https://www.chinaamc.com/front/front/out/etf/tradeList")
        .form(&[
            ("fundCode", code),
            ("queryDate", date.as_str()),
            ("instType", ""),
        ])
        .send()
        .await
        .ok()?;
    if !resp.status().is_success() {
        return None;
    }
    let value: serde_json::Value = resp.json().await.ok()?;
    let mut min_unit = None;
    let mut min_value = None;
    let mut daily_limit = None;
    let mut status = None;

    if let Some(items) = value
        .pointer("/data/firstContent")
        .and_then(|v| v.as_array())
    {
        min_value = json_label_field(items, |label| label.contains("资产净值"));
    }
    if let Some(items) = value
        .pointer("/data/secondContent")
        .and_then(|v| v.as_array())
    {
        min_unit = json_label_field(items, |label| {
            label.contains("最小申购")
                && label.contains("单位")
                && label.contains('份')
                && !label.contains("资产净值")
                && !label.contains("现金")
        });
        daily_limit = json_label_field(items, |label| {
            label.contains("当日净申购") || label.contains("当日累计可申购")
        });
        status = json_label_text(items, |label| label.contains("申购赎回的允许情况"));
    }

    format_etf_barrier_detail(min_unit, min_value, daily_limit, status.as_deref())
}

async fn fetch_html_etf_barrier(
    client: &Client,
    url: &str,
    fallback_encoding: Option<&'static str>,
) -> Option<String> {
    let html = fetch_text(client, url, fallback_encoding).await?;
    parse_html_etf_barrier(&html)
}

fn parse_html_etf_barrier(html: &str) -> Option<String> {
    let rows = extract_table_key_values(html);
    let min_value = rows
        .iter()
        .find(|(label, _)| label.contains("最小申购") && label.contains("资产净值"))
        .and_then(|(_, value)| parse_float(value))
        .or_else(|| {
            extract_value_after_label(html, "最小申购、赎回单位资产净值")
                .and_then(|v| parse_float(&v))
        });
    let min_unit = rows
        .iter()
        .find(|(label, _)| {
            label.contains("最小申购")
                && label.contains("单位")
                && !label.contains("资产净值")
                && !label.contains("现金红利")
                && !label.contains("现金")
        })
        .and_then(|(_, value)| parse_float(value))
        .or_else(|| {
            extract_value_after_label(html, "最小申购、赎回单位</th>").and_then(|v| parse_float(&v))
        })
        .or_else(|| {
            extract_value_after_label(html, "最小申购赎回单位(单位").and_then(|v| parse_float(&v))
        });
    let daily_limit = rows
        .iter()
        .find(|(label, value)| {
            let is_creation_limit = label.contains("当天净申购")
                || label.contains("当日净申购")
                || label.contains("当日累计申购")
                || label.contains("当日累计可申购");
            is_creation_limit && parse_float(value).is_some()
        })
        .and_then(|(_, value)| parse_float(value))
        .or_else(|| {
            extract_value_after_label(html, "当天净申购的基金份额上限")
                .and_then(|v| parse_float(&v))
        })
        .or_else(|| {
            extract_value_after_label(html, "当日累计申购份额上限").and_then(|v| parse_float(&v))
        });
    let status = rows
        .iter()
        .find(|(label, _)| label.contains("申购赎回的允许情况") || label == "是否允许申购")
        .map(|(_, value)| {
            if value == "否" {
                "不允许申购".to_string()
            } else if value == "是" {
                "允许申购".to_string()
            } else {
                value.clone()
            }
        });

    format_etf_barrier_detail(min_unit, min_value, daily_limit, status.as_deref())
}

fn extract_value_after_label(html: &str, label: &str) -> Option<String> {
    let pos = html.find(label)?;
    let after = &html[pos + label.len()..];
    let td_pos = after.find("<td")?;
    let td_start = pos + label.len() + td_pos + after[td_pos..].find('>')? + 1;
    let td_end = html[td_start..].find("</td>")? + td_start;
    let value = normalize_cell_text(&strip_html_tags(&html[td_start..td_end]));
    if value.is_empty() {
        None
    } else {
        Some(value)
    }
}

fn strip_html_tags(input: &str) -> String {
    let mut out = String::with_capacity(input.len());
    let mut in_tag = false;
    for ch in input.chars() {
        match ch {
            '<' => in_tag = true,
            '>' => in_tag = false,
            _ if !in_tag => out.push(ch),
            _ => {}
        }
    }
    out.replace("&nbsp;", " ")
}

async fn fetch_text(
    client: &Client,
    url: &str,
    fallback_encoding: Option<&'static str>,
) -> Option<String> {
    let resp = client
        .get(url)
        .header("User-Agent", "Mozilla/5.0")
        .send()
        .await
        .ok()?;
    if !resp.status().is_success() {
        return None;
    }
    let content_type = resp
        .headers()
        .get(reqwest::header::CONTENT_TYPE)
        .and_then(|v| v.to_str().ok())
        .map(|v| v.to_string());
    let bytes = resp.bytes().await.ok()?;
    let encoding_label = content_type
        .as_deref()
        .and_then(charset_from_content_type)
        .or(fallback_encoding);

    if let Some(label) = encoding_label {
        if let Some(encoding) = Encoding::for_label(label.as_bytes()) {
            let (text, _, _) = encoding.decode(bytes.as_ref());
            return Some(text.into_owned());
        }
    }

    Some(String::from_utf8_lossy(bytes.as_ref()).into_owned())
}

fn charset_from_content_type(content_type: &str) -> Option<&str> {
    content_type
        .split(';')
        .map(str::trim)
        .find_map(|part| part.strip_prefix("charset=").map(str::trim))
}

fn extract_table_key_values(html: &str) -> Vec<(String, String)> {
    let doc = ScraperHtml::parse_document(html);
    let tr_sel = match Selector::parse("tr") {
        Ok(sel) => sel,
        Err(_) => return Vec::new(),
    };
    let cell_sel = match Selector::parse("th, td") {
        Ok(sel) => sel,
        Err(_) => return Vec::new(),
    };

    doc.select(&tr_sel)
        .filter_map(|tr| {
            let cells: Vec<String> = tr
                .select(&cell_sel)
                .map(|c| normalize_cell_text(&c.text().collect::<Vec<_>>().join("")))
                .filter(|s| !s.is_empty())
                .collect();
            if cells.len() >= 2 {
                Some((cells[0].clone(), cells[1].clone()))
            } else {
                None
            }
        })
        .collect()
}

fn normalize_cell_text(input: &str) -> String {
    input
        .replace('\u{a0}', " ")
        .split_whitespace()
        .collect::<Vec<_>>()
        .join("")
}

fn json_label_field<F>(items: &[serde_json::Value], pred: F) -> Option<f64>
where
    F: Fn(&str) -> bool,
{
    items.iter().find_map(|item| {
        let label = item.get("label")?.as_str()?;
        let value = item.get("value")?.as_str()?;
        if pred(label) {
            parse_float(value)
        } else {
            None
        }
    })
}

fn json_label_text<F>(items: &[serde_json::Value], pred: F) -> Option<String>
where
    F: Fn(&str) -> bool,
{
    items.iter().find_map(|item| {
        let label = item.get("label")?.as_str()?;
        let value = item.get("value")?.as_str()?.trim();
        if pred(label) && !value.is_empty() {
            Some(value.to_string())
        } else {
            None
        }
    })
}

fn json_array_field(items: &[serde_json::Value], field: &str) -> Option<f64> {
    items.iter().find_map(|item| {
        let arr = item.as_array()?;
        if arr.get(2)?.as_str()? == field {
            parse_float(arr.get(1)?.as_str()?)
        } else {
            None
        }
    })
}

fn json_array_text(items: &[serde_json::Value], field: &str) -> Option<String> {
    items.iter().find_map(|item| {
        let arr = item.as_array()?;
        if arr.get(2)?.as_str()? == field {
            let value = arr.get(1)?.as_str()?.trim();
            if value.is_empty() || value == "-" {
                None
            } else {
                Some(value.to_string())
            }
        } else {
            None
        }
    })
}

fn extract_div_id_value(html: &str, id: &str) -> Option<String> {
    let single = format!("id='{id}'");
    let double = format!("id=\"{id}\"");
    let marker_pos = html.find(&single).or_else(|| html.find(&double))?;
    let start = html[marker_pos..].find('>')? + marker_pos + 1;
    let end = html[start..].find('<')? + start;
    let value = html[start..end].trim();
    if value.is_empty() {
        None
    } else {
        Some(value.to_string())
    }
}

fn format_etf_barrier_detail(
    min_unit: Option<f64>,
    min_value: Option<f64>,
    daily_limit: Option<f64>,
    status: Option<&str>,
) -> Option<String> {
    let mut parts = Vec::new();
    match (min_unit, min_value) {
        (Some(unit), Some(value)) => parts.push(format!(
            "最小申赎单位{}/约{}",
            format_share_count(unit),
            format_money_wan(value)
        )),
        (Some(unit), None) => parts.push(format!("最小申赎单位{}", format_share_count(unit))),
        (None, Some(value)) => parts.push(format!("最小申赎单位约{}", format_money_wan(value))),
        (None, None) => return None,
    }
    if let Some(limit) = daily_limit {
        parts.push(format!("当日申购上限{}", format_share_count(limit)));
    }
    if let Some(status) = status.and_then(normalize_status_text) {
        parts.push(format!("状态{}", status));
    }
    Some(parts.join("，"))
}

fn normalize_status_text(status: &str) -> Option<&str> {
    let value = status.trim();
    if value.is_empty() || value == "-" || value == "不限" || value == "不设上限" {
        None
    } else {
        Some(value)
    }
}

fn format_creation_redemption_status(
    creation: Option<&str>,
    redemption: Option<&str>,
) -> Option<String> {
    match (creation.map(str::trim), redemption.map(str::trim)) {
        (Some("是"), Some("是")) => Some("申购赎回皆允许".to_string()),
        (Some("是"), Some("否")) => Some("仅允许申购".to_string()),
        (Some("否"), Some("是")) => Some("仅允许赎回".to_string()),
        (Some("否"), Some("否")) => Some("暂停申赎".to_string()),
        _ => None,
    }
}

fn format_share_count(v: f64) -> String {
    if v >= 10_000.0 {
        let wan = v / 10_000.0;
        if (wan.fract()).abs() < 0.05 {
            format!("{:.0}万份", wan)
        } else {
            format!("{:.1}万份", wan)
        }
    } else {
        format!("{:.0}份", v)
    }
}

fn format_money_wan(v: f64) -> String {
    if v >= 10_000.0 {
        let wan = v / 10_000.0;
        if wan >= 100.0 {
            format!("{:.1}万元", wan)
        } else {
            format!("{:.0}万元", wan)
        }
    } else {
        format!("{:.0}元", v)
    }
}

fn shanghai_today() -> NaiveDate {
    let sh_tz = FixedOffset::east_opt(8 * 3600).expect("tz");
    Utc::now().with_timezone(&sh_tz).date_naive()
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

    consecutive_days_until(history, code, threshold_percent, days, today)
}

fn consecutive_days_until(
    history: &HistoryMap,
    code: &str,
    threshold_percent: f64,
    days: i64,
    today: NaiveDate,
) -> i64 {
    let mut c = 0;
    let mut checked_trading_days = 0;
    let mut i = 0;
    while checked_trading_days < days && i < days + 14 {
        let d = today - ChronoDuration::days(i);
        i += 1;
        if d.weekday().number_from_monday() > 5 {
            continue;
        }
        checked_trading_days += 1;
        let k = d.to_string();
        if let Some(v) = history.get(code).and_then(|m| m.get(&k)) {
            if *v >= threshold_percent {
                c += 1;
            } else {
                break;
            }
        } else {
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

fn is_etf_creation_unit_code(code: &str) -> bool {
    code.starts_with("159") || code.starts_with("513")
}

fn high_entry_barrier_reason(f: &Fund) -> Option<String> {
    let text = f.limit_text.trim();
    if text.contains("万份") || text.contains("最小") || text.contains("申赎单位") {
        return Some(format!("🧱{}", text));
    }
    if is_etf_creation_unit_code(&f.code) && !f.suspended {
        return Some("🧱ETF一级申赎：PCF门槛暂未抓到".to_string());
    }
    None
}

fn has_enough_turnover(f: &Fund) -> bool {
    f.amount.unwrap_or(0.0) >= AMOUNT_THRESHOLD
}

fn has_enough_limit(f: &Fund) -> bool {
    f.limit.map(|v| v >= LIMIT_THRESHOLD).unwrap_or(true)
}

fn is_low_barrier_candidate(f: &Fund) -> bool {
    has_enough_turnover(f)
        && !f.suspended
        && has_enough_limit(f)
        && high_entry_barrier_reason(f).is_none()
}

fn display_limit_text(f: &Fund) -> String {
    let formatted = format_limit(f.limit, &f.limit_text);
    if formatted == "-" {
        if let Some(reason) = high_entry_barrier_reason(f) {
            return reason.trim_start_matches("🧱").to_string();
        }
    }
    formatted
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
            let days = consecutive_days(history, &f.code, 5.0, CONSECUTIVE_DAYS);
            if p >= PREMIUM_THRESHOLD && is_low_barrier_candidate(f) && days >= CONSECUTIVE_DAYS {
                opportunities.push((f, p - DEFAULT_COST, days));
            }
        }
    }
    opportunities.sort_by(|a, b| {
        b.0.premium
            .partial_cmp(&a.0.premium)
            .unwrap_or(std::cmp::Ordering::Equal)
    });

    let tradable_ranked: Vec<&Fund> = with_premium
        .iter()
        .copied()
        .filter(|f| f.premium.unwrap_or(0.0) >= PREMIUM_THRESHOLD && is_low_barrier_candidate(f))
        .collect();

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

    lines.push("🔥 套利机会（溢价≥5% + 成交额≥50万 + 排除ETF申赎高门槛）".to_string());
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
                display_limit_text(f),
                days
            ));
        }
    }

    lines.push("".to_string());
    lines.push("📊 低门槛溢价TOP10（已排除ETF申赎高门槛）".to_string());
    if tradable_ranked.is_empty() {
        lines.push("   暂无低门槛高溢价候选；前排多为ETF申赎高门槛/暂停/低成交。".to_string());
    }
    for (idx, f) in tradable_ranked.iter().take(10).enumerate() {
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
            "   {}. [{}]{} {}{:.1}% 限额:{} {} {}",
            idx + 1,
            f.code,
            f.name,
            level,
            p,
            display_limit_text(f),
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
        let amount_ok = has_enough_turnover(f);
        let limit_ok = has_enough_limit(f);
        let barrier = high_entry_barrier_reason(f);
        let days = consecutive_days(history, &f.code, 5.0, CONSECUTIVE_DAYS);
        let eligible =
            amount_ok && !f.suspended && limit_ok && barrier.is_none() && days >= CONSECUTIVE_DAYS;
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
            reasons.push(format!("🔒限额{}", display_limit_text(f)));
        }
        if let Some(reason) = barrier {
            reasons.push(reason);
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
            limit_text: display_limit_text(f),
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

    fn sample_fund(code: &str, limit_text: &str, suspended: bool) -> Fund {
        Fund {
            code: code.to_string(),
            name: "测试基金".to_string(),
            premium: Some(0.08),
            rt_nav: Some(1.0),
            rt_premium_pct: Some(8.0),
            latest_nav: Some(1.0),
            latest_premium_pct: Some(8.0),
            price: Some(1.08),
            change_pct: Some(0.0),
            amount: Some(600_000.0),
            limit: None,
            suspended,
            limit_text: limit_text.to_string(),
        }
    }

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

    #[test]
    fn consecutive_days_skips_weekends_without_consuming_window() {
        let mut history = HistoryMap::new();
        history.insert(
            "513300".to_string(),
            HashMap::from([
                ("2026-05-28".to_string(), 5.8),
                ("2026-05-29".to_string(), 8.02),
                ("2026-06-01".to_string(), 9.69),
            ]),
        );
        let monday = NaiveDate::from_ymd_opt(2026, 6, 1).unwrap();

        assert_eq!(
            consecutive_days_until(&history, "513300", 5.0, 3, monday),
            3
        );
    }

    #[test]
    fn etf_creation_unit_codes_are_not_low_barrier_candidates() {
        let f = sample_fund("513300", "-", false);

        assert_eq!(
            high_entry_barrier_reason(&f).as_deref(),
            Some("🧱ETF一级申赎：PCF门槛暂未抓到")
        );
        assert_eq!(display_limit_text(&f), "ETF一级申赎：PCF门槛暂未抓到");
        assert!(!is_low_barrier_candidate(&f));
    }

    #[test]
    fn ordinary_lof_can_stay_in_low_barrier_ranking() {
        let f = sample_fund("161129", "不限", false);

        assert!(high_entry_barrier_reason(&f).is_none());
        assert_eq!(display_limit_text(&f), "不限");
        assert!(is_low_barrier_candidate(&f));
    }

    #[test]
    fn minimum_share_text_marks_high_entry_barrier() {
        let f = sample_fund("161999", "最小申赎单位50万份", false);

        assert_eq!(
            high_entry_barrier_reason(&f).as_deref(),
            Some("🧱最小申赎单位50万份")
        );
        assert!(!is_low_barrier_candidate(&f));
    }

    #[test]
    fn etf_barrier_detail_formats_specific_unit_and_money() {
        assert_eq!(
            format_etf_barrier_detail(
                Some(1_000_000.0),
                Some(2_309_357.23),
                Some(1_000_000.0),
                Some("不允许申购")
            )
            .as_deref(),
            Some("最小申赎单位100万份/约230.9万元，当日申购上限100万份，状态不允许申购")
        );
    }

    #[test]
    fn html_etf_barrier_parser_reads_pcf_table_rows() {
        let html = r#"
            <table>
              <tr><th>最小申购、赎回单位资产净值(单位：元)</th><td>￥2,309,357.23</td></tr>
              <tr><th>最小申购、赎回单位(单位：份)</th><td>1,000,000</td></tr>
              <tr><th>当日累计申购份额上限(单位：份)</th><td>1,000,000.00</td></tr>
              <tr><th>是否允许申购</th><td>否</td></tr>
            </table>
        "#;

        assert_eq!(
            parse_html_etf_barrier(html).as_deref(),
            Some("最小申赎单位100万份/约230.9万元，当日申购上限100万份，状态不允许申购")
        );
    }

    #[test]
    fn div_id_parser_reads_gffunds_pcf_values() {
        let html = "<div id='NAVperCU'>2007892.56</div><div id=\"CreationRedemptionUnit\">1300000.00份</div>";

        assert_eq!(
            extract_div_id_value(html, "CreationRedemptionUnit").as_deref(),
            Some("1300000.00份")
        );
        assert_eq!(
            extract_div_id_value(html, "NAVperCU").as_deref(),
            Some("2007892.56")
        );
    }
}
