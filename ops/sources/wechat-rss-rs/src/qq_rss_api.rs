use axum::{
    extract::{Query, State},
    Json,
};
use chrono::{DateTime, Duration, FixedOffset, Utc};
use regex::Regex;
use ring::digest::{Context, SHA256};
use rusqlite::params;
use serde::Deserialize;
use serde_json::{json, Value};
use std::{fs, sync::Arc};

use crate::{
    ad_score, conn, fetch_article_markdown_from_link, map_entry_row, refresh_all_impl, refresh_one,
    AppState, Entry,
};

use crate::qq_article_format::format_article_push_body;
use crate::qq_extractive_qa::extractive_answer;

const SIGNED_PREFIX: &str = "NBRAW1-SHA256:";
const WECHAT_CACHE_FILE: &str =
    "/root/.nanobot/workspace/skills/wechat-rss-sidecar/wechat_push_cache.json";
const YAGE_CACHE_FILE: &str = "/root/.nanobot/workspace/skills/news-curator/yage_cache.json";
const YAGE_BIZ_DAILY: &str = "yage_kit_daily";
const YAGE_SUB_NAME_HINT: &str = "鸭哥AI要闻-每日记录";

#[derive(Debug, Deserialize, Default, Clone)]
pub(crate) struct RssActionQuery {
    days: Option<i64>,
    limit: Option<i64>,
    subscription_id: Option<i64>,
    refresh: Option<bool>,
    sample_fetches: Option<i64>,
    sample_interval: Option<f64>,
    question: Option<String>,
    entry_id: Option<i64>,
    force: Option<bool>,
    latest: Option<bool>,
    nth: Option<i64>,
    date: Option<String>,
    url: Option<String>,
    digest: Option<String>,
}

fn positive(value: Option<i64>, default: i64, minimum: i64) -> i64 {
    value.unwrap_or(default).max(minimum)
}

fn parse_utc(value: Option<&str>) -> DateTime<Utc> {
    let text = value.unwrap_or("").trim();
    if text.is_empty() {
        return DateTime::<Utc>::MIN_UTC;
    }
    DateTime::parse_from_rfc3339(text)
        .or_else(|_| DateTime::parse_from_rfc2822(text))
        .map(|dt| dt.with_timezone(&Utc))
        .unwrap_or(DateTime::<Utc>::MIN_UTC)
}

fn shanghai_hour() -> u32 {
    let tz = FixedOffset::east_opt(8 * 3600).expect("valid shanghai offset");
    Utc::now().with_timezone(&tz).hour()
}

trait HourExt {
    fn hour(&self) -> u32;
}

impl HourExt for chrono::DateTime<FixedOffset> {
    fn hour(&self) -> u32 {
        use chrono::Timelike;
        Timelike::hour(self)
    }
}

fn select_entries(
    st: &Arc<AppState>,
    days: i64,
    limit: i64,
    subscription_id: Option<i64>,
) -> Result<Vec<Entry>, String> {
    let days = days.max(1);
    let limit = limit.max(1);
    let cutoff = (Utc::now() - Duration::days(days)).to_rfc3339();
    let _g = st
        .db_lock
        .lock()
        .map_err(|_| "db lock failed".to_string())?;
    let c = conn(&st.db_path)?;
    let mut items = Vec::<Entry>::new();
    let with_sid = subscription_id.is_some();
    let sql = if with_sid {
        "SELECT e.id,e.subscription_id,e.guid,e.title,e.link,e.summary,e.content_markdown,e.published_at,e.inserted_at,e.last_seen_at,e.sample_hits,s.name FROM entries e JOIN subscriptions s ON s.id=e.subscription_id WHERE (e.published_at IS NULL OR e.published_at >= ?1) AND e.subscription_id=?2 ORDER BY e.published_at DESC, e.inserted_at DESC LIMIT ?3"
    } else {
        "SELECT e.id,e.subscription_id,e.guid,e.title,e.link,e.summary,e.content_markdown,e.published_at,e.inserted_at,e.last_seen_at,e.sample_hits,s.name FROM entries e JOIN subscriptions s ON s.id=e.subscription_id WHERE (e.published_at IS NULL OR e.published_at >= ?1) ORDER BY e.published_at DESC, e.inserted_at DESC LIMIT ?2"
    };
    let mut stmt = c.prepare(sql).map_err(|e| e.to_string())?;
    let rows = if with_sid {
        stmt.query_map(
            params![cutoff, subscription_id.unwrap_or_default(), limit],
            map_entry_row,
        )
    } else {
        stmt.query_map(params![cutoff, limit], map_entry_row)
    }
    .map_err(|e| e.to_string())?;
    for row in rows.flatten() {
        if ad_score(&row.title, &row.summary, &row.content_markdown) >= 2 {
            continue;
        }
        items.push(row);
    }
    items.sort_by(|a, b| {
        (
            parse_utc(a.published_at.as_deref()),
            parse_utc(a.inserted_at.as_deref()),
            a.id,
        )
            .cmp(&(
                parse_utc(b.published_at.as_deref()),
                parse_utc(b.inserted_at.as_deref()),
                b.id,
            ))
            .reverse()
    });
    Ok(items)
}

fn load_entry(st: &Arc<AppState>, id: i64) -> Result<Entry, String> {
    let _g = st
        .db_lock
        .lock()
        .map_err(|_| "db lock failed".to_string())?;
    let c = conn(&st.db_path)?;
    let sql = "SELECT e.id,e.subscription_id,e.guid,e.title,e.link,e.summary,e.content_markdown,e.published_at,e.inserted_at,e.last_seen_at,e.sample_hits,s.name FROM entries e JOIN subscriptions s ON s.id=e.subscription_id WHERE e.id=?1";
    let mut stmt = c.prepare(sql).map_err(|e| e.to_string())?;
    stmt.query_row(params![id], map_entry_row)
        .map_err(|_| "entry not found".to_string())
}

async fn article_markdown(st: &Arc<AppState>, entry: &Entry) -> String {
    let mut md = if entry.content_markdown.trim().is_empty() {
        entry.summary.clone()
    } else {
        entry.content_markdown.clone()
    };
    if md.trim().len() < 240 {
        if let Some(fetched) = fetch_article_markdown_from_link(&st.http, &entry.link).await {
            if fetched.len() > md.len() {
                md = fetched.clone();
            }
            if let Ok(_g) = st.db_lock.lock() {
                if let Ok(c) = conn(&st.db_path) {
                    let min_len = md.len() as i64;
                    let _ = c.execute(
                        "UPDATE entries SET content_markdown=CASE WHEN length(coalesce(content_markdown,''))>=?1 THEN content_markdown ELSE ?2 END WHERE id=?3",
                        params![min_len, md.clone(), entry.id],
                    );
                }
            }
        } else if md.trim().is_empty() {
            md = entry.summary.clone();
        }
    }
    md.trim().to_string()
}

async fn build_article_payload(st: Arc<AppState>, entry: Entry) -> Value {
    let markdown = article_markdown(&st, &entry).await;
    json!({
        "entry_id": entry.id,
        "title": entry.title,
        "subscription_name": entry.subscription_name.unwrap_or_default(),
        "published_at": entry.published_at.unwrap_or_default(),
        "published_at_local": entry.published_at_local.unwrap_or_default(),
        "link": entry.link,
        "article_markdown": markdown,
    })
}

async fn maybe_refresh(st: Arc<AppState>, q: &RssActionQuery, days: i64, sample_fetches: i64) {
    if !q.refresh.unwrap_or(false) {
        return;
    }
    if let Some(sid) = q.subscription_id.filter(|v| *v > 0) {
        let _ = refresh_one(st, sid, days, sample_fetches).await;
    } else {
        let _ = refresh_all_impl(st, days, sample_fetches).await;
    }
    let pause = q.sample_interval.unwrap_or(0.0).max(0.0);
    if pause > 0.0 {
        tokio::time::sleep(std::time::Duration::from_secs_f64(pause.min(3.0))).await;
    }
}

async fn latest_value(st: Arc<AppState>, q: RssActionQuery) -> Value {
    let days = positive(q.days, 7, 1);
    let limit = positive(q.limit, 50, 1).max(10);
    let sample_fetches = positive(q.sample_fetches, 3, 1);
    maybe_refresh(st.clone(), &q, days, sample_fetches).await;
    let items = match select_entries(&st, days, limit, q.subscription_id) {
        Ok(v) => v,
        Err(e) => {
            return json!({"status":"error","reason":e,"days":days,"subscription_id":q.subscription_id.unwrap_or(0)})
        }
    };
    let Some(top) = items.into_iter().next() else {
        return json!({"status":"empty","reason":"NO_ITEMS_IN_TIMELINE","days":days,"subscription_id":q.subscription_id.unwrap_or(0)});
    };
    if top.id <= 0 {
        return json!({"status":"error","reason":"INVALID_ENTRY_ID","days":days,"subscription_id":q.subscription_id.unwrap_or(0)});
    }
    let picked_entry_id = top.id;
    let picked_published_at = top.published_at.clone().unwrap_or_default();
    let picked_inserted_at = top.inserted_at.clone().unwrap_or_default();
    let mut article = build_article_payload(st, top).await;
    if let Some(obj) = article.as_object_mut() {
        obj.insert("status".to_string(), json!("ok"));
        obj.insert(
            "selection".to_string(),
            json!({
                "picked_entry_id": picked_entry_id,
                "picked_published_at": picked_published_at,
                "picked_inserted_at": picked_inserted_at,
                "days": days,
                "limit": limit,
                "subscription_id": q.subscription_id.unwrap_or(0),
                "refresh": q.refresh.unwrap_or(false),
            }),
        );
    }
    article
}

pub(crate) async fn latest(
    State(st): State<Arc<AppState>>,
    Query(q): Query<RssActionQuery>,
) -> Json<Value> {
    Json(latest_value(st, q).await)
}

pub(crate) async fn ask(
    State(st): State<Arc<AppState>>,
    Query(q): Query<RssActionQuery>,
) -> Json<Value> {
    let question = q.question.clone().unwrap_or_default();
    let article = if let Some(entry_id) = q.entry_id.filter(|v| *v > 0) {
        match load_entry(&st, entry_id) {
            Ok(entry) => build_article_payload(st.clone(), entry).await,
            Err(e) => {
                return Json(
                    json!({"status":"not_found","question":question,"answer":"NOT_FOUND_IN_ARTICLE","reason":e,"evidence":[]}),
                )
            }
        }
    } else {
        let latest = latest_value(st.clone(), q.clone()).await;
        if latest
            .get("status")
            .and_then(|v| v.as_str())
            .is_some_and(|s| s != "ok")
        {
            return Json(
                json!({"status":"not_found","question":question,"answer":"NOT_FOUND_IN_ARTICLE","reason":latest.get("reason").and_then(|v| v.as_str()).unwrap_or("LATEST_NOT_AVAILABLE"),"evidence":[]}),
            );
        }
        latest
    };
    let markdown = article
        .get("article_markdown")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let result = extractive_answer(markdown, &question, 8);
    Json(json!({
        "status": result.get("status").and_then(|v| v.as_str()).unwrap_or("not_found"),
        "mode": "extractive",
        "question": question,
        "entry_id": article.get("entry_id").and_then(|v| v.as_i64()).unwrap_or(q.entry_id.unwrap_or(0)),
        "published_at": article.get("published_at").and_then(|v| v.as_str()).unwrap_or(""),
        "published_at_local": article.get("published_at_local").and_then(|v| v.as_str()).unwrap_or(""),
        "title": article.get("title").and_then(|v| v.as_str()).unwrap_or(""),
        "link": article.get("link").and_then(|v| v.as_str()).unwrap_or(""),
        "tokens": result.get("tokens").cloned().unwrap_or_else(|| json!([])),
        "answer": result.get("answer").and_then(|v| v.as_str()).unwrap_or("NOT_FOUND_IN_ARTICLE"),
        "evidence": result.get("evidence").cloned().unwrap_or_else(|| json!([])),
    }))
}

fn hex_lower(bytes: &[u8]) -> String {
    const LUT: &[u8; 16] = b"0123456789abcdef";
    let mut out = String::with_capacity(bytes.len() * 2);
    for &b in bytes {
        out.push(LUT[(b >> 4) as usize] as char);
        out.push(LUT[(b & 0x0f) as usize] as char);
    }
    out
}

fn sha256_hex(body: &str) -> String {
    let mut ctx = Context::new(&SHA256);
    ctx.update(body.as_bytes());
    hex_lower(ctx.finish().as_ref())
}

fn sign_nbraw_sha256(body: &str) -> String {
    let digest = sha256_hex(body);
    format!("{SIGNED_PREFIX}{digest}\n\n{body}")
}

fn read_json_file(path: &str) -> Value {
    fs::read_to_string(path)
        .ok()
        .and_then(|text| serde_json::from_str(&text).ok())
        .unwrap_or_else(|| json!({}))
}

fn write_json_file_atomic(path: &str, value: &Value) -> Result<(), String> {
    let tmp = format!("{path}.tmp");
    let data = serde_json::to_vec(value).map_err(|e| e.to_string())?;
    fs::write(&tmp, data).map_err(|e| e.to_string())?;
    fs::rename(&tmp, path).map_err(|e| e.to_string())
}

fn wechat_candidate_subscription_ids() -> Vec<i64> {
    let mut ids = Vec::<i64>::new();
    if let Some(obj) = read_json_file(WECHAT_CACHE_FILE).as_object() {
        for key in obj.keys() {
            if let Some(raw) = key.strip_prefix("sub:") {
                if let Ok(id) = raw.parse::<i64>() {
                    if id > 0 && !ids.contains(&id) {
                        ids.push(id);
                    }
                }
            }
        }
    }
    for id in [1_i64, 2, 3] {
        if !ids.contains(&id) {
            ids.push(id);
        }
    }
    ids
}

fn should_ack_yage_url(previous_url: &str, candidate_url: &str) -> bool {
    let prev = previous_url.trim();
    let cand = candidate_url.trim();
    if cand.is_empty() {
        return false;
    }
    if prev.is_empty() {
        return true;
    }
    if prev == cand {
        return false;
    }
    let prev_dt = extract_date_in_url(prev);
    let cand_dt = extract_date_in_url(cand);
    if !prev_dt.is_empty() && !cand_dt.is_empty() {
        return cand_dt >= prev_dt;
    }
    false
}

async fn build_wechat_signed_value(st: Arc<AppState>, q: RssActionQuery) -> Value {
    let article = latest_value(st, q.clone()).await;
    if article.get("status").and_then(|v| v.as_str()) != Some("ok") {
        return json!({"status":"empty","reason":article.get("reason").and_then(|v| v.as_str()).unwrap_or("LATEST_NOT_AVAILABLE")});
    }
    let entry_id = article
        .get("entry_id")
        .and_then(|v| v.as_i64())
        .unwrap_or(0);
    if entry_id <= 0 {
        return json!({"status":"empty","reason":"INVALID_ENTRY_ID"});
    }
    let subscription_id = q.subscription_id.unwrap_or(0).max(0);
    let cache_key = format!("sub:{subscription_id}");
    let force = q.force.unwrap_or(true);
    let cached = read_json_file(WECHAT_CACHE_FILE)
        .get(&cache_key)
        .and_then(|v| v.as_i64())
        .unwrap_or(0);
    if !force && cached == entry_id {
        return json!({"status":"empty","reason":"ALREADY_SENT","entry_id":entry_id,"subscription_id":subscription_id});
    }
    let mut body = format_article_push_body(&article);
    if body.trim().is_empty() {
        return json!({"status":"empty","reason":"EMPTY_BODY","entry_id":entry_id,"subscription_id":subscription_id});
    }
    body = format!("{body}\n\n<!-- NBACK_WECHAT sub:{subscription_id} entry:{entry_id} -->")
        .trim()
        .to_string();
    let digest = sha256_hex(&body);
    let signed_payload = format!("{SIGNED_PREFIX}{digest}\n\n{body}");
    json!({
        "status": "ok",
        "entry_id": entry_id,
        "subscription_id": subscription_id,
        "title": article.get("title").cloned().unwrap_or_else(|| json!("")),
        "link": article.get("link").cloned().unwrap_or_else(|| json!("")),
        "body": body,
        "digest": digest,
        "signed_payload": signed_payload,
    })
}

pub(crate) async fn wechat_signed(
    State(st): State<Arc<AppState>>,
    Query(q): Query<RssActionQuery>,
) -> Json<Value> {
    Json(build_wechat_signed_value(st, q).await)
}

pub(crate) async fn wechat_recover(
    State(st): State<Arc<AppState>>,
    Query(q): Query<RssActionQuery>,
) -> Json<Value> {
    let expected = q
        .digest
        .clone()
        .unwrap_or_default()
        .trim()
        .to_ascii_lowercase();
    if expected.is_empty() {
        return Json(json!({"status":"empty","reason":"MISSING_DIGEST"}));
    }
    for sid in wechat_candidate_subscription_ids() {
        let mut sub_q = q.clone();
        sub_q.subscription_id = Some(sid);
        sub_q.force = Some(true);
        let value = build_wechat_signed_value(st.clone(), sub_q).await;
        if value.get("status").and_then(|v| v.as_str()) == Some("ok")
            && value.get("digest").and_then(|v| v.as_str()) == Some(expected.as_str())
        {
            return Json(value);
        }
    }
    Json(json!({"status":"empty","reason":"DIGEST_NOT_FOUND"}))
}

pub(crate) async fn wechat_ack(Query(q): Query<RssActionQuery>) -> Json<Value> {
    let sub_id = q.subscription_id.unwrap_or(0).max(0);
    let entry_id = q.entry_id.unwrap_or(0);
    if entry_id <= 0 {
        return Json(json!({"status":"error","reason":"INVALID_ENTRY_ID"}));
    }
    let cache_key = format!("sub:{sub_id}");
    let mut cache = read_json_file(WECHAT_CACHE_FILE);
    if !cache.is_object() {
        cache = json!({});
    }
    let prev = cache.get(&cache_key).and_then(|v| v.as_i64()).unwrap_or(0);
    if entry_id <= prev {
        return Json(
            json!({"status":"ok","updated":false,"key":cache_key,"prev":prev,"entry_id":entry_id}),
        );
    }
    if let Some(obj) = cache.as_object_mut() {
        obj.insert(cache_key.clone(), json!(entry_id));
    }
    match write_json_file_atomic(WECHAT_CACHE_FILE, &cache) {
        Ok(()) => Json(
            json!({"status":"ok","updated":true,"key":cache_key,"prev":prev,"entry_id":entry_id}),
        ),
        Err(e) => Json(
            json!({"status":"error","reason":e,"updated":false,"key":cache_key,"prev":prev,"entry_id":entry_id}),
        ),
    }
}

pub(crate) async fn yage_ack(Query(q): Query<RssActionQuery>) -> Json<Value> {
    let source_url = q.url.unwrap_or_default();
    if source_url.trim().is_empty() {
        return Json(json!({"status":"error","reason":"MISSING_SOURCE_URL"}));
    }
    let mut cache = read_json_file(YAGE_CACHE_FILE);
    if !cache.is_object() {
        cache = json!({});
    }
    let prev = cache
        .get("last_url")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_string();
    if !should_ack_yage_url(&prev, &source_url) {
        return Json(json!({"status":"ok","updated":false,"prev":prev,"source_url":source_url}));
    }
    if let Some(obj) = cache.as_object_mut() {
        obj.insert("last_url".to_string(), json!(source_url));
    }
    match write_json_file_atomic(YAGE_CACHE_FILE, &cache) {
        Ok(()) => Json(json!({"status":"ok","updated":true,"prev":prev,"source_url":source_url})),
        Err(e) => Json(
            json!({"status":"error","reason":e,"updated":false,"prev":prev,"source_url":source_url}),
        ),
    }
}

fn find_yage_daily_subscription_id(st: &Arc<AppState>) -> Option<i64> {
    let _g = st.db_lock.lock().ok()?;
    let c = conn(&st.db_path).ok()?;
    let mut stmt = c
        .prepare("SELECT id,biz,name FROM subscriptions ORDER BY id ASC")
        .ok()?;
    let rows = stmt
        .query_map([], |r| {
            Ok((
                r.get::<_, i64>(0)?,
                r.get::<_, String>(1)?,
                r.get::<_, String>(2)?,
            ))
        })
        .ok()?;
    let mut by_name = None;
    for row in rows.flatten() {
        let (id, biz, name) = row;
        if biz.trim() == YAGE_BIZ_DAILY {
            return Some(id);
        }
        if by_name.is_none() && name.contains(YAGE_SUB_NAME_HINT) {
            by_name = Some(id);
        }
    }
    by_name
}

fn extract_date_in_url(url: &str) -> String {
    Regex::new(r"(20\d{2}-\d{2}-\d{2})")
        .expect("valid yage date regex")
        .captures(url)
        .and_then(|cap| cap.get(1).map(|m| m.as_str().to_string()))
        .unwrap_or_default()
}

fn pick_yage_entry(
    entries: Vec<Entry>,
    nth: i64,
    target_date: &str,
    target_url: &str,
) -> Option<Entry> {
    if !target_url.trim().is_empty() {
        return entries
            .into_iter()
            .find(|e| e.link.trim() == target_url.trim());
    }
    if !target_date.trim().is_empty() {
        return entries
            .into_iter()
            .find(|e| extract_date_in_url(&e.link) == target_date.trim());
    }
    let idx = nth.max(1) as usize - 1;
    entries.into_iter().nth(idx)
}

pub(crate) async fn yage_signed(
    State(st): State<Arc<AppState>>,
    Query(q): Query<RssActionQuery>,
) -> Json<Value> {
    let hour = shanghai_hour();
    if !(hour >= 19 || hour < 2) {
        return Json(json!({"status":"empty","reason":"OUTSIDE_YAGE_WINDOW"}));
    }
    let Some(sub_id) = find_yage_daily_subscription_id(&st) else {
        return Json(json!({"status":"empty","reason":"YAGE_SUBSCRIPTION_NOT_FOUND"}));
    };
    let entries = match select_entries(&st, 120, 200, Some(sub_id)) {
        Ok(v) => v,
        Err(e) => return Json(json!({"status":"error","reason":e})),
    };
    let target_date = q.date.clone().unwrap_or_default();
    let target_url = q.url.clone().unwrap_or_default();
    let latest = q.latest.unwrap_or(false);
    let nth = if latest { 1 } else { positive(q.nth, 1, 1) };
    let Some(entry) = pick_yage_entry(entries, nth, &target_date, &target_url) else {
        return Json(json!({"status":"empty","reason":"YAGE_ENTRY_NOT_FOUND"}));
    };
    let source_url = entry.link.trim().to_string();
    let custom_selector =
        !target_date.trim().is_empty() || nth > 1 || !target_url.trim().is_empty();
    if !latest && !custom_selector {
        let cached = read_json_file(YAGE_CACHE_FILE)
            .get("last_url")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .trim()
            .to_string();
        if !cached.is_empty() && cached == source_url {
            return Json(json!({"status":"empty","reason":"ALREADY_SENT","link":source_url}));
        }
    }
    let mut body = entry.content_markdown.trim().to_string();
    if body.is_empty() {
        let title = if entry.title.trim().is_empty() {
            "鸭哥 AI 要闻"
        } else {
            entry.title.trim()
        };
        body = format!("## {title}");
    }
    if !source_url.is_empty() {
        body = format!("{body}\n\n---\n\n原文链接：[查看原文]({source_url})");
    }
    let signed_payload = sign_nbraw_sha256(&body);
    Json(json!({
        "status": "ok",
        "entry_id": entry.id,
        "subscription_id": sub_id,
        "title": entry.title,
        "link": source_url,
        "body": body,
        "signed_payload": signed_payload,
    }))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn yage_ack_only_advances_to_newer_urls() {
        assert!(should_ack_yage_url(
            "",
            "https://yage-ai.kit.com/posts/2026-05-08-news"
        ));
        assert!(should_ack_yage_url(
            "https://yage-ai.kit.com/posts/2026-05-07-old",
            "https://yage-ai.kit.com/posts/2026-05-08-news"
        ));
        assert!(!should_ack_yage_url(
            "https://yage-ai.kit.com/posts/2026-05-08-news",
            "https://yage-ai.kit.com/posts/2026-05-07-old"
        ));
        assert!(!should_ack_yage_url(
            "https://yage-ai.kit.com/posts/2026-05-08-news",
            "https://yage-ai.kit.com/posts/2026-05-08-news"
        ));
    }

    #[test]
    fn nbraw_signature_has_expected_prefix_and_body() {
        let signed = sign_nbraw_sha256("hello");
        assert!(signed.starts_with(
            "NBRAW1-SHA256:2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824\n\n"
        ));
        assert!(signed.ends_with("hello"));
    }

    #[test]
    fn paid_teaser_notice_does_not_forward_snippet_body() {
        let article = json!({
            "title": "财富大洗牌",
            "subscription_name": "记忆承载",
            "published_at_local": "2026-05-07 11:27:00",
            "link": "https://mp.weixin.qq.com/s/test",
            "article_markdown": "全文两文字，共分五个话题，文中多处有链接，俗称画中画，文中文。本文下面的每一条留言，我都会看到。以下进入正文：文章原文"
        });
        let body = format_article_push_body(&article);
        assert!(body.contains("付费文章导流"));
        assert!(body.contains("[文章原文](https://mp.weixin.qq.com/s/test)"));
        assert!(!body.contains("全文两文字"));
    }

    #[test]
    fn extractive_answer_keeps_markdown_links() {
        let result = extractive_answer(
            "无关\n\n[核心观点](https://example.com)：Alpha 与 Beta 的区别。",
            "Alpha 是什么",
            8,
        );
        assert_eq!(result.get("status").and_then(|v| v.as_str()), Some("ok"));
        assert!(result
            .get("answer")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .contains("[核心观点]"));
    }
}
