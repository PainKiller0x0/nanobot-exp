use std::collections::HashMap;

use chrono::{DateTime, Datelike, Duration, NaiveDate, Utc};
use regex::Regex;
use reqwest::Client;
use scraper::{Html as ScraperHtml, Selector};

use crate::markdown::parse_html_preserving_inline_markdown;
use crate::{to_shanghai_time, Entry};
const YAGE_KIT_PROFILE_URL: &str = "https://yage-ai.kit.com/profile";
const YAGE_KIT_DAILY_URL: &str = "kit://yage/daily";
const YAGE_KIT_WEEKLY_URL: &str = "kit://yage/weekly";

pub(crate) fn is_yage_kit_daily(url: &str) -> bool {
    url.trim().eq_ignore_ascii_case(YAGE_KIT_DAILY_URL)
}

pub(crate) fn is_yage_kit_weekly(url: &str) -> bool {
    url.trim().eq_ignore_ascii_case(YAGE_KIT_WEEKLY_URL)
}

fn extract_yage_date_from_url(url: &str) -> Option<NaiveDate> {
    let marker = "/posts/ai-";
    let idx = url.find(marker)?;
    let start = idx + marker.len();
    if url.len() < start + 10 {
        return None;
    }
    let date_str = &url[start..start + 10];
    NaiveDate::parse_from_str(date_str, "%Y-%m-%d").ok()
}

fn rfc3339_from_date(date: NaiveDate) -> Option<String> {
    let dt = date.and_hms_opt(0, 0, 0)?;
    Some(DateTime::<Utc>::from_naive_utc_and_offset(dt, Utc).to_rfc3339())
}

fn yage_title_from_url(url: &str) -> String {
    if let Some(d) = extract_yage_date_from_url(url) {
        return format!("鸭哥 AI 要闻 {}", d.format("%Y-%m-%d"));
    }
    "鸭哥 AI 要闻".to_string()
}

fn yage_decode_content_field(article_html: &str) -> Option<String> {
    let re = Regex::new(r#""content":"(.*?)","recentPosts""#).ok()?;
    let cap = re.captures(article_html)?;
    let escaped = cap.get(1)?.as_str();
    let wrapped = format!("\"{escaped}\"");
    if let Ok(decoded) = serde_json::from_str::<String>(&wrapped) {
        return Some(decoded);
    }
    Some(
        escaped
            .replace("\\n", "\n")
            .replace("\\\"", "\"")
            .replace("\\/", "/")
            .replace("\\u003c", "<")
            .replace("\\u003e", ">")
            .replace("\\u0026", "&"),
    )
}

pub(crate) fn yage_prepare_content_html(raw: &str) -> String {
    let mut html = raw.trim().to_string();
    if let Some(idx) = html.to_ascii_lowercase().find("</style>") {
        // Kit sometimes wraps the actual post in a full HTML document inside a
        // layout table.  html2md treats that outer table and CSS as content, so
        // start from the real body after the embedded stylesheet.
        html = html[idx + "</style>".len()..].to_string();
    }
    for pattern in [
        r"(?is)<script\b[^>]*>.*?</script>",
        r"(?is)<style\b[^>]*>.*?</style>",
        r"(?is)<title\b[^>]*>.*?</title>",
        r"(?is)<meta\b[^>]*>",
    ] {
        if let Ok(re) = Regex::new(pattern) {
            html = re.replace_all(&html, "").to_string();
        }
    }
    html.trim().to_string()
}

fn yage_extract_title_line(markdown: &str) -> String {
    for raw in markdown.lines() {
        let mut s = raw.trim();
        if s.is_empty() {
            continue;
        }
        if s.starts_with('>') {
            continue;
        }
        if s.starts_with("**") && s.ends_with("**") && s.len() > 4 {
            s = s.trim_matches('*').trim();
        }
        if s.starts_with('#') {
            s = s.trim_start_matches('#').trim();
        }
        if !s.is_empty() {
            return s.to_string();
        }
    }
    String::new()
}

async fn fetch_yage_article_markdown(
    client: &Client,
    url: &str,
) -> Option<(String, String, String)> {
    let article_html = client
        .get(url)
        .send()
        .await
        .ok()?
        .error_for_status()
        .ok()?
        .text()
        .await
        .ok()?;
    let raw = yage_decode_content_field(&article_html)?;
    let cleaned = yage_prepare_content_html(&raw);
    let markdown = parse_html_preserving_inline_markdown(&cleaned)
        .trim()
        .to_string();
    if markdown.is_empty() {
        return None;
    }
    let title = {
        let t = yage_extract_title_line(&markdown);
        if t.is_empty() {
            yage_title_from_url(url)
        } else {
            t
        }
    };
    let summary = markdown.chars().take(500).collect::<String>();
    Some((title, markdown, summary))
}

async fn fetch_yage_kit_post_urls(client: &Client, limit: usize) -> Result<Vec<String>, String> {
    let html = client
        .get(YAGE_KIT_PROFILE_URL)
        .send()
        .await
        .map_err(|e| e.to_string())?
        .error_for_status()
        .map_err(|e| e.to_string())?
        .text()
        .await
        .map_err(|e| e.to_string())?;

    let doc = ScraperHtml::parse_document(&html);
    let sel = Selector::parse("a[href]").map_err(|e| e.to_string())?;
    let mut out: Vec<String> = Vec::new();
    for a in doc.select(&sel) {
        let Some(href) = a.value().attr("href") else {
            continue;
        };
        let full = if href.starts_with("https://yage-ai.kit.com/posts/") {
            href.to_string()
        } else if href.starts_with("/posts/") {
            format!("https://yage-ai.kit.com{href}")
        } else {
            continue;
        };
        if out.contains(&full) {
            continue;
        }
        out.push(full);
        if out.len() >= limit {
            break;
        }
    }
    Ok(out)
}

pub(crate) async fn build_yage_daily_entries(
    days: i64,
    client: &Client,
) -> Result<Vec<Entry>, String> {
    let cutoff_date = (Utc::now() - Duration::days(days.max(1))).date_naive();
    let mut items: Vec<Entry> = Vec::new();
    for url in fetch_yage_kit_post_urls(client, 120).await? {
        let Some(d) = extract_yage_date_from_url(&url) else {
            continue;
        };
        if d < cutoff_date {
            continue;
        }
        let published_at = rfc3339_from_date(d);
        let (title, content_markdown, summary) =
            match fetch_yage_article_markdown(client, &url).await {
                Some(v) => v,
                None => (
                    yage_title_from_url(&url),
                    format!("[文章原文]({url})"),
                    format!("鸭哥 AI 每日记录 {}", d.format("%Y-%m-%d")),
                ),
            };
        items.push(Entry {
            id: 0,
            subscription_id: 0,
            guid: format!("yage-kit-daily:{}", d.format("%Y-%m-%d")),
            title,
            link: url.clone(),
            summary,
            content_markdown,
            published_at_local: to_shanghai_time(published_at.as_deref()),
            published_at,
            inserted_at: None,
            last_seen_at: None,
            sample_hits: 1,
            subscription_name: None,
        });
    }
    items.sort_by(|a, b| b.published_at.cmp(&a.published_at));
    Ok(items)
}

pub(crate) async fn build_yage_weekly_entries(
    days: i64,
    client: &Client,
) -> Result<Vec<Entry>, String> {
    let cutoff_date = (Utc::now() - Duration::days(days.max(1))).date_naive();
    let mut by_week: HashMap<(i32, u32), Vec<(NaiveDate, String)>> = HashMap::new();
    for url in fetch_yage_kit_post_urls(client, 240).await? {
        let Some(d) = extract_yage_date_from_url(&url) else {
            continue;
        };
        if d < cutoff_date {
            continue;
        }
        let iso = d.iso_week();
        by_week
            .entry((iso.year(), iso.week()))
            .or_default()
            .push((d, url));
    }

    let mut out: Vec<Entry> = Vec::new();
    for ((year, week), mut posts) in by_week {
        posts.sort_by(|a, b| b.0.cmp(&a.0));
        let Some((latest_day, latest_url)) = posts.first().cloned() else {
            continue;
        };
        let mut md = String::new();
        for (d, u) in &posts {
            md.push_str(&format!("- {} [文章原文]({})\n", d.format("%Y-%m-%d"), u));
        }
        let published_at = rfc3339_from_date(latest_day);
        out.push(Entry {
            id: 0,
            subscription_id: 0,
            guid: format!("yage-kit-weekly:{year}-W{week:02}"),
            title: format!("鸭哥 AI 周记录 {}-W{:02}", year, week),
            link: latest_url,
            summary: format!("本周共 {} 条每日记录", posts.len()),
            content_markdown: md.trim().to_string(),
            published_at_local: to_shanghai_time(published_at.as_deref()),
            published_at,
            inserted_at: None,
            last_seen_at: None,
            sample_hits: 1,
            subscription_name: None,
        });
    }
    out.sort_by(|a, b| b.published_at.cmp(&a.published_at));
    Ok(out)
}
