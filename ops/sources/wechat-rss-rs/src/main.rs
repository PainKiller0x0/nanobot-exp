use axum::{
    extract::{Path, Query, State},
    http::{header, StatusCode},
    response::IntoResponse,
    routing::{get, post},
    Json, Router,
};
use chrono::{DateTime, Duration, FixedOffset, Utc};
use reqwest::Client;
use rss::Channel;
use rusqlite::{params, Connection};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::{
    collections::HashMap,
    net::SocketAddr,
    path::PathBuf,
    sync::{Arc, Mutex},
};

mod db;
mod markdown;
mod pages;
mod paid_cleaner;
mod qq_article_format;
mod qq_extractive_qa;
mod qq_rss_api;
mod settings;
mod yage;

use markdown::parse_html_preserving_inline_markdown;
use pages::{cleaner_page, root};
use paid_cleaner::{
    assemble_paid_article_markdown, build_paid_article_cleaner_response,
    clean_paid_article_payload, markdown_integrity_ok, prepare_paid_article_body,
    set_cleaner_llm_result, CleanMarkdownPayload,
};
use settings::{
    load_auto_refresh_config, load_llm_settings_compat, read_settings, write_settings,
    AutoRefreshConfig, AutoRefreshRuntime, LlmSettings, FREE_LLM_ERROR,
};
use yage::{
    build_yage_daily_entries, build_yage_weekly_entries, is_yage_kit_daily, is_yage_kit_weekly,
};

#[derive(Clone)]
struct AppState {
    db_path: PathBuf,
    settings_path: PathBuf,
    db_lock: Arc<Mutex<()>>,
    http: Client,
    auto_runtime: Arc<Mutex<AutoRefreshRuntime>>,
}

#[derive(Debug, Deserialize)]
struct ListQuery {
    subscription_id: Option<i64>,
    days: Option<i64>,
    limit: Option<i64>,
    hours: Option<i64>,
}

#[derive(Debug, Deserialize, Default)]
struct RefreshPayload {
    sample_fetches: Option<i64>,
    sample_interval: Option<f64>,
    days: Option<i64>,
}

#[derive(Debug, Serialize)]
struct Subscription {
    id: i64,
    biz: String,
    name: String,
    feed_url: String,
    enabled: i64,
    created_at: Option<String>,
    updated_at: Option<String>,
    last_refresh_at: Option<String>,
    last_status: Option<String>,
    last_error: Option<String>,
}

#[derive(Debug, Serialize)]
pub(crate) struct Entry {
    pub(crate) id: i64,
    pub(crate) subscription_id: i64,
    pub(crate) guid: String,
    pub(crate) title: String,
    pub(crate) link: String,
    pub(crate) summary: String,
    pub(crate) content_markdown: String,
    pub(crate) published_at: Option<String>,
    pub(crate) published_at_local: Option<String>,
    pub(crate) inserted_at: Option<String>,
    pub(crate) last_seen_at: Option<String>,
    pub(crate) sample_hits: i64,
    pub(crate) subscription_name: Option<String>,
}

fn map_entry_row(r: &rusqlite::Row<'_>) -> rusqlite::Result<Entry> {
    let published_at: Option<String> = r.get(7)?;
    Ok(Entry {
        id: r.get(0)?,
        subscription_id: r.get(1)?,
        guid: r.get(2)?,
        title: r.get(3)?,
        link: r.get(4)?,
        summary: r.get(5)?,
        content_markdown: r.get(6)?,
        published_at_local: to_shanghai_time(published_at.as_deref()),
        published_at,
        inserted_at: r.get(8)?,
        last_seen_at: r.get(9)?,
        sample_hits: r.get(10)?,
        subscription_name: r.get(11)?,
    })
}

#[derive(Debug, Serialize)]
struct FetchRun {
    id: i64,
    subscription_id: i64,
    started_at: String,
    finished_at: Option<String>,
    status: String,
    sample_fetches: i64,
    items_seen: i64,
    items_saved: i64,
    note: Option<String>,
}

fn now_iso() -> String {
    Utc::now().to_rfc3339()
}

fn conn(path: &PathBuf) -> Result<Connection, String> {
    Connection::open(path).map_err(|e| e.to_string())
}

fn ad_score(title: &str, summary: &str, content: &str) -> i32 {
    let title_l = title.to_lowercase();
    let summary_l = summary.to_lowercase();
    let body_l = content
        .chars()
        .take(12_000)
        .collect::<String>()
        .to_lowercase();
    let front = format!("{}\n{}", title_l, summary_l);
    let all = format!("{}\n{}", front, body_l);

    let hard_title = ["八段锦的猛料", "刺痛了多少中国女人"];
    let hard = [
        "-广告-",
        "限时0元",
        "立即领取",
        "报名通道",
        "仅需0元",
        "免费社群陪伴",
    ];
    let soft = [
        "广告",
        "赞助",
        "推广",
        "课程",
        "训练营",
        "0元",
        "报名",
        "扫码",
        "加微信",
        "下单",
        "限时",
        "福利",
        "购课",
        "客服",
        "先到先得",
        "体验营",
    ];
    let course_title = ["一堂课告诉你", "课告诉你"];
    let commercial_context = [
        "点击图片报名",
        "点击报名",
        "优惠名额",
        "前100名",
        "仅需",
        "9.9",
        "课程官网价",
        "为期6天",
        "直播课",
        "选修课",
        "奖励课",
        "具体收费",
        "课程由",
        "授课",
        "课程信息",
        "领取",
        "社群",
        "训练营",
        "体验营",
        "客服",
        "扫码",
        "加微信",
    ];

    let mut s = 0_i32;
    for k in hard_title {
        if title.contains(k) {
            s += 10;
        }
    }
    for k in hard {
        if front.contains(k) {
            s += 3;
        } else if all.contains(k) {
            s += 2;
        }
    }
    for k in soft {
        if front.contains(k) {
            s += 1;
        }
    }

    let has_course_title = course_title.iter().any(|k| title_l.contains(*k));
    let context_hits = commercial_context
        .iter()
        .filter(|k| all.contains(**k))
        .count() as i32;
    if has_course_title && context_hits >= 2 {
        s += 3;
    } else if has_course_title && context_hits == 1 {
        s += 1;
    }
    if context_hits >= 4 {
        s += 2;
    } else if context_hits >= 2 {
        s += 1;
    }
    s
}

async fn llm_is_ad(client: &Client, llm: &LlmSettings, title: &str, summary: &str) -> Option<bool> {
    if !llm.enabled() {
        return None;
    }
    let mut url = llm.api_base.trim_end_matches('/').to_string();
    if !url.ends_with("/chat/completions") {
        url.push_str("/chat/completions");
    }
    let body = json!({
        "model": llm.model,
        "messages": [
            {"role":"system","content":"你是内容审核助手。仅回答 AD 或 NORMAL，不要输出其他内容。"},
            {"role":"user","content": format!("判断这篇公众号文章是否属于广告/推广文。\n标题: {}\n摘要: {}\n如果是广告/推广返 AD，否则返 NORMAL。", title, summary)}
        ],
        "max_tokens": 6,
        "temperature": 0
    });
    let resp = client
        .post(url)
        .bearer_auth(llm.api_key.clone())
        .json(&body)
        .timeout(std::time::Duration::from_secs(30))
        .send()
        .await
        .ok()?;
    let ok = resp.error_for_status().ok()?;
    let parsed: Value = ok.json().await.ok()?;
    let content = parsed
        .get("choices")
        .and_then(|v| v.as_array())
        .and_then(|arr| arr.first())
        .and_then(|x| x.get("message"))
        .and_then(|x| x.get("content"))
        .and_then(|x| x.as_str())
        .unwrap_or("")
        .trim()
        .to_uppercase();
    if content.contains("AD") {
        Some(true)
    } else if content.contains("NORMAL") {
        Some(false)
    } else {
        None
    }
}

fn query_param(link: &str, key: &str) -> Option<String> {
    let qpos = link.find('?')?;
    let qs = &link[qpos + 1..];
    for part in qs.split('&') {
        let mut it = part.splitn(2, '=');
        let k = it.next().unwrap_or("").trim();
        let v = it.next().unwrap_or("").trim();
        if k == key && !v.is_empty() {
            return Some(v.to_string());
        }
    }
    None
}

fn parse_guid(link: &str, fallback: &str) -> String {
    let mid = query_param(link, "mid");
    let idx = query_param(link, "idx").or_else(|| query_param(link, "itemidx"));
    match (mid, idx) {
        (Some(m), Some(i)) => return format!("{m}:{i}"),
        (Some(m), None) => return m,
        _ => {}
    }
    if !fallback.trim().is_empty() {
        fallback.trim().to_string()
    } else {
        link.to_string()
    }
}

fn parse_pub_date(s: Option<&str>) -> Option<String> {
    let v = s?.trim();
    if v.is_empty() {
        return None;
    }
    if let Ok(dt) = DateTime::parse_from_rfc2822(v) {
        return Some(dt.with_timezone(&Utc).to_rfc3339());
    }
    if let Ok(dt) = DateTime::parse_from_rfc3339(v) {
        return Some(dt.with_timezone(&Utc).to_rfc3339());
    }
    None
}

pub(crate) fn to_shanghai_time(v: Option<&str>) -> Option<String> {
    let raw = v?.trim();
    if raw.is_empty() {
        return None;
    }
    let dt_utc = if let Ok(dt) = DateTime::parse_from_rfc3339(raw) {
        dt.with_timezone(&Utc)
    } else if let Ok(dt) = DateTime::parse_from_rfc2822(raw) {
        dt.with_timezone(&Utc)
    } else {
        return None;
    };
    let tz = FixedOffset::east_opt(8 * 3600)?;
    Some(
        dt_utc
            .with_timezone(&tz)
            .format("%Y-%m-%d %H:%M:%S")
            .to_string(),
    )
}

async fn fetch_feed_text(client: &Client, url: &str) -> Result<String, String> {
    let mut last_err = String::new();
    for attempt in 1..=3 {
        match client.get(url).send().await {
            Ok(resp) => match resp.error_for_status() {
                Ok(ok) => match ok.text().await {
                    Ok(text) => return Ok(text),
                    Err(e) => last_err = e.to_string(),
                },
                Err(e) => last_err = e.to_string(),
            },
            Err(e) => last_err = e.to_string(),
        }
        let ms = 500_u64 * attempt;
        tokio::time::sleep(std::time::Duration::from_millis(ms)).await;
    }
    Err(last_err)
}

async fn fetch_article_markdown_from_link(client: &Client, url: &str) -> Option<String> {
    let link = url.trim();
    if link.is_empty() {
        return None;
    }
    let resp = client
        .get(link)
        .send()
        .await
        .ok()?
        .error_for_status()
        .ok()?;
    let html = resp.text().await.ok()?;
    let md = parse_html_preserving_inline_markdown(&html)
        .trim()
        .to_string();
    if md.is_empty() {
        None
    } else {
        Some(md)
    }
}

fn normalize_feed_url(url: &str) -> String {
    if url.starts_with("http://rss.jintiankansha.me/") {
        url.replacen("http://", "https://", 1)
    } else {
        url.to_string()
    }
}

async fn refresh_one(
    st: Arc<AppState>,
    sid: i64,
    days: i64,
    sample_fetches: i64,
) -> Result<Value, String> {
    let days = days.max(1);
    let mut sample_fetches = sample_fetches.max(1);
    let cutoff = (Utc::now() - Duration::days(days)).to_rfc3339();

    let subscription = {
        let _g = st
            .db_lock
            .lock()
            .map_err(|_| "db lock failed".to_string())?;
        let c = conn(&st.db_path)?;
        let mut stmt = c
            .prepare("SELECT id,biz,name,feed_url,enabled FROM subscriptions WHERE id=?1")
            .map_err(|e| e.to_string())?;
        stmt.query_row(params![sid], |r| {
            Ok((
                r.get::<_, i64>(0)?,
                r.get::<_, String>(1)?,
                r.get::<_, String>(2)?,
                r.get::<_, String>(3)?,
                r.get::<_, i64>(4)?,
            ))
        })
        .map_err(|e| e.to_string())?
    };

    let (_, _biz, name, feed_url, _enabled) = subscription;
    if feed_url.contains("rss.jintiankansha.me") {
        // Upstream occasionally serves stale windows; increase sampling to improve freshness.
        sample_fetches = sample_fetches.max(8);
    }
    let started_at = now_iso();
    let run_id = {
        let _g = st
            .db_lock
            .lock()
            .map_err(|_| "db lock failed".to_string())?;
        let c = conn(&st.db_path)?;
        c.execute(
            "INSERT INTO fetch_runs (subscription_id,started_at,status,sample_fetches,items_seen,items_saved) VALUES (?1,?2,'running',?3,0,0)",
            params![sid, started_at, sample_fetches],
        )
        .map_err(|e| e.to_string())?;
        c.last_insert_rowid()
    };

    let llm = load_llm_settings_compat(&st.settings_path);
    let mut seen = 0_i64;
    let mut saved = 0_i64;
    let mut ad_skipped = 0_i64;
    let mut per_guid: HashMap<String, Entry> = HashMap::new();

    let effective_feed_url = normalize_feed_url(&feed_url);
    let is_yage_daily = is_yage_kit_daily(&effective_feed_url);
    let is_yage_weekly = is_yage_kit_weekly(&effective_feed_url);
    let is_yage_mode = is_yage_daily || is_yage_weekly;

    if is_yage_mode {
        let entries = if is_yage_daily {
            build_yage_daily_entries(days, &st.http).await?
        } else {
            build_yage_weekly_entries(days, &st.http).await?
        };
        seen = entries.len() as i64;
        for mut e in entries {
            let guid = e.guid.clone();
            e.subscription_id = sid;
            match per_guid.get_mut(&guid) {
                Some(existing) => {
                    existing.sample_hits += 1;
                    if e.content_markdown.len() > existing.content_markdown.len() {
                        *existing = Entry {
                            sample_hits: existing.sample_hits,
                            ..e
                        };
                    }
                }
                None => {
                    per_guid.insert(guid, e);
                }
            }
        }
    } else {
        for _ in 0..sample_fetches {
            let feed_text = fetch_feed_text(&st.http, &effective_feed_url).await?;
            let channel = Channel::read_from(feed_text.as_bytes()).map_err(|e| e.to_string())?;
            for item in channel.items() {
                let link = item.link().unwrap_or("").to_string();
                if link.is_empty() {
                    continue;
                }
                let guid = parse_guid(&link, item.guid().map(|g| g.value()).unwrap_or(""));
                let title = item.title().unwrap_or("Untitled").to_string();
                let raw_summary = item.description().unwrap_or("").to_string();
                let raw_content = item.content().unwrap_or("").to_string();
                let content_markdown = if raw_content.is_empty() {
                    parse_html_preserving_inline_markdown(&raw_summary)
                } else {
                    parse_html_preserving_inline_markdown(&raw_content)
                };
                let summary = if raw_summary.is_empty() {
                    content_markdown.chars().take(500).collect::<String>()
                } else {
                    raw_summary
                };
                let published = parse_pub_date(item.pub_date());
                if let Some(p) = &published {
                    if p < &cutoff {
                        continue;
                    }
                }
                seen += 1;
                let entry = Entry {
                    id: 0,
                    subscription_id: sid,
                    guid: guid.clone(),
                    title,
                    link,
                    summary,
                    content_markdown,
                    published_at_local: to_shanghai_time(published.as_deref()),
                    published_at: published,
                    inserted_at: None,
                    last_seen_at: None,
                    sample_hits: 1,
                    subscription_name: None,
                };
                match per_guid.get_mut(&guid) {
                    Some(existing) => {
                        existing.sample_hits += 1;
                        if entry.content_markdown.len() > existing.content_markdown.len() {
                            *existing = Entry {
                                sample_hits: existing.sample_hits,
                                ..entry
                            };
                        }
                    }
                    None => {
                        per_guid.insert(guid, entry);
                    }
                }
            }
        }
    }

    let mut candidates: Vec<Entry> = per_guid.into_values().collect();
    candidates.sort_by(|a, b| b.published_at.cmp(&a.published_at));
    let mut filtered: Vec<Entry> = Vec::with_capacity(candidates.len());
    let mut ad_guids: Vec<String> = Vec::new();
    for v in candidates {
        if is_yage_mode {
            filtered.push(v);
            continue;
        }
        let score = ad_score(&v.title, &v.summary, &v.content_markdown);
        let mut is_ad = score >= 3;
        if !is_ad && score > 0 {
            if let Some(decision) = llm_is_ad(&st.http, &llm, &v.title, &v.summary).await {
                is_ad = decision;
            } else {
                is_ad = score >= 2;
            }
        }
        if is_ad {
            ad_skipped += 1;
            ad_guids.push(v.guid.clone());
            continue;
        }
        filtered.push(v);
    }

    {
        let _g = st
            .db_lock
            .lock()
            .map_err(|_| "db lock failed".to_string())?;
        let c = conn(&st.db_path)?;
        let now = now_iso();
        for v in &filtered {
            let rows = c
                .execute(
                    "UPDATE entries SET title=?1,link=?2,summary=?3,content_markdown=?4,published_at=?5,last_seen_at=?6,sample_hits=MAX(sample_hits,?7) WHERE subscription_id=?8 AND guid=?9",
                    params![
                        v.title,
                        v.link,
                        v.summary,
                        v.content_markdown,
                        v.published_at,
                        now,
                        v.sample_hits,
                        sid,
                        v.guid
                    ],
                )
                .map_err(|e| e.to_string())?;
            if rows == 0 {
                c.execute(
                    "INSERT INTO entries (subscription_id,guid,title,link,summary,content_markdown,published_at,inserted_at,last_seen_at,sample_hits) VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10)",
                    params![
                        sid,
                        v.guid,
                        v.title,
                        v.link,
                        v.summary,
                        v.content_markdown,
                        v.published_at,
                        now,
                        now,
                        v.sample_hits
                    ],
                )
                .map_err(|e| e.to_string())?;
                saved += 1;
            }
        }
        c.execute(
            "UPDATE subscriptions SET last_refresh_at=?1,last_status='ok',last_error=NULL,updated_at=?1 WHERE id=?2",
            params![now, sid],
        )
        .map_err(|e| e.to_string())?;
        for g in ad_guids {
            let _ = c.execute(
                "DELETE FROM entries WHERE subscription_id=?1 AND guid=?2",
                params![sid, g],
            );
        }
        // Hard cap per subscription: keep latest 5 rows only.
        let _ = c.execute(
            "DELETE FROM entries
             WHERE id IN (
                SELECT id FROM (
                    SELECT id,
                           ROW_NUMBER() OVER (
                               PARTITION BY subscription_id
                               ORDER BY COALESCE(published_at, inserted_at, last_seen_at) DESC, id DESC
                           ) AS rn
                    FROM entries
                    WHERE subscription_id=?1
                ) t
                WHERE rn > 5
             )",
            params![sid],
        );
        c.execute(
            "UPDATE fetch_runs SET finished_at=?1,status='ok',items_seen=?2,items_saved=?3,note=?4 WHERE id=?5",
            params![
                now,
                seen,
                saved,
                format!("max_age_days={days};ad_skipped={ad_skipped};llm_ad={}", llm.ad_route_note()),
                run_id
            ],
        )
        .map_err(|e| e.to_string())?;
    }

    Ok(json!({
        "subscription": {"id": sid, "name": name},
        "items_seen": seen,
        "items_saved": saved,
        "ad_skipped": ad_skipped
    }))
}

async fn llm_refine_cleaner_markdown(
    client: &Client,
    llm: &LlmSettings,
    markdown: &str,
) -> Result<String, String> {
    if !llm.configured() || !llm.free_allowed() {
        return Err("free LongCat cleaner is not configured".to_string());
    }
    let max_tokens = ((markdown.chars().count() as i64) + 2048).clamp(4096, 60000);
    let body = json!({
        "model": llm.model,
        "messages": [
            {"role":"system","content":"You are a Markdown paragraph formatter for long Chinese essays. You may only change blank lines and paragraph breaks. Preserve every original character, punctuation mark, Markdown link, URL, heading, quote, italic metadata line, and ordering exactly. Do not rewrite, summarize, translate, explain, add, or delete content. Output plain Markdown only, no code fence."},
            {"role":"user","content": format!("Format the following Markdown into natural paragraphs in the writing rhythm of Bishu Xifeng / Jiyi Chengzai. Only adjust blank lines. Keep tightly related explanatory sentences and question pairs in the same paragraph when appropriate. Return the complete Markdown.\n\n{}", markdown)}
        ],
        "temperature": 0,
        "max_tokens": max_tokens,
        "stream": false
    });
    let resp = client
        .post(llm.chat_completions_url())
        .bearer_auth(llm.api_key.clone())
        .json(&body)
        .timeout(std::time::Duration::from_secs(120))
        .send()
        .await
        .map_err(|e| format!("LongCat request failed: {e}"))?;
    let status = resp.status().as_u16();
    let text = resp.text().await.unwrap_or_default();
    if status >= 400 {
        return Err(format!(
            "LongCat HTTP {status}: {}",
            text.chars().take(300).collect::<String>()
        ));
    }
    let parsed: Value =
        serde_json::from_str(&text).map_err(|e| format!("LongCat returned invalid JSON: {e}"))?;
    let content = parsed
        .get("choices")
        .and_then(|v| v.as_array())
        .and_then(|arr| arr.first())
        .and_then(|x| x.get("message"))
        .and_then(|x| x.get("content"))
        .and_then(|x| x.as_str())
        .unwrap_or("")
        .trim()
        .trim_start_matches("```markdown")
        .trim_start_matches("```")
        .trim_end_matches("```")
        .trim()
        .to_string();
    if content.is_empty() {
        return Err("LongCat returned empty content".to_string());
    }
    if !markdown_integrity_ok(markdown, &content) {
        return Err("LongCat changed text content, local result kept".to_string());
    }
    Ok(content)
}

async fn health() -> Json<Value> {
    Json(json!({"ok": true, "time": now_iso()}))
}

async fn auto_refresh_status(State(st): State<Arc<AppState>>) -> Json<Value> {
    let cfg = load_auto_refresh_config(&st.settings_path);
    let runtime = match st.auto_runtime.lock() {
        Ok(g) => g.clone(),
        Err(_) => AutoRefreshRuntime::default(),
    };
    Json(json!({
        "enabled": cfg.enabled,
        "interval_seconds": cfg.interval_seconds,
        "thread_alive": runtime.thread_alive,
        "running": runtime.running,
        "last_run_at": runtime.last_run_at,
        "next_run_at": runtime.next_run_at,
        "last_status": runtime.last_status,
        "last_message": runtime.last_message
    }))
}

async fn list_subscriptions(State(st): State<Arc<AppState>>) -> Json<Value> {
    let _g = match st.db_lock.lock() {
        Ok(g) => g,
        Err(_) => return Json(json!({"error":"db lock failed","items":[] })),
    };
    let c = match conn(&st.db_path) {
        Ok(v) => v,
        Err(e) => return Json(json!({"error":e,"items":[] })),
    };
    let mut items = Vec::<Subscription>::new();
    let sql = "SELECT id,biz,name,feed_url,enabled,created_at,updated_at,last_refresh_at,last_status,last_error FROM subscriptions ORDER BY id ASC";
    if let Ok(mut stmt) = c.prepare(sql) {
        if let Ok(rows) = stmt.query_map([], |r| {
            Ok(Subscription {
                id: r.get(0)?,
                biz: r.get(1)?,
                name: r.get(2)?,
                feed_url: r.get(3)?,
                enabled: r.get(4)?,
                created_at: r.get(5)?,
                updated_at: r.get(6)?,
                last_refresh_at: r.get(7)?,
                last_status: r.get(8)?,
                last_error: r.get(9)?,
            })
        }) {
            for row in rows.flatten() {
                items.push(row);
            }
        }
    }
    Json(json!({"items": items}))
}

async fn list_entries(State(st): State<Arc<AppState>>, Query(q): Query<ListQuery>) -> Json<Value> {
    let days = q.days.unwrap_or(7).max(1);
    let limit = q.limit.unwrap_or(50).max(1);
    let cutoff = (Utc::now() - Duration::days(days)).to_rfc3339();
    let _g = match st.db_lock.lock() {
        Ok(g) => g,
        Err(_) => return Json(json!({"error":"db lock failed","items":[] })),
    };
    let c = match conn(&st.db_path) {
        Ok(v) => v,
        Err(e) => return Json(json!({"error":e,"items":[] })),
    };
    let mut items = Vec::<Entry>::new();
    let with_sid = q.subscription_id.is_some();
    let sql = if with_sid {
        "SELECT e.id,e.subscription_id,e.guid,e.title,e.link,e.summary,e.content_markdown,e.published_at,e.inserted_at,e.last_seen_at,e.sample_hits,s.name FROM entries e JOIN subscriptions s ON s.id=e.subscription_id WHERE (e.published_at IS NULL OR e.published_at >= ?1) AND e.subscription_id=?2 ORDER BY e.published_at DESC, e.inserted_at DESC LIMIT ?3"
    } else {
        "SELECT e.id,e.subscription_id,e.guid,e.title,e.link,e.summary,e.content_markdown,e.published_at,e.inserted_at,e.last_seen_at,e.sample_hits,s.name FROM entries e JOIN subscriptions s ON s.id=e.subscription_id WHERE (e.published_at IS NULL OR e.published_at >= ?1) ORDER BY e.published_at DESC, e.inserted_at DESC LIMIT ?2"
    };
    if let Ok(mut stmt) = c.prepare(sql) {
        let mapper = map_entry_row;
        let rows = if with_sid {
            stmt.query_map(
                params![cutoff, q.subscription_id.unwrap_or_default(), limit],
                mapper,
            )
        } else {
            stmt.query_map(params![cutoff, limit], mapper)
        };
        if let Ok(rows) = rows {
            for row in rows.flatten() {
                if ad_score(&row.title, &row.summary, &row.content_markdown) >= 2 {
                    continue;
                }
                items.push(row);
            }
        }
    }
    Json(json!({"items": items}))
}

async fn list_new_items(
    State(st): State<Arc<AppState>>,
    Query(q): Query<ListQuery>,
) -> Json<Value> {
    let hours = q.hours.unwrap_or(24).max(1);
    let limit = q.limit.unwrap_or(20).max(1);
    let cutoff = (Utc::now() - Duration::hours(hours)).to_rfc3339();
    let _g = match st.db_lock.lock() {
        Ok(g) => g,
        Err(_) => return Json(json!({"error":"db lock failed","items":[] })),
    };
    let c = match conn(&st.db_path) {
        Ok(v) => v,
        Err(e) => return Json(json!({"error":e,"items":[] })),
    };
    let mut items = Vec::<Entry>::new();
    let sql = "SELECT e.id,e.subscription_id,e.guid,e.title,e.link,e.summary,e.content_markdown,e.published_at,e.inserted_at,e.last_seen_at,e.sample_hits,s.name FROM entries e JOIN subscriptions s ON s.id=e.subscription_id WHERE e.inserted_at >= ?1 ORDER BY e.inserted_at DESC LIMIT ?2";
    if let Ok(mut stmt) = c.prepare(sql) {
        if let Ok(rows) = stmt.query_map(params![cutoff, limit], map_entry_row) {
            for row in rows.flatten() {
                if ad_score(&row.title, &row.summary, &row.content_markdown) >= 2 {
                    continue;
                }
                items.push(row);
            }
        }
    }
    Json(json!({"items": items}))
}

async fn list_runs(State(st): State<Arc<AppState>>, Query(q): Query<ListQuery>) -> Json<Value> {
    let limit = q.limit.unwrap_or(20).max(1);
    let _g = match st.db_lock.lock() {
        Ok(g) => g,
        Err(_) => return Json(json!({"error":"db lock failed","items":[] })),
    };
    let c = match conn(&st.db_path) {
        Ok(v) => v,
        Err(e) => return Json(json!({"error":e,"items":[] })),
    };
    let with_sid = q.subscription_id.is_some();
    let sql = if with_sid {
        "SELECT id,subscription_id,started_at,finished_at,status,sample_fetches,items_seen,items_saved,note FROM fetch_runs WHERE subscription_id=?1 ORDER BY id DESC LIMIT ?2"
    } else {
        "SELECT id,subscription_id,started_at,finished_at,status,sample_fetches,items_seen,items_saved,note FROM fetch_runs ORDER BY id DESC LIMIT ?1"
    };
    let mut items = Vec::<FetchRun>::new();
    if let Ok(mut stmt) = c.prepare(sql) {
        let mapper = |r: &rusqlite::Row<'_>| {
            Ok(FetchRun {
                id: r.get(0)?,
                subscription_id: r.get(1)?,
                started_at: r.get(2)?,
                finished_at: r.get(3)?,
                status: r.get(4)?,
                sample_fetches: r.get(5)?,
                items_seen: r.get(6)?,
                items_saved: r.get(7)?,
                note: r.get(8)?,
            })
        };
        let rows = if with_sid {
            stmt.query_map(
                params![q.subscription_id.unwrap_or_default(), limit],
                mapper,
            )
        } else {
            stmt.query_map(params![limit], mapper)
        };
        if let Ok(rows) = rows {
            for row in rows.flatten() {
                items.push(row);
            }
        }
    }
    Json(json!({"items": items}))
}

async fn get_settings_llm(State(st): State<Arc<AppState>>) -> Json<Value> {
    let llm = load_llm_settings_compat(&st.settings_path);
    Json(json!({"item": llm.public_json()}))
}

async fn get_article(State(st): State<Arc<AppState>>, Path(id): Path<i64>) -> Json<Value> {
    let _g = match st.db_lock.lock() {
        Ok(g) => g,
        Err(_) => return Json(json!({"error":"db lock failed"})),
    };
    let c = match conn(&st.db_path) {
        Ok(v) => v,
        Err(e) => return Json(json!({"error":e})),
    };
    let sql = "SELECT e.id,e.subscription_id,e.guid,e.title,e.link,e.summary,e.content_markdown,e.published_at,e.inserted_at,e.last_seen_at,e.sample_hits,s.name FROM entries e JOIN subscriptions s ON s.id=e.subscription_id WHERE e.id=?1";
    let mut stmt = match c.prepare(sql) {
        Ok(v) => v,
        Err(e) => return Json(json!({"error":e.to_string()})),
    };
    let row = stmt.query_row(params![id], map_entry_row);
    match row {
        Ok(v) => Json(
            json!({"item": { "id": v.id, "title": v.title, "link": v.link, "summary": v.summary, "content_markdown": v.content_markdown, "published_at": v.published_at, "published_at_local": v.published_at_local, "inserted_at": v.inserted_at, "subscription_name": v.subscription_name, "article_markdown": if v.content_markdown.is_empty() { v.summary } else { v.content_markdown } }}),
        ),
        Err(_) => Json(json!({"error":"entry not found"})),
    }
}

async fn get_article_markdown(
    State(st): State<Arc<AppState>>,
    Path(id): Path<i64>,
) -> impl IntoResponse {
    let Json(v) = get_article(State(st.clone()), Path(id)).await;
    if let Some(err) = v.get("error") {
        return (StatusCode::NOT_FOUND, err.to_string()).into_response();
    }
    let mut md = v
        .get("item")
        .and_then(|x| x.get("article_markdown"))
        .and_then(|x| x.as_str())
        .unwrap_or("")
        .to_string();
    let link = v
        .get("item")
        .and_then(|x| x.get("link"))
        .and_then(|x| x.as_str())
        .unwrap_or("")
        .to_string();
    let summary = v
        .get("item")
        .and_then(|x| x.get("summary"))
        .and_then(|x| x.as_str())
        .unwrap_or("")
        .to_string();

    if md.trim().len() < 240 {
        if let Some(fetched) = fetch_article_markdown_from_link(&st.http, &link).await {
            if fetched.len() > md.len() {
                md = fetched.clone();
            }
            if let Ok(_g) = st.db_lock.lock() {
                if let Ok(c) = conn(&st.db_path) {
                    let min_len = md.len() as i64;
                    let _ = c.execute(
                        "UPDATE entries SET content_markdown=CASE WHEN length(coalesce(content_markdown,''))>=?1 THEN content_markdown ELSE ?2 END WHERE id=?3",
                        params![min_len, md.clone(), id],
                    );
                }
            }
        } else if md.trim().is_empty() {
            md = summary;
        }
    }
    if md.trim().is_empty() {
        md = "(暂无可预览正文)".to_string();
    }
    ([(header::CONTENT_TYPE, "text/plain; charset=utf-8")], md).into_response()
}

async fn clean_markdown(Json(payload): Json<CleanMarkdownPayload>) -> Json<Value> {
    if payload.content.as_deref().unwrap_or("").trim().is_empty() {
        return Json(json!({"ok": false, "error": "content is empty"}));
    }
    Json(clean_paid_article_payload(&payload))
}

async fn refine_clean_markdown(
    State(st): State<Arc<AppState>>,
    Json(payload): Json<CleanMarkdownPayload>,
) -> Json<Value> {
    if payload.content.as_deref().unwrap_or("").trim().is_empty() {
        return Json(json!({"ok": false, "error": "content is empty"}));
    }
    let prepared = prepare_paid_article_body(&payload, false);
    if prepared.body.trim().is_empty() {
        return Json(json!({"ok": false, "error": "content is empty after cleanup"}));
    }
    let llm = load_llm_settings_compat(&st.settings_path);
    match llm_refine_cleaner_markdown(&st.http, &llm, &prepared.body).await {
        Ok(refined_body) => {
            let refined = assemble_paid_article_markdown(&payload, &refined_body);
            let mut result = build_paid_article_cleaner_response(
                &payload,
                &prepared,
                refined,
                "llm_refine",
                "not_used",
            );
            set_cleaner_llm_result(&mut result, "ok", None);
            Json(result)
        }
        Err(e) => Json(json!({"ok": false, "error": e, "llm_cleaner_status": "failed"})),
    }
}

async fn create_subscription(
    State(st): State<Arc<AppState>>,
    Json(payload): Json<Value>,
) -> Json<Value> {
    let mut biz = payload
        .get("biz")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_string();
    let name = payload
        .get("name")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_string();
    let feed_url = payload
        .get("feed_url")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_string();
    if feed_url.is_empty() {
        return Json(json!({"error":"feed_url required"}));
    }
    if biz.is_empty() {
        if let Some(v) = query_param(&feed_url, "__biz") {
            biz = v;
        }
    }
    if biz.is_empty() {
        let host = feed_url
            .split('/')
            .nth(2)
            .unwrap_or("unknown")
            .to_lowercase();
        let tail = feed_url
            .rsplit('/')
            .next()
            .unwrap_or("unknown")
            .chars()
            .take(24)
            .collect::<String>();
        biz = format!("custom:{host}:{tail}");
    }
    let now = now_iso();
    let _g = match st.db_lock.lock() {
        Ok(g) => g,
        Err(_) => return Json(json!({"error":"db lock failed"})),
    };
    let c = match conn(&st.db_path) {
        Ok(v) => v,
        Err(e) => return Json(json!({"error":e})),
    };
    let _ = c.execute(
        "INSERT INTO subscriptions (biz,name,feed_url,enabled,created_at,updated_at) VALUES (?1,?2,?3,1,?4,?4)
         ON CONFLICT(biz) DO UPDATE SET name=excluded.name, feed_url=excluded.feed_url, updated_at=excluded.updated_at",
        params![biz, if name.is_empty() { "Unnamed".to_string() } else { name }, feed_url, now],
    );
    Json(json!({"message":"Saved"}))
}

async fn toggle_subscription(State(st): State<Arc<AppState>>, Path(id): Path<i64>) -> Json<Value> {
    let _g = match st.db_lock.lock() {
        Ok(g) => g,
        Err(_) => return Json(json!({"error":"db lock failed"})),
    };
    let c = match conn(&st.db_path) {
        Ok(v) => v,
        Err(e) => return Json(json!({"error":e})),
    };
    let enabled: i64 = c
        .query_row(
            "SELECT enabled FROM subscriptions WHERE id=?1",
            params![id],
            |r| r.get(0),
        )
        .unwrap_or(1);
    let new_v = if enabled == 0 { 1 } else { 0 };
    let _ = c.execute(
        "UPDATE subscriptions SET enabled=?1,updated_at=?2 WHERE id=?3",
        params![new_v, now_iso(), id],
    );
    Json(json!({"message":"OK","item":{"id":id,"enabled":new_v}}))
}

async fn update_subscription(
    State(st): State<Arc<AppState>>,
    Path(id): Path<i64>,
    Json(payload): Json<Value>,
) -> Json<Value> {
    let name = payload
        .get("name")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_string();
    let feed_url = payload
        .get("feed_url")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_string();
    let _g = match st.db_lock.lock() {
        Ok(g) => g,
        Err(_) => return Json(json!({"error":"db lock failed"})),
    };
    let c = match conn(&st.db_path) {
        Ok(v) => v,
        Err(e) => return Json(json!({"error":e})),
    };
    let _ = c.execute(
        "UPDATE subscriptions SET name=COALESCE(NULLIF(?1,''),name),feed_url=COALESCE(NULLIF(?2,''),feed_url),updated_at=?3 WHERE id=?4",
        params![name, feed_url, now_iso(), id],
    );
    Json(json!({"message":"Updated"}))
}

async fn delete_subscription(State(st): State<Arc<AppState>>, Path(id): Path<i64>) -> Json<Value> {
    let _g = match st.db_lock.lock() {
        Ok(g) => g,
        Err(_) => return Json(json!({"error":"db lock failed"})),
    };
    let c = match conn(&st.db_path) {
        Ok(v) => v,
        Err(e) => return Json(json!({"error":e})),
    };
    let _ = c.execute("DELETE FROM entries WHERE subscription_id=?1", params![id]);
    let _ = c.execute(
        "DELETE FROM fetch_runs WHERE subscription_id=?1",
        params![id],
    );
    let _ = c.execute("DELETE FROM subscriptions WHERE id=?1", params![id]);
    Json(json!({"message":"Deleted"}))
}

async fn set_auto_refresh(
    State(st): State<Arc<AppState>>,
    Json(payload): Json<Value>,
) -> Json<Value> {
    let enabled = payload
        .get("enabled")
        .and_then(|v| v.as_bool())
        .unwrap_or(true);
    let seconds = payload
        .get("seconds")
        .and_then(|v| v.as_i64())
        .or_else(|| payload.get("interval_seconds").and_then(|v| v.as_i64()))
        .or_else(|| {
            payload
                .get("minutes")
                .and_then(|v| v.as_i64())
                .map(|v| v * 60)
        })
        .unwrap_or(3600)
        .clamp(5, 86400);
    let mut settings = read_settings(&st.settings_path);
    settings["auto_refresh_enabled"] = json!(enabled);
    settings["auto_refresh_seconds"] = json!(seconds);
    settings["auto_refresh_minutes"] = json!((seconds / 60).max(1));
    if let Err(e) = write_settings(&st.settings_path, &settings) {
        return Json(json!({"error":e}));
    }
    Json(json!({
        "message": format!("auto refresh: {} / {}s", if enabled { "enabled" } else { "disabled" }, seconds),
        "enabled": enabled,
        "interval_seconds": seconds
    }))
}

async fn set_llm_settings(
    State(st): State<Arc<AppState>>,
    Json(payload): Json<Value>,
) -> Json<Value> {
    let llm = load_llm_settings_compat(&st.settings_path).with_payload(&payload, true);
    let mut settings = read_settings(&st.settings_path);
    settings["llm_enabled"] = json!(llm.enabled);
    settings["api_base"] = json!(llm.api_base.clone());
    settings["api_key"] = json!(llm.api_key.clone());
    settings["model"] = json!(llm.model.clone());
    settings["llm"] = llm.stored_json();
    if let Err(e) = write_settings(&st.settings_path, &settings) {
        return Json(json!({"error":e}));
    }
    Json(json!({"message":"LLM settings saved","item": llm.public_json()}))
}

async fn test_llm_settings(
    State(st): State<Arc<AppState>>,
    Json(payload): Json<Value>,
) -> Json<Value> {
    let llm = load_llm_settings_compat(&st.settings_path).with_payload(&payload, true);
    if !llm.configured() {
        return Json(json!({"error":"Please provide API Base, API Key, and Model"}));
    }
    if !llm.free_allowed() {
        return Json(json!({"error": FREE_LLM_ERROR}));
    }
    let url = llm.chat_completions_url();
    let body = json!({
        "model": llm.model,
        "messages":[{"role":"user","content":"Reply with OK only."}],
        "max_tokens": 8,
        "temperature": 0
    });
    let started = std::time::Instant::now();
    let resp = st
        .http
        .post(url.clone())
        .bearer_auth(llm.api_key.clone())
        .json(&body)
        .timeout(std::time::Duration::from_secs(30))
        .send()
        .await;
    let Ok(resp) = resp else {
        return Json(json!({"error":"Connection failed"}));
    };
    let status = resp.status().as_u16();
    let text = resp.text().await.unwrap_or_default();
    if status >= 400 {
        return Json(
            json!({"error": format!("HTTP {}: {}", status, text.chars().take(300).collect::<String>())}),
        );
    }
    let mut preview = String::new();
    if let Ok(parsed) = serde_json::from_str::<Value>(&text) {
        preview = parsed
            .get("choices")
            .and_then(|v| v.as_array())
            .and_then(|arr| arr.first())
            .and_then(|x| x.get("message"))
            .and_then(|x| x.get("content"))
            .and_then(|x| x.as_str())
            .unwrap_or("")
            .to_string();
    }
    Json(json!({
        "message":"Connection OK",
        "item":{
            "ok": true,
            "status_code": status,
            "latency_ms": started.elapsed().as_millis() as i64,
            "preview": preview.chars().take(160).collect::<String>(),
            "endpoint": url,
            "model": llm.model
        }
    }))
}

async fn refresh_all_impl(st: Arc<AppState>, days: i64, sample_fetches: i64) -> Value {
    let subs = {
        let _g = match st.db_lock.lock() {
            Ok(g) => g,
            Err(_) => return json!({"error":"db lock failed","items":[] }),
        };
        let c = match conn(&st.db_path) {
            Ok(v) => v,
            Err(e) => return json!({"error":e,"items":[] }),
        };
        let mut ids = Vec::new();
        if let Ok(mut stmt) =
            c.prepare("SELECT id,name FROM subscriptions WHERE enabled=1 ORDER BY id ASC")
        {
            if let Ok(rows) =
                stmt.query_map([], |r| Ok((r.get::<_, i64>(0)?, r.get::<_, String>(1)?)))
            {
                for row in rows.flatten() {
                    ids.push(row);
                }
            }
        }
        ids
    };
    let mut items = Vec::<Value>::new();
    for (sid, name) in subs {
        match refresh_one(st.clone(), sid, days, sample_fetches).await {
            Ok(v) => items.push(json!({"id":sid,"name":name,"status":"ok","items_seen":v["items_seen"],"items_saved":v["items_saved"]})),
            Err(e) => items.push(json!({"id":sid,"name":name,"status":"error","error":e})),
        }
    }
    json!({"message": format!("Refreshed {} subscriptions", items.len()), "items": items})
}

async fn refresh_all(
    State(st): State<Arc<AppState>>,
    Json(payload): Json<RefreshPayload>,
) -> Json<Value> {
    let days = payload.days.unwrap_or(7);
    let sample_fetches = payload.sample_fetches.unwrap_or(3);
    let _sample_interval = payload.sample_interval.unwrap_or(1.0);
    Json(refresh_all_impl(st, days, sample_fetches).await)
}

async fn refresh_subscription(
    State(st): State<Arc<AppState>>,
    Path(id): Path<i64>,
    Json(payload): Json<RefreshPayload>,
) -> Json<Value> {
    let days = payload.days.unwrap_or(7);
    let sample_fetches = payload.sample_fetches.unwrap_or(3);
    let _sample_interval = payload.sample_interval.unwrap_or(1.0);
    match refresh_one(st, id, days, sample_fetches).await {
        Ok(v) => Json(json!({
            "message": format!("Refreshed subscription {id} ({} seen, {} saved)", v["items_seen"], v["items_saved"]),
            "subscription": v["subscription"],
            "items_seen": v["items_seen"],
            "items_saved": v["items_saved"]
        })),
        Err(e) => Json(json!({"error":e})),
    }
}

async fn auto_refresh_loop(st: Arc<AppState>) {
    let mut next_due: Option<DateTime<Utc>> = None;
    let mut last_cfg = AutoRefreshConfig::default();
    loop {
        let cfg = load_auto_refresh_config(&st.settings_path);
        let now = Utc::now();

        {
            if let Ok(mut rt) = st.auto_runtime.lock() {
                rt.thread_alive = true;
                if !cfg.enabled {
                    rt.running = false;
                    rt.next_run_at = None;
                    if rt.last_status == "idle" {
                        rt.last_status = "disabled".to_string();
                    }
                }
            }
        }

        if !cfg.enabled {
            next_due = None;
            last_cfg = cfg;
            tokio::time::sleep(std::time::Duration::from_secs(2)).await;
            continue;
        }

        if next_due.is_none()
            || cfg.interval_seconds != last_cfg.interval_seconds
            || cfg.enabled != last_cfg.enabled
        {
            next_due = Some(now + Duration::seconds(cfg.interval_seconds));
        }
        last_cfg = cfg.clone();

        if let Some(due) = next_due {
            {
                if let Ok(mut rt) = st.auto_runtime.lock() {
                    rt.next_run_at = Some(due.to_rfc3339());
                }
            }
            if now >= due {
                {
                    if let Ok(mut rt) = st.auto_runtime.lock() {
                        rt.running = true;
                        rt.last_status = "running".to_string();
                    }
                }
                let result = refresh_all_impl(st.clone(), 7, 3).await;
                let items = result
                    .get("items")
                    .and_then(|v| v.as_array())
                    .cloned()
                    .unwrap_or_default();
                let errors = items
                    .iter()
                    .filter(|x| x.get("status").and_then(|s| s.as_str()) == Some("error"))
                    .count();
                let status = if errors == 0 { "ok" } else { "partial_error" };
                let message = result
                    .get("message")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string();
                {
                    if let Ok(mut rt) = st.auto_runtime.lock() {
                        rt.running = false;
                        rt.last_run_at = Some(Utc::now().to_rfc3339());
                        rt.last_status = status.to_string();
                        rt.last_message = if errors == 0 {
                            message
                        } else {
                            format!("{message}; errors={errors}")
                        };
                    }
                }
                next_due = Some(Utc::now() + Duration::seconds(cfg.interval_seconds));
            }
        }
        tokio::time::sleep(std::time::Duration::from_secs(1)).await;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ad_score_uses_body_context_for_course_packaging() {
        let title = "为什么普通人创业就赔钱？一堂课告诉你商业的真正逻辑";
        let summary = "一次关于创业选择的复盘";
        let content = "推荐给大家第29次。100个优惠名额。课程官网价199元。前100名仅需9.9元。点击图片报名。为期6天的线上训练，包含2节直播课、选修课和奖励课。";

        assert!(ad_score(title, summary, content) >= 2);
    }

    #[test]
    fn ad_score_does_not_block_course_style_title_without_commerce() {
        let title = "一堂课告诉你如何理解概率";
        let summary = "普通学习笔记";
        let content = "本文整理阅读笔记和个人理解，讨论概率思维、日常选择与学习方法。";

        assert!(ad_score(title, summary, content) < 2);
    }

    #[test]
    fn ad_score_keeps_known_hard_title_blocklist() {
        assert!(ad_score("八段锦的猛料，刺痛了多少中国女人", "", "") >= 2);
    }

    #[test]
    fn paid_article_cleaner_merges_broken_lines_and_keeps_markdown() {
        let payload = CleanMarkdownPayload {
            title: Some("测试标题".to_string()),
            source: Some("记忆承载".to_string()),
            published_at: None,
            content: Some(
                "测试标题\n\n这是一个被微信\n拆碎的段落，\n还没有结束\n\n[保留链接](https://example.com)\n\n文章原文"
                    .to_string(),
            ),
            input_format: Some("text".to_string()),
            smart_merge: Some(true),
            merge_mode: Some("smart".to_string()),
        };
        let value = clean_paid_article_payload(&payload);
        let markdown = value.get("markdown").and_then(|v| v.as_str()).unwrap_or("");
        assert!(markdown.starts_with("# 测试标题"));
        assert!(markdown.contains("> 来源：记忆承载"));
        assert!(markdown.contains("这是一个被微信拆碎的段落，还没有结束"));
        assert!(markdown.contains("[保留链接](https://example.com)"));
        assert!(!markdown.contains("文章原文"));
    }

    #[test]
    fn paid_article_cleaner_matches_bishu_short_paragraph_rhythm() {
        let payload = CleanMarkdownPayload {
            title: Some("短段落测试".to_string()),
            source: Some("记忆承载".to_string()),
            published_at: None,
            content: Some("短段落测试\n\n你讲的这个现象，非常普遍，你的留言，让我想起一本20年前看过的电视剧，士兵突击。许三多，被发配到红三连五班去看守草原补给站。班长老马，三个老兵，每天除了做梦，就是打牌，坚持出操，整理内务的许三多，反而显得像个异类。人嘛，都是怕兄弟苦，更怕兄弟开路虎。兄弟和自己一样苦，苦也不觉得苦，兄弟要是开了路虎，那比自己苦还糟心。".to_string()),
            input_format: Some("text".to_string()),
            smart_merge: None,
            merge_mode: Some("auto".to_string()),
        };
        let value = clean_paid_article_payload(&payload);
        let markdown = value.get("markdown").and_then(|v| v.as_str()).unwrap_or("");
        assert!(markdown.contains("许三多，被发配到红三连五班去看守草原补给站。"));
        assert!(markdown.contains("人嘛，都是怕兄弟苦，更怕兄弟开路虎。"));
        let body_paras = markdown
            .split("\n\n")
            .filter(|p| !p.starts_with('#') && !p.starts_with('>'))
            .collect::<Vec<_>>();
        assert!(body_paras.len() >= 5, "{markdown}");
        assert!(
            body_paras.iter().all(|p| p.chars().count() < 150),
            "{markdown}"
        );
    }

    #[test]
    fn paid_article_cleaner_includes_italic_published_time() {
        let payload = CleanMarkdownPayload {
            title: Some("time test".to_string()),
            source: Some("rss".to_string()),
            published_at: Some("2026-05-07 11:27".to_string()),
            content: Some("body".to_string()),
            input_format: Some("text".to_string()),
            smart_merge: None,
            merge_mode: Some("preserve".to_string()),
        };
        let value = clean_paid_article_payload(&payload);
        let markdown = value.get("markdown").and_then(|v| v.as_str()).unwrap_or("");
        assert!(
            markdown.contains("*\u{53D1}\u{5E03}\u{65F6}\u{95F4}\u{FF1A}2026-05-07 11:27*"),
            "{markdown}"
        );
    }

    #[test]
    fn paid_article_cleaner_preserves_html_links() {
        let payload = CleanMarkdownPayload {
            title: Some("link test".to_string()),
            source: Some("rss".to_string()),
            published_at: None,
            content: Some(
                r#"<p><a href="https://example.com/a">linked text</a></p><p>plain text.</p>"#
                    .to_string(),
            ),
            input_format: Some("html".to_string()),
            smart_merge: None,
            merge_mode: Some("auto".to_string()),
        };
        let value = clean_paid_article_payload(&payload);
        let markdown = value.get("markdown").and_then(|v| v.as_str()).unwrap_or("");
        assert!(
            markdown.contains("[linked text](https://example.com/a)"),
            "{markdown}"
        );
        assert!(markdown.contains("plain text."), "{markdown}");
    }

    #[test]
    fn paid_article_cleaner_recovers_bishu_rss_paragraph_beats() {
        let payload = CleanMarkdownPayload {
            title: Some("rss beat regression".to_string()),
            source: Some("Bishu".to_string()),
            published_at: None,
            content: Some("\u{6211}\u{4EEC}\u{6765}\u{770B}\u{8FD9}\u{4E2A}\u{95EE}\u{9898}\u{3002}\u{4F60}\u{8BB2}\u{7684}\u{8FD9}\u{4E2A}\u{73B0}\u{8C61}\u{FF0C}\u{975E}\u{5E38}\u{666E}\u{904D}\u{FF0C}\u{4F60}\u{7684}\u{7559}\u{8A00}\u{FF0C}\u{8BA9}\u{6211}\u{60F3}\u{8D77}\u{4E00}\u{672C}20\u{5E74}\u{524D}\u{770B}\u{8FC7}\u{7684}\u{7535}\u{89C6}\u{5267}\u{FF0C}\u{58EB}\u{5175}\u{7A81}\u{51FB}\u{3002}\u{8BB8}\u{4E09}\u{591A}\u{FF0C}\u{88AB}\u{53D1}\u{914D}\u{5230}\u{7EA2}\u{4E09}\u{8FDE}\u{4E94}\u{73ED}\u{53BB}\u{770B}\u{5B88}\u{8349}\u{539F}\u{8865}\u{7ED9}\u{7AD9}\u{3002}\u{73ED}\u{957F}\u{8001}\u{9A6C}\u{FF0C}\u{4E09}\u{4E2A}\u{8001}\u{5175}\u{FF0C}\u{6BCF}\u{5929}\u{9664}\u{4E86}\u{505A}\u{68A6}\u{FF0C}\u{5C31}\u{662F}\u{6253}\u{724C}\u{FF0C}\u{575A}\u{6301}\u{51FA}\u{64CD}\u{FF0C}\u{6574}\u{7406}\u{5185}\u{52A1}\u{7684}\u{8BB8}\u{4E09}\u{591A}\u{FF0C}\u{53CD}\u{800C}\u{663E}\u{5F97}\u{50CF}\u{4E2A}\u{5F02}\u{7C7B}\u{3002}\u{8001}\u{9A6C}\u{7ED9}\u{8BB8}\u{4E09}\u{591A}\u{8BB2}\u{8FC7}\u{8FD9}\u{4E48}\u{4E00}\u{4E2A}\u{5BD3}\u{8A00}\u{6545}\u{4E8B}\u{3002}".to_string()),
            input_format: Some("text".to_string()),
            smart_merge: None,
            merge_mode: Some("auto".to_string()),
        };
        let value = clean_paid_article_payload(&payload);
        let markdown = value.get("markdown").and_then(|v| v.as_str()).unwrap_or("");
        let expected = [
            "\u{6211}\u{4EEC}\u{6765}\u{770B}\u{8FD9}\u{4E2A}\u{95EE}\u{9898}\u{3002}",
            "\u{4F60}\u{8BB2}\u{7684}\u{8FD9}\u{4E2A}\u{73B0}\u{8C61}\u{FF0C}\u{975E}\u{5E38}\u{666E}\u{904D}\u{FF0C}\u{4F60}\u{7684}\u{7559}\u{8A00}\u{FF0C}\u{8BA9}\u{6211}\u{60F3}\u{8D77}\u{4E00}\u{672C}20\u{5E74}\u{524D}\u{770B}\u{8FC7}\u{7684}\u{7535}\u{89C6}\u{5267}\u{FF0C}\u{58EB}\u{5175}\u{7A81}\u{51FB}\u{3002}",
            "\u{8BB8}\u{4E09}\u{591A}\u{FF0C}\u{88AB}\u{53D1}\u{914D}\u{5230}\u{7EA2}\u{4E09}\u{8FDE}\u{4E94}\u{73ED}\u{53BB}\u{770B}\u{5B88}\u{8349}\u{539F}\u{8865}\u{7ED9}\u{7AD9}\u{3002}",
            "\u{73ED}\u{957F}\u{8001}\u{9A6C}\u{FF0C}\u{4E09}\u{4E2A}\u{8001}\u{5175}\u{FF0C}\u{6BCF}\u{5929}\u{9664}\u{4E86}\u{505A}\u{68A6}\u{FF0C}\u{5C31}\u{662F}\u{6253}\u{724C}\u{FF0C}\u{575A}\u{6301}\u{51FA}\u{64CD}\u{FF0C}\u{6574}\u{7406}\u{5185}\u{52A1}\u{7684}\u{8BB8}\u{4E09}\u{591A}\u{FF0C}\u{53CD}\u{800C}\u{663E}\u{5F97}\u{50CF}\u{4E2A}\u{5F02}\u{7C7B}\u{3002}",
            "\u{8001}\u{9A6C}\u{7ED9}\u{8BB8}\u{4E09}\u{591A}\u{8BB2}\u{8FC7}\u{8FD9}\u{4E48}\u{4E00}\u{4E2A}\u{5BD3}\u{8A00}\u{6545}\u{4E8B}\u{3002}",
        ];
        for para in expected {
            assert!(
                markdown.contains(para),
                "missing paragraph: {para}\n{markdown}"
            );
        }
        assert!(
            !markdown.contains("\u{6211}\u{4EEC}\u{6765}\u{770B}\u{8FD9}\u{4E2A}\u{95EE}\u{9898}\u{3002}\u{4F60}\u{8BB2}\u{7684}\u{8FD9}\u{4E2A}\u{73B0}\u{8C61}\u{FF0C}\u{975E}\u{5E38}\u{666E}\u{904D}\u{FF0C}\u{4F60}\u{7684}\u{7559}\u{8A00}\u{FF0C}\u{8BA9}\u{6211}\u{60F3}\u{8D77}\u{4E00}\u{672C}20\u{5E74}\u{524D}\u{770B}\u{8FC7}\u{7684}\u{7535}\u{89C6}\u{5267}\u{FF0C}\u{58EB}\u{5175}\u{7A81}\u{51FB}\u{3002}"),
            "short rhythm paragraphs should not be glued together: {markdown}"
        );
    }

    #[test]
    fn paid_article_cleaner_auto_segments_lumped_wechat_text() {
        let payload = CleanMarkdownPayload {
            title: Some("财富大洗牌，我该选择，还是努力？".to_string()),
            source: Some("记忆承载".to_string()),
            published_at: None,
            content: Some("财富大洗牌，我该选择，还是努力？\n\n今年以来，很多读者都在跟我讲，自己非常困惑。要是大家都在变得不好倒也罢了，关键是有人变得更好，而自己的处境越发不妙。更糟糕的是，所有传统方式都在失效。过去的二十年，讲究选择大于努力，可当下是：努力吧，像没头的苍蝇，选择吧，又进退失据。.......好，我们今天就来详细的探讨大家遇到的困惑。选择的重点是怎么选择，努力的关键在于怎么努力。以下进入正文：第一个话题，选择不是重点，基于什么选择才是。首先，提出选择大于努力这句话的人，逻辑还是颇严谨的。人家讲的是选择大于努力，人家可没说选择可以覆盖努力。第二个话题，一切选择的底层逻辑：赚Alpha的钱？还是Beta的钱？如果我们看表面现象，你会发现有360个行业。".to_string()),
            input_format: Some("text".to_string()),
            smart_merge: None,
            merge_mode: Some("auto".to_string()),
        };
        let value = clean_paid_article_payload(&payload);
        let markdown = value.get("markdown").and_then(|v| v.as_str()).unwrap_or("");
        assert!(markdown.contains("好，我们今天就来详细的探讨大家遇到的困惑。"));
        assert!(markdown.contains("## 第一个话题，选择不是重点，基于什么选择才是。"));
        assert!(!markdown.contains("以下进入正文"));
        assert!(markdown.contains("## 第二个话题，一切选择的底层逻辑：赚Alpha的钱？还是Beta的钱？"));
        let max_para = markdown
            .split("\n\n")
            .map(|p| p.chars().count())
            .max()
            .unwrap_or(0);
        assert!(
            max_para < 420,
            "max paragraph too long: {max_para}\n{markdown}"
        );
    }

    #[test]
    fn paid_article_cleaner_keeps_short_metadata_lines_separate() {
        let payload = CleanMarkdownPayload {
            title: Some("测试标题".to_string()),
            source: Some("记忆承载".to_string()),
            published_at: None,
            content: Some("测试标题\n\n碧树西风\n2026年05月07日\n广东\n\n正文第一段。".to_string()),
            input_format: Some("text".to_string()),
            smart_merge: Some(true),
            merge_mode: Some("smart".to_string()),
        };
        let value = clean_paid_article_payload(&payload);
        let markdown = value.get("markdown").and_then(|v| v.as_str()).unwrap_or("");
        assert!(markdown.contains("碧树西风\n\n2026年05月07日\n\n广东"));
        assert!(!markdown.contains("碧树西风2026年05月07日广东"));
    }

    #[test]
    fn paid_article_cleaner_keeps_demonstrative_continuation_together() {
        let payload = CleanMarkdownPayload {
            title: Some("rule regression".to_string()),
            source: Some("rss".to_string()),
            published_at: None,
            content: Some("\u{6211}\u{6839}\u{672C}\u{5C31}\u{4E0D}\u{662F}\u{90A3}\u{4E2A}\u{8D4C}\u{5F92}\u{4E86}\u{FF0C}\u{90A3}\u{4E2A}\u{8D4C}\u{5F92}\u{5DF2}\u{7ECF}\u{4ECE}\u{8BA4}\u{77E5}\u{6DF1}\u{5904}\u{90FD}\u{6B7B}\u{7FD8}\u{7FD8}\u{4E86}\u{FF0C}\u{73B0}\u{5728}\u{662F}\u{4E00}\u{4E2A}\u{5168}\u{65B0}\u{7684}\u{4EBA}\u{3002}\u{8FD9}\u{4E2A}\u{5168}\u{65B0}\u{7684}\u{6211}\u{662F}\u{5F00}\u{8D4C}\u{573A}\u{7684}\u{FF0C}\u{94B1}\u{6E90}\u{6E90}\u{4E0D}\u{65AD}\u{6D41}\u{5411}\u{6211}\u{FF0C}\u{5B83}\u{53EB}\u{4EA4}\u{6613}\u{7CFB}\u{7EDF}\u{3002}".to_string()),
            input_format: Some("text".to_string()),
            smart_merge: None,
            merge_mode: Some("auto".to_string()),
        };
        let value = clean_paid_article_payload(&payload);
        let markdown = value.get("markdown").and_then(|v| v.as_str()).unwrap_or("");
        assert!(markdown.contains("\u{5168}\u{65B0}\u{7684}\u{4EBA}\u{3002}\u{8FD9}\u{4E2A}\u{5168}\u{65B0}\u{7684}\u{6211}"), "{markdown}");
        assert!(
            !markdown.contains("\u{5168}\u{65B0}\u{7684}\u{4EBA}\u{3002}\n\n\u{8FD9}\u{4E2A}"),
            "{markdown}"
        );
        assert_eq!(
            value.get("llm_cleaner_status").and_then(|v| v.as_str()),
            Some("not_used")
        );
    }

    #[test]
    fn paid_article_cleaner_keeps_related_question_pair_together() {
        let payload = CleanMarkdownPayload {
            title: Some("question regression".to_string()),
            source: Some("rss".to_string()),
            published_at: None,
            content: Some("\u{5F88}\u{591A}\u{4EBA}\u{4E00}\u{542C}\u{5230}\u{9009}\u{62E9}\u{FF0C}\u{7B2C}\u{4E00}\u{53CD}\u{5E94}\u{4ECE}\u{6765}\u{90FD}\u{662F}\u{FF0C}\u{8981}\u{8003}\u{7814}\u{8FD8}\u{662F}\u{8981}\u{4E0A}\u{5CB8}\u{FF1F}\u{53BB}\u{54EA}\u{4E2A}\u{516C}\u{53F8}\u{4F1A}\u{53D1}\u{8D22}\u{FF1F}".to_string()),
            input_format: Some("text".to_string()),
            smart_merge: None,
            merge_mode: Some("auto".to_string()),
        };
        let value = clean_paid_article_payload(&payload);
        let markdown = value.get("markdown").and_then(|v| v.as_str()).unwrap_or("");
        assert!(markdown.contains("\u{8981}\u{8003}\u{7814}\u{8FD8}\u{662F}\u{8981}\u{4E0A}\u{5CB8}\u{FF1F}\u{53BB}\u{54EA}\u{4E2A}\u{516C}\u{53F8}\u{4F1A}\u{53D1}\u{8D22}\u{FF1F}"), "{markdown}");
        assert!(
            !markdown.contains("\u{4E0A}\u{5CB8}\u{FF1F}\n\n\u{53BB}\u{54EA}\u{4E2A}"),
            "{markdown}"
        );
    }

    #[test]
    fn paid_article_cleaner_keeps_new_user_regression_pairs() {
        let payload = CleanMarkdownPayload {
            title: Some("new regression".to_string()),
            source: Some("rss".to_string()),
            published_at: None,
            content: Some("\u{8981}\u{662F}\u{5927}\u{5BB6}\u{90FD}\u{5728}\u{53D8}\u{5F97}\u{4E0D}\u{597D}\u{5012}\u{4E5F}\u{7F62}\u{4E86}\u{FF0C}\u{5173}\u{952E}\u{662F}\u{6709}\u{4EBA}\u{53D8}\u{5F97}\u{66F4}\u{597D}\u{FF0C}\u{800C}\u{81EA}\u{5DF1}\u{7684}\u{5904}\u{5883}\u{8D8A}\u{53D1}\u{4E0D}\u{5999}\u{3002}\u{5C31}\u{50CF}\u{8D22}\u{5BCC}\u{5927}\u{6D17}\u{724C}\u{FF0C}\u{62BC}\u{6CE8}\u{78B3}\u{57FA}\u{7684}\u{FF0C}\u{90FD}\u{5728}\u{5411}\u{62BC}\u{6CE8}\u{7845}\u{57FA}\u{7684}\u{8F93}\u{8840}\u{3002}\n\u{6240}\u{4EE5}\u{4EA4}\u{6613}\u{7CFB}\u{7EDF}\u{7ED9}\u{4E00}\u{4E2A}\u{8D4C}\u{5F92}\u{6709}\u{7528}\u{4E48}\u{FF1F}\u{6CA1}\u{6709}\u{7684}\u{3002}\n\u{5954}\u{5B66}\u{672F}\u{53BB}\u{FF0C}\u{90A3}\u{5C31}\u{6309}\u{7167}\u{5B66}\u{672F}\u{7684}\u{8981}\u{6C42}\u{3002}\u{4E0D}\u{5954}\u{5B66}\u{672F}\u{53BB}\u{FF0C}\u{90A3}\u{5C31}\u{6309}\u{7167}\u{6700}\u{7701}\u{65F6}\u{8981}\u{6C42}\u{3002}".to_string()),
            input_format: Some("text".to_string()),
            smart_merge: None,
            merge_mode: Some("auto".to_string()),
        };
        let value = clean_paid_article_payload(&payload);
        let markdown = value.get("markdown").and_then(|v| v.as_str()).unwrap_or("");
        assert!(markdown.contains("\u{8D8A}\u{53D1}\u{4E0D}\u{5999}\u{3002}\u{5C31}\u{50CF}\u{8D22}\u{5BCC}\u{5927}\u{6D17}\u{724C}"), "{markdown}");
        assert!(markdown.contains("\u{6240}\u{4EE5}\u{4EA4}\u{6613}\u{7CFB}\u{7EDF}\u{7ED9}\u{4E00}\u{4E2A}\u{8D4C}\u{5F92}\u{6709}\u{7528}\u{4E48}\u{FF1F}\u{6CA1}\u{6709}\u{7684}\u{3002}"), "{markdown}");
        assert!(markdown.contains("\u{5954}\u{5B66}\u{672F}\u{53BB}\u{FF0C}\u{90A3}\u{5C31}\u{6309}\u{7167}\u{5B66}\u{672F}\u{7684}\u{8981}\u{6C42}\u{3002}\u{4E0D}\u{5954}\u{5B66}\u{672F}\u{53BB}"), "{markdown}");
        assert!(
            !markdown.contains("\u{4E0D}\u{5999}\u{3002}\n\n\u{5C31}\u{50CF}"),
            "{markdown}"
        );
        assert!(
            !markdown.contains("\u{7528}\u{4E48}\u{FF1F}\n\n\u{6CA1}\u{6709}"),
            "{markdown}"
        );
        assert!(
            !markdown.contains("\u{8981}\u{6C42}\u{3002}\n\n\u{4E0D}\u{5954}"),
            "{markdown}"
        );
    }

    #[test]
    fn paid_article_cleaner_preserves_html_bold() {
        let payload = CleanMarkdownPayload {
            title: Some("bold regression".to_string()),
            source: Some("rss".to_string()),
            published_at: None,
            content: Some(
                r#"<p><strong>core point</strong>: keep bold.</p><p><b>second point</b></p>"#
                    .to_string(),
            ),
            input_format: Some("html".to_string()),
            smart_merge: None,
            merge_mode: Some("preserve".to_string()),
        };
        let value = clean_paid_article_payload(&payload);
        let markdown = value.get("markdown").and_then(|v| v.as_str()).unwrap_or("");
        assert!(markdown.contains("**core point**"), "{markdown}");
        assert!(markdown.contains("**second point**"), "{markdown}");
    }

    #[test]
    fn yage_new_kit_html_wrapper_is_removed_before_markdown() {
        let raw = r#"
<table><tbody><tr><td><div>
<meta>
<title>Noise title</title>
<style>
body { font-family: sans-serif; }
h1 { color: red; }
</style>
<h1>[鸭哥 AI 手记] 2026-05-03: 正文标题</h1>
<p>&gt; 第一段摘要。</p>
<p><strong>懒人包：真正的正文。</strong></p>
</div></td></tr></tbody></table>
"#;
        let cleaned = crate::yage::yage_prepare_content_html(raw);
        let markdown = parse_html_preserving_inline_markdown(&cleaned);

        assert!(markdown.contains("[鸭哥 AI 手记] 2026-05-03: 正文标题"));
        assert!(markdown.contains("第一段摘要"));
        assert!(markdown.contains("懒人包"));
        assert!(!markdown.contains("font-family"));
        assert!(!markdown.contains("Noise title"));
        assert!(!markdown.trim_start().starts_with('|'));
    }
}

#[tokio::main]
async fn main() {
    let host = std::env::var("WECHAT_RSS_HOST").unwrap_or_else(|_| "0.0.0.0".to_string());
    let port: u16 = std::env::var("WECHAT_RSS_PORT")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(8091);
    let base_dir = std::env::var("WECHAT_RSS_BASE_DIR")
        .unwrap_or_else(|_| "/root/.nanobot/workspace/wechat_rss_service".to_string());
    let db_path =
        std::env::var("WECHAT_RSS_DB").unwrap_or_else(|_| format!("{base_dir}/service.db"));
    let settings_path = std::env::var("WECHAT_RSS_SETTINGS")
        .unwrap_or_else(|_| format!("{base_dir}/settings.json"));

    let _ = db::init_db(&db_path);
    let http = Client::builder()
        .timeout(std::time::Duration::from_secs(25))
        .user_agent("wechat-rss-rs/0.2")
        .build()
        .expect("http client build failed");
    let state = Arc::new(AppState {
        db_path: PathBuf::from(db_path),
        settings_path: PathBuf::from(settings_path),
        db_lock: Arc::new(Mutex::new(())),
        http,
        auto_runtime: Arc::new(Mutex::new(AutoRefreshRuntime::default())),
    });

    tokio::spawn(auto_refresh_loop(state.clone()));

    let app = Router::new()
        .route("/", get(root))
        .route("/rss", get(root))
        .route("/rss/", get(root))
        .route("/cleaner", get(cleaner_page))
        .route("/cleaner/", get(cleaner_page))
        .route("/rss/cleaner", get(cleaner_page))
        .route("/rss/cleaner/", get(cleaner_page))
        .route("/api/health", get(health))
        .route("/api/auto-refresh-status", get(auto_refresh_status))
        .route(
            "/api/subscriptions",
            get(list_subscriptions).post(create_subscription),
        )
        .route("/api/subscriptions/{id}/toggle", post(toggle_subscription))
        .route("/api/subscriptions/{id}/update", post(update_subscription))
        .route("/api/subscriptions/{id}/delete", post(delete_subscription))
        .route(
            "/api/subscriptions/{id}/refresh",
            post(refresh_subscription),
        )
        .route("/api/entries", get(list_entries))
        .route("/api/timeline", get(list_entries))
        .route("/api/new-items", get(list_new_items))
        .route("/api/runs", get(list_runs))
        .route(
            "/api/settings/llm",
            get(get_settings_llm).post(set_llm_settings),
        )
        .route("/api/settings/llm/test", post(test_llm_settings))
        .route("/api/settings/auto-refresh", post(set_auto_refresh))
        .route("/api/articles/{id}", get(get_article))
        .route("/api/articles/{id}/markdown", get(get_article_markdown))
        .route("/api/latest", get(qq_rss_api::latest))
        .route("/api/ask", get(qq_rss_api::ask))
        .route("/api/push/wechat-signed", get(qq_rss_api::wechat_signed))
        .route("/api/push/wechat-recover", get(qq_rss_api::wechat_recover))
        .route("/api/push/wechat-ack", get(qq_rss_api::wechat_ack))
        .route("/api/push/yage-signed", get(qq_rss_api::yage_signed))
        .route("/api/push/yage-ack", get(qq_rss_api::yage_ack))
        .route("/api/clean-markdown", post(clean_markdown))
        .route("/api/clean-markdown/refine", post(refine_clean_markdown))
        .route("/api/refresh-all", post(refresh_all))
        .with_state(state);

    let addr: SocketAddr = format!("{}:{}", host, port)
        .parse()
        .expect("invalid address");
    println!("wechat-rss-rs listening on http://{}", addr);
    let listener = tokio::net::TcpListener::bind(addr)
        .await
        .expect("bind failed");
    axum::serve(listener, app).await.expect("server failed");
}
