use std::collections::{HashMap, HashSet};
use std::net::SocketAddr;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Duration;

use axum::extract::{Path as AxumPath, Query, State};
use axum::http::StatusCode;
use axum::response::{Html, IntoResponse};
use axum::routing::{get, post};
use axum::{Json, Router};
use chrono::{DateTime, Utc};
use reqwest::Client;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use tokio::sync::Mutex;

const DEFAULT_API_URL: &str = "https://newsnow.busiyi.world/api/s";
const MAX_ITEMS_PER_SOURCE: usize = 30;
const MAX_TOTAL_ITEMS: usize = 1600;
const MAX_ACTIVE_AGE_HOURS: i64 = 72;
const DAILY_HISTORY_LIMIT: usize = 120;

#[derive(Clone)]
struct AppState {
    http: Client,
    state_file: PathBuf,
    history_dir: PathBuf,
    api_url: String,
    sources: Vec<TrendSource>,
    refresh_lock: Arc<Mutex<()>>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct TrendSource {
    id: String,
    name: String,
    weight: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct TrendItem {
    id: String,
    source_id: String,
    source_name: String,
    rank: usize,
    title: String,
    #[serde(default)]
    summary: String,
    url: String,
    mobile_url: String,
    first_seen_at: DateTime<Utc>,
    last_seen_at: DateTime<Utc>,
    seen_count: u32,
    best_rank: usize,
    score: f64,
    tags: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
struct TrendStore {
    ok: bool,
    updated_at: Option<DateTime<Utc>>,
    refresh_count: u64,
    sources: Vec<TrendSource>,
    items: Vec<TrendItem>,
    last_errors: Vec<String>,
}

#[derive(Debug, Deserialize)]
struct LatestQuery {
    limit: Option<usize>,
    source: Option<String>,
    q: Option<String>,
}

#[derive(Debug, Deserialize)]
struct SearchQuery {
    q: String,
    limit: Option<usize>,
}

#[derive(Debug, Deserialize)]
struct HistoryQuery {
    date: Option<String>,
    limit: Option<usize>,
}

#[derive(Debug, Deserialize)]
struct DailyReportQuery {
    limit: Option<usize>,
}

#[derive(Debug, Deserialize)]
struct NewsNowResponse {
    status: Option<String>,
    items: Option<Vec<NewsNowItem>>,
}

#[derive(Debug, Deserialize)]
struct NewsNowItem {
    title: Option<Value>,
    url: Option<String>,
    #[serde(rename = "mobileUrl")]
    mobile_url: Option<String>,
    extra: Option<Value>,
    desc: Option<Value>,
    summary: Option<Value>,
}

#[derive(Debug, Deserialize)]
struct McpCallRequest {
    tool: Option<String>,
    name: Option<String>,
    arguments: Option<Value>,
}

#[derive(Debug, Deserialize)]
struct JsonRpcRequest {
    jsonrpc: Option<String>,
    id: Option<Value>,
    method: String,
    params: Option<Value>,
}

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt().with_target(false).init();

    let port: u16 = std::env::var("TREND_SIDECAR_PORT")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(8095);
    let state_file = std::env::var("TREND_STATE_FILE")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("/root/.nanobot/data/trend-sidecar/state.json"));
    if let Some(parent) = state_file.parent() {
        let _ = tokio::fs::create_dir_all(parent).await;
    }
    let history_dir = std::env::var("TREND_HISTORY_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("/root/.nanobot/data/trend-sidecar/history"));
    let _ = tokio::fs::create_dir_all(&history_dir).await;
    let api_url =
        std::env::var("TREND_NEWSNOW_API_URL").unwrap_or_else(|_| DEFAULT_API_URL.to_string());
    let refresh_secs: u64 = std::env::var("TREND_REFRESH_SECS")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(1800);

    let http = Client::builder()
        .timeout(Duration::from_secs(14))
        .user_agent(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/121 Safari/537.36",
        )
        .build()
        .expect("build reqwest client");

    let state = AppState {
        http,
        state_file,
        history_dir,
        api_url,
        sources: default_sources(),
        refresh_lock: Arc::new(Mutex::new(())),
    };

    let init_state = state.clone();
    tokio::spawn(async move {
        let _ = refresh_store(&init_state).await;
        let mut tick = tokio::time::interval(Duration::from_secs(refresh_secs.max(300)));
        loop {
            tick.tick().await;
            let _ = refresh_store(&init_state).await;
        }
    });

    let app = Router::new()
        .route("/", get(index))
        .route("/trends", get(index))
        .route("/trends/", get(index))
        .route("/health", get(health))
        .route("/mcp", get(mcp_info).post(mcp_jsonrpc))
        .route("/trends/mcp", get(mcp_info).post(mcp_jsonrpc))
        .route("/api/status", get(api_status))
        .route("/api/mcp/tools", get(api_mcp_tools))
        .route("/api/mcp/call", post(api_mcp_call))
        .route("/trends/api/mcp/tools", get(api_mcp_tools))
        .route("/trends/api/mcp/call", post(api_mcp_call))
        .route("/api/trends/status", get(api_status))
        .route("/api/trends/sources", get(api_sources))
        .route("/api/trends/latest", get(api_latest))
        .route("/api/trends/search", get(api_search))
        .route("/api/trends/brief", get(api_brief))
        .route("/api/trends/daily-report", get(api_daily_report))
        .route("/api/trends/history", get(api_history))
        .route("/api/trends/topic/{keyword}", get(api_topic))
        .route("/api/trends/refresh", post(api_refresh))
        .route("/trends/api/trends/status", get(api_status))
        .route("/trends/api/trends/sources", get(api_sources))
        .route("/trends/api/trends/latest", get(api_latest))
        .route("/trends/api/trends/search", get(api_search))
        .route("/trends/api/trends/brief", get(api_brief))
        .route("/trends/api/trends/daily-report", get(api_daily_report))
        .route("/trends/api/trends/history", get(api_history))
        .route("/trends/api/trends/topic/{keyword}", get(api_topic))
        .route("/trends/api/trends/refresh", post(api_refresh))
        .with_state(state);

    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    tracing::info!("trend-sidecar-rs listening on http://{}", addr);
    let listener = tokio::net::TcpListener::bind(addr)
        .await
        .expect("bind failed");
    axum::serve(listener, app).await.expect("server failed");
}

fn default_sources() -> Vec<TrendSource> {
    vec![
        source("weibo", "微博", 1.20),
        source("zhihu", "知乎", 1.05),
        source("bilibili", "B站", 1.00),
        source("baidu", "百度热搜", 1.00),
        source("cls", "财联社", 1.10),
        source("wallstreetcn", "华尔街见闻", 1.05),
        source("toutiao", "今日头条", 0.95),
        source("douyin", "抖音", 0.95),
        source("36kr", "36氪", 0.90),
        source("sspai", "少数派", 0.82),
    ]
}

fn source(id: &str, name: &str, weight: f64) -> TrendSource {
    TrendSource {
        id: id.to_string(),
        name: name.to_string(),
        weight,
    }
}

async fn health() -> impl IntoResponse {
    Json(json!({"ok": true, "service": "trend-sidecar-rs", "time": Utc::now().to_rfc3339()}))
}

async fn index() -> Html<&'static str> {
    Html(INDEX_HTML)
}

async fn mcp_info() -> impl IntoResponse {
    Json(json!({
        "ok": true,
        "name": "nanobot-trend-radar",
        "description": "TrendRadar-lite data and MCP-style tools backed by local cached hot news.",
        "transport": "minimal-jsonrpc-http",
        "mcp_endpoint": "/trends/mcp",
        "tools_endpoint": "/trends/api/mcp/tools",
        "call_endpoint": "/trends/api/mcp/call",
        "tools": tool_specs(),
    }))
}

async fn api_status(State(state): State<AppState>) -> impl IntoResponse {
    Json(status_payload(&state).await)
}

async fn api_sources(State(state): State<AppState>) -> impl IntoResponse {
    Json(json!({"ok": true, "items": state.sources}))
}

async fn api_latest(
    State(state): State<AppState>,
    Query(q): Query<LatestQuery>,
) -> impl IntoResponse {
    let store = load_store(&state).await;
    let mut items = store.items;
    if let Some(source) = q.source.as_deref().filter(|v| !v.trim().is_empty()) {
        items.retain(|item| item.source_id == source || item.source_name.contains(source));
    }
    if let Some(keyword) = q.q.as_deref().filter(|v| !v.trim().is_empty()) {
        items = filter_items(items, keyword);
    }
    sort_items(&mut items);
    let limit = q.limit.unwrap_or(50).clamp(1, 200);
    items.truncate(limit);
    Json(json!({"ok": true, "items": items, "updated_at": store.updated_at}))
}

async fn api_search(
    State(state): State<AppState>,
    Query(q): Query<SearchQuery>,
) -> impl IntoResponse {
    let store = load_store(&state).await;
    let mut items = filter_items(store.items, &q.q);
    sort_items(&mut items);
    let limit = q.limit.unwrap_or(50).clamp(1, 200);
    items.truncate(limit);
    Json(json!({"ok": true, "query": q.q, "items": items, "updated_at": store.updated_at}))
}

async fn api_brief(State(state): State<AppState>) -> impl IntoResponse {
    let store = load_store(&state).await;
    Json(build_brief(&store))
}

async fn api_daily_report(
    State(state): State<AppState>,
    Query(q): Query<DailyReportQuery>,
) -> impl IntoResponse {
    let store = load_store(&state).await;
    Json(build_daily_report(
        &store,
        q.limit.unwrap_or(8).clamp(3, 15),
    ))
}

async fn api_history(
    State(state): State<AppState>,
    Query(q): Query<HistoryQuery>,
) -> impl IntoResponse {
    Json(history_payload(&state, q.date, q.limit.unwrap_or(30).clamp(5, 120)).await)
}

async fn api_topic(
    State(state): State<AppState>,
    AxumPath(keyword): AxumPath<String>,
) -> impl IntoResponse {
    let store = load_store(&state).await;
    Json(topic_payload(&store, &keyword))
}

async fn api_refresh(State(state): State<AppState>) -> impl IntoResponse {
    match refresh_store(&state).await {
        Ok(store) => Json(
            json!({"ok": true, "updated_at": store.updated_at, "items": store.items.len(), "errors": store.last_errors}),
        ),
        Err(err) => Json(json!({"ok": false, "error": err})),
    }
}

async fn api_mcp_tools() -> impl IntoResponse {
    Json(json!({"ok": true, "tools": tool_specs()}))
}

async fn api_mcp_call(
    State(state): State<AppState>,
    Json(req): Json<McpCallRequest>,
) -> impl IntoResponse {
    let name = req.tool.or(req.name).unwrap_or_default();
    let args = req.arguments.unwrap_or_else(|| json!({}));
    Json(call_tool(&state, &name, args).await)
}

async fn mcp_jsonrpc(
    State(state): State<AppState>,
    Json(req): Json<JsonRpcRequest>,
) -> impl IntoResponse {
    let id = req.id.clone().unwrap_or(Value::Null);
    let result = match req.method.as_str() {
        "initialize" => json!({
            "protocolVersion": "2024-11-05",
            "serverInfo": {"name": "nanobot-trend-radar", "version": "0.1.0"},
            "capabilities": {"tools": {}}
        }),
        "tools/list" => json!({"tools": tool_specs()}),
        "tools/call" => {
            let params = req.params.unwrap_or_else(|| json!({}));
            let name = params
                .get("name")
                .and_then(Value::as_str)
                .unwrap_or_default();
            let args = params
                .get("arguments")
                .cloned()
                .unwrap_or_else(|| json!({}));
            let value = call_tool(&state, name, args).await;
            json!({"content": [{"type": "text", "text": serde_json::to_string_pretty(&value).unwrap_or_else(|_| value.to_string())}]})
        }
        _ => {
            return (
                StatusCode::BAD_REQUEST,
                Json(json!({"jsonrpc": req.jsonrpc.unwrap_or_else(|| "2.0".into()), "id": id, "error": {"code": -32601, "message": "method not found"}})),
            )
                .into_response();
        }
    };
    Json(
        json!({"jsonrpc": req.jsonrpc.unwrap_or_else(|| "2.0".into()), "id": id, "result": result}),
    )
    .into_response()
}

async fn call_tool(state: &AppState, name: &str, args: Value) -> Value {
    let store = load_store(state).await;
    match name {
        "get_latest_news" => {
            let limit = args.get("limit").and_then(Value::as_u64).unwrap_or(30) as usize;
            let source = args.get("source").and_then(Value::as_str).unwrap_or("");
            let mut items = store.items;
            if !source.is_empty() {
                items.retain(|x| x.source_id == source || x.source_name.contains(source));
            }
            sort_items(&mut items);
            items.truncate(limit.clamp(1, 100));
            json!({"ok": true, "items": items})
        }
        "search_news" => {
            let query = args
                .get("query")
                .or_else(|| args.get("q"))
                .and_then(Value::as_str)
                .unwrap_or("");
            let mut items = filter_items(store.items, query);
            sort_items(&mut items);
            items.truncate(100);
            json!({"ok": true, "query": query, "items": items})
        }
        "get_trending_topics" => build_brief(&store),
        "analyze_topic_trend" => {
            let keyword = args
                .get("keyword")
                .or_else(|| args.get("topic"))
                .and_then(Value::as_str)
                .unwrap_or("");
            topic_payload(&store, keyword)
        }
        "generate_summary_report" => build_report(&store),
        "get_system_status" => status_payload(state).await,
        "list_trend_sources" => json!({"ok": true, "items": state.sources}),
        _ => json!({"ok": false, "error": format!("unknown tool: {}", name)}),
    }
}

fn tool_specs() -> Vec<Value> {
    vec![
        tool(
            "get_latest_news",
            "获取最新热榜新闻，可按 source 过滤。",
            json!({"type":"object","properties":{"limit":{"type":"integer"},"source":{"type":"string"}}}),
        ),
        tool(
            "search_news",
            "在本地已缓存的热榜新闻中搜索关键词。",
            json!({"type":"object","properties":{"query":{"type":"string"}},"required":["query"]}),
        ),
        tool(
            "get_trending_topics",
            "生成当前热点主题聚合与跨平台摘要。",
            json!({"type":"object","properties":{}}),
        ),
        tool(
            "analyze_topic_trend",
            "分析某个关键词/话题的跨平台出现次数、最佳排名和样本新闻。",
            json!({"type":"object","properties":{"keyword":{"type":"string"}},"required":["keyword"]}),
        ),
        tool(
            "generate_summary_report",
            "生成适合 Nanobot/LLM 继续分析的结构化热点简报。",
            json!({"type":"object","properties":{}}),
        ),
        tool(
            "get_system_status",
            "查看 trend sidecar 数据状态、刷新时间和错误。",
            json!({"type":"object","properties":{}}),
        ),
        tool(
            "list_trend_sources",
            "列出已启用热榜来源。",
            json!({"type":"object","properties":{}}),
        ),
    ]
}

fn tool(name: &str, description: &str, input_schema: Value) -> Value {
    json!({"name": name, "description": description, "inputSchema": input_schema})
}

async fn status_payload(state: &AppState) -> Value {
    let store = load_store(state).await;
    json!({
        "ok": store.ok,
        "updated_at": store.updated_at,
        "refresh_count": store.refresh_count,
        "sources": store.sources,
        "items_count": store.items.len(),
        "last_errors": store.last_errors,
        "mcp": {"endpoint": "/trends/mcp", "tools": tool_specs().len()},
    })
}

async fn refresh_store(state: &AppState) -> Result<TrendStore, String> {
    let _guard = state.refresh_lock.lock().await;
    let now = Utc::now();
    let old = load_store(state).await;
    let mut by_id: HashMap<String, TrendItem> = old
        .items
        .into_iter()
        .map(|item| (item.id.clone(), item))
        .collect();
    let mut errors = Vec::new();

    for source in &state.sources {
        match fetch_source(state, source).await {
            Ok(items) => {
                for (idx, raw) in items.into_iter().take(MAX_ITEMS_PER_SOURCE).enumerate() {
                    let title = value_to_title(raw.title.clone().unwrap_or(Value::Null));
                    if title.trim().is_empty() {
                        continue;
                    }
                    let rank = idx + 1;
                    let summary = news_summary(&raw, &title);
                    let url = raw.url.unwrap_or_default();
                    let mobile_url = raw.mobile_url.unwrap_or_default();
                    let id = stable_id(&source.id, &title);
                    let score = score_item(source.weight, rank, &title);
                    let tags = classify_tags(&title);
                    by_id
                        .entry(id.clone())
                        .and_modify(|item| {
                            item.rank = rank;
                            item.last_seen_at = now;
                            item.seen_count = item.seen_count.saturating_add(1);
                            item.best_rank = item.best_rank.min(rank);
                            item.score = score.max(item.score * 0.96);
                            item.summary = summary.clone();
                            if !url.is_empty() {
                                item.url = url.clone();
                            }
                            if !mobile_url.is_empty() {
                                item.mobile_url = mobile_url.clone();
                            }
                            item.tags = merge_tags(&item.tags, &tags);
                        })
                        .or_insert(TrendItem {
                            id,
                            source_id: source.id.clone(),
                            source_name: source.name.clone(),
                            rank,
                            title,
                            summary,
                            url,
                            mobile_url,
                            first_seen_at: now,
                            last_seen_at: now,
                            seen_count: 1,
                            best_rank: rank,
                            score,
                            tags,
                        });
                }
            }
            Err(err) => errors.push(format!("{}: {}", source.id, err)),
        }
        tokio::time::sleep(Duration::from_millis(120)).await;
    }

    let mut items: Vec<TrendItem> = by_id.into_values().collect();
    items.retain(|item| {
        now.signed_duration_since(item.last_seen_at).num_hours() <= MAX_ACTIVE_AGE_HOURS
    });
    sort_items(&mut items);
    items.truncate(MAX_TOTAL_ITEMS);

    let store = TrendStore {
        ok: errors.len() < state.sources.len(),
        updated_at: Some(now),
        refresh_count: old.refresh_count.saturating_add(1),
        sources: state.sources.clone(),
        items,
        last_errors: errors,
    };
    save_store(state, &store).await?;
    let _ = save_daily_history(state, &store).await;
    Ok(store)
}

async fn fetch_source(state: &AppState, source: &TrendSource) -> Result<Vec<NewsNowItem>, String> {
    let url = format!("{}?id={}&latest", state.api_url, source.id);
    let resp = state
        .http
        .get(url)
        .header("Accept", "application/json, text/plain, */*")
        .header("Accept-Language", "zh-CN,zh;q=0.9,en;q=0.8")
        .send()
        .await
        .map_err(|e| e.to_string())?;
    if !resp.status().is_success() {
        return Err(format!("http {}", resp.status().as_u16()));
    }
    let payload: NewsNowResponse = resp.json().await.map_err(|e| e.to_string())?;
    let status = payload.status.unwrap_or_else(|| "unknown".into());
    if status != "success" && status != "cache" {
        return Err(format!("bad status {}", status));
    }
    Ok(payload.items.unwrap_or_default())
}

async fn load_store(state: &AppState) -> TrendStore {
    match tokio::fs::read_to_string(&state.state_file).await {
        Ok(text) => serde_json::from_str(&text).unwrap_or_else(|_| empty_store(&state.sources)),
        Err(_) => empty_store(&state.sources),
    }
}

fn empty_store(sources: &[TrendSource]) -> TrendStore {
    TrendStore {
        ok: false,
        updated_at: None,
        refresh_count: 0,
        sources: sources.to_vec(),
        items: vec![],
        last_errors: vec![],
    }
}

async fn save_store(state: &AppState, store: &TrendStore) -> Result<(), String> {
    if let Some(parent) = state.state_file.parent() {
        tokio::fs::create_dir_all(parent)
            .await
            .map_err(|e| e.to_string())?;
    }
    let tmp = state.state_file.with_extension("json.tmp");
    let text = serde_json::to_string_pretty(store).map_err(|e| e.to_string())?;
    tokio::fs::write(&tmp, text)
        .await
        .map_err(|e| e.to_string())?;
    tokio::fs::rename(&tmp, &state.state_file)
        .await
        .map_err(|e| e.to_string())?;
    Ok(())
}

async fn save_daily_history(state: &AppState, store: &TrendStore) -> Result<(), String> {
    tokio::fs::create_dir_all(&state.history_dir)
        .await
        .map_err(|e| e.to_string())?;
    let date = shanghai_date(store.updated_at.unwrap_or_else(Utc::now));
    let path = state.history_dir.join(format!("{date}.json"));
    let mut items = recent_items(&store.items);
    sort_items(&mut items);
    items.truncate(DAILY_HISTORY_LIMIT);
    let payload = json!({
        "ok": true,
        "date": date,
        "updated_at": store.updated_at,
        "items": items,
        "source_errors": store.last_errors,
    });
    let tmp = path.with_extension("json.tmp");
    let text = serde_json::to_string_pretty(&payload).map_err(|e| e.to_string())?;
    tokio::fs::write(&tmp, text)
        .await
        .map_err(|e| e.to_string())?;
    tokio::fs::rename(&tmp, &path)
        .await
        .map_err(|e| e.to_string())?;
    Ok(())
}

async fn history_payload(state: &AppState, date: Option<String>, limit: usize) -> Value {
    let days = list_history_days(&state.history_dir).await;
    let selected = date
        .filter(|d| valid_history_date(d))
        .or_else(|| days.first().cloned());
    let Some(selected) = selected else {
        return json!({"ok": true, "days": days, "date": null, "items": []});
    };
    let path = state.history_dir.join(format!("{selected}.json"));
    match tokio::fs::read_to_string(&path).await {
        Ok(text) => match serde_json::from_str::<Value>(&text) {
            Ok(mut value) => {
                if let Some(items) = value.get_mut("items").and_then(Value::as_array_mut) {
                    items.truncate(limit);
                }
                value["days"] = json!(days);
                value
            }
            Err(err) => {
                json!({"ok": false, "days": days, "date": selected, "error": err.to_string()})
            }
        },
        Err(err) => json!({"ok": false, "days": days, "date": selected, "error": err.to_string()}),
    }
}

async fn list_history_days(dir: &Path) -> Vec<String> {
    let mut days = Vec::new();
    let Ok(mut entries) = tokio::fs::read_dir(dir).await else {
        return days;
    };
    while let Ok(Some(entry)) = entries.next_entry().await {
        let name = entry.file_name().to_string_lossy().to_string();
        if let Some(day) = name.strip_suffix(".json") {
            if valid_history_date(day) {
                days.push(day.to_string());
            }
        }
    }
    days.sort_by(|a, b| b.cmp(a));
    days.truncate(60);
    days
}

fn valid_history_date(date: &str) -> bool {
    let b = date.as_bytes();
    b.len() == 10
        && b[4] == b'-'
        && b[7] == b'-'
        && b.iter()
            .enumerate()
            .all(|(i, c)| i == 4 || i == 7 || c.is_ascii_digit())
}

fn build_brief(store: &TrendStore) -> Value {
    let mut items = recent_items(&store.items);
    sort_items(&mut items);
    let top_items = diverse_items(&items, 20);
    let mut tag_counts: HashMap<String, usize> = HashMap::new();
    let mut source_counts: HashMap<String, usize> = HashMap::new();
    for item in &items {
        *source_counts.entry(item.source_name.clone()).or_default() += 1;
        for tag in &item.tags {
            *tag_counts.entry(tag.clone()).or_default() += 1;
        }
    }
    let mut topics: Vec<_> = tag_counts.into_iter().collect();
    topics.sort_by(|a, b| b.1.cmp(&a.1));
    let mut sources: Vec<_> = source_counts.into_iter().collect();
    sources.sort_by(|a, b| b.1.cmp(&a.1));
    let signals = weak_signals(&items);
    json!({
        "ok": store.ok,
        "updated_at": store.updated_at,
        "items_count": store.items.len(),
        "top_items": top_items,
        "topics": topics.into_iter().take(12).map(|(name,count)| json!({"name": name, "count": count})).collect::<Vec<_>>(),
        "source_counts": sources.into_iter().map(|(name,count)| json!({"name": name, "count": count})).collect::<Vec<_>>(),
        "weak_signals": signals,
        "daily_report_markdown": build_daily_report(store, 8).get("markdown").cloned().unwrap_or(Value::Null),
        "analysis_hint": "可交给 Nanobot/LLM 继续分析：核心热点态势、舆论争议、异动弱信号、策略建议。"
    })
}

fn topic_payload(store: &TrendStore, keyword: &str) -> Value {
    let mut matches = filter_items(store.items.clone(), keyword);
    sort_items(&mut matches);
    let platforms: HashSet<_> = matches
        .iter()
        .map(|item| item.source_name.clone())
        .collect();
    let best_rank = matches.iter().map(|item| item.best_rank).min().unwrap_or(0);
    let total_seen: u32 = matches.iter().map(|item| item.seen_count).sum();
    let first_seen = matches.iter().map(|item| item.first_seen_at).min();
    let last_seen = matches.iter().map(|item| item.last_seen_at).max();
    json!({
        "ok": true,
        "keyword": keyword,
        "count": matches.len(),
        "platforms": platforms.into_iter().collect::<Vec<_>>(),
        "best_rank": best_rank,
        "total_seen": total_seen,
        "first_seen_at": first_seen,
        "last_seen_at": last_seen,
        "items": matches.into_iter().take(50).collect::<Vec<_>>(),
        "analysis": topic_analysis_text(keyword, best_rank, total_seen),
    })
}

fn build_daily_report(store: &TrendStore, limit: usize) -> Value {
    let mut items = recent_items(&store.items);
    sort_items(&mut items);
    let updated = store
        .updated_at
        .map(|dt| shanghai_time_text(dt))
        .unwrap_or_else(|| "未知".to_string());
    let mut lines = Vec::new();
    lines.push(format!("📰 Trend Radar 每日新闻简报（{}）", updated));
    lines.push(format!(
        "数据：{} 条缓存，{} 个源异常",
        store.items.len(),
        store.last_errors.len()
    ));
    lines.push("".to_string());
    let report_pool: Vec<_> = items
        .iter()
        .filter(|item| is_report_candidate(item))
        .cloned()
        .collect();
    let report_items = if report_pool.len() >= limit {
        diverse_items(&report_pool, limit)
    } else {
        diverse_items(&items, limit)
    };
    for (idx, item) in report_items.iter().enumerate() {
        lines.push(format!("{}. {}", idx + 1, item.title));
        lines.push(format!("   简要：{}", readable_summary(item)));
        let link = if item.url.is_empty() {
            item.mobile_url.as_str()
        } else {
            item.url.as_str()
        };
        if !link.is_empty() {
            lines.push(format!("   原文：{}", link));
        }
        lines.push("".to_string());
    }
    lines.push("看板：http://150.158.121.88:8093/trends/".to_string());
    json!({
        "ok": true,
        "updated_at": store.updated_at,
        "items": report_items,
        "markdown": lines.join("\n"),
        "last_errors": store.last_errors,
    })
}

fn build_report(store: &TrendStore) -> Value {
    let brief = build_brief(store);
    let mut lines = Vec::new();
    lines.push(format!(
        "热点雷达简报：{} 条缓存，更新时间 {:?}",
        store.items.len(),
        store.updated_at
    ));
    if let Some(items) = brief.get("top_items").and_then(Value::as_array) {
        lines.push("核心热点：".into());
        for item in items.iter().take(8) {
            lines.push(format!(
                "- [{}] {}",
                item.get("source_name")
                    .and_then(Value::as_str)
                    .unwrap_or("-"),
                item.get("title").and_then(Value::as_str).unwrap_or("-")
            ));
        }
    }
    json!({"ok": true, "brief": brief, "markdown": lines.join("\n")})
}

fn weak_signals(items: &[TrendItem]) -> Vec<Value> {
    let mut fresh: Vec<_> = items
        .iter()
        .filter(|item| item.seen_count <= 2 && item.best_rank <= 8)
        .cloned()
        .collect();
    sort_items(&mut fresh);
    fresh
        .into_iter()
        .take(8)
        .map(|item| json!({"title": item.title, "source": item.source_name, "rank": item.rank, "score": item.score, "url": item.url}))
        .collect()
}

fn topic_analysis_text(keyword: &str, best_rank: usize, total_seen: u32) -> String {
    if best_rank > 0 && best_rank <= 5 && total_seen >= 3 {
        format!("{} 已进入前排并多次出现，属于需要关注的强信号。", keyword)
    } else if total_seen >= 3 {
        format!("{} 有持续出现迹象，但排名未必靠前，适合继续观察。", keyword)
    } else if best_rank > 0 {
        format!("{} 有命中样本，但目前更像零散热点。", keyword)
    } else {
        format!("{} 暂无本地缓存命中。", keyword)
    }
}

fn filter_items(items: Vec<TrendItem>, query: &str) -> Vec<TrendItem> {
    let q = query.trim().to_lowercase();
    if q.is_empty() {
        return items;
    }
    items
        .into_iter()
        .filter(|item| {
            item.title.to_lowercase().contains(&q)
                || item.source_name.to_lowercase().contains(&q)
                || item.tags.iter().any(|tag| tag.to_lowercase().contains(&q))
        })
        .collect()
}

fn sort_items(items: &mut [TrendItem]) {
    let now = Utc::now();
    items.sort_by(|a, b| {
        effective_score(b, now)
            .partial_cmp(&effective_score(a, now))
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| b.last_seen_at.cmp(&a.last_seen_at))
            .then_with(|| a.rank.cmp(&b.rank))
            .then_with(|| a.best_rank.cmp(&b.best_rank))
    });
}

fn diverse_items(items: &[TrendItem], limit: usize) -> Vec<TrendItem> {
    let mut out = Vec::new();
    let mut by_source: HashMap<String, usize> = HashMap::new();
    for item in items {
        let count = by_source.get(&item.source_id).copied().unwrap_or(0);
        if count >= 2 {
            continue;
        }
        out.push(item.clone());
        by_source.insert(item.source_id.clone(), count + 1);
        if out.len() >= limit {
            return out;
        }
    }
    for item in items {
        if out.iter().any(|x| x.id == item.id) {
            continue;
        }
        out.push(item.clone());
        if out.len() >= limit {
            break;
        }
    }
    out
}

fn recent_items(items: &[TrendItem]) -> Vec<TrendItem> {
    let now = Utc::now();
    let mut recent: Vec<_> = items
        .iter()
        .filter(|item| now.signed_duration_since(item.last_seen_at).num_hours() <= 24)
        .cloned()
        .collect();
    if recent.len() < 12 {
        recent = items
            .iter()
            .filter(|item| {
                now.signed_duration_since(item.last_seen_at).num_hours() <= MAX_ACTIVE_AGE_HOURS
            })
            .cloned()
            .collect();
    }
    if recent.is_empty() {
        recent = items.to_vec();
    }
    recent
}

fn effective_score(item: &TrendItem, now: DateTime<Utc>) -> f64 {
    let age_hours = now
        .signed_duration_since(item.last_seen_at)
        .num_minutes()
        .max(0) as f64
        / 60.0;
    let freshness = if age_hours <= 1.0 {
        1.35
    } else if age_hours <= 6.0 {
        1.15
    } else if age_hours <= 24.0 {
        0.85
    } else if age_hours <= 72.0 {
        0.32
    } else {
        0.05
    };
    let rank_boost = (40.0 - item.rank.min(40) as f64).max(0.0) * 0.8;
    (item.score + rank_boost + item.seen_count.min(4) as f64 * 2.0) * freshness
}

fn value_to_title(value: Value) -> String {
    match value {
        Value::String(s) => s.trim().to_string(),
        Value::Number(n) => n.to_string(),
        other => other.to_string(),
    }
}

fn news_summary(raw: &NewsNowItem, title: &str) -> String {
    let mut parts = Vec::new();
    for value in [&raw.summary, &raw.desc, &raw.extra] {
        collect_summary_parts(value.as_ref(), &mut parts);
    }
    parts
        .into_iter()
        .map(|s| compact_ws(&s))
        .filter(|s| !s.is_empty() && s != title)
        .next()
        .map(|s| short_chars(&s, 120))
        .unwrap_or_default()
}

fn collect_summary_parts(value: Option<&Value>, out: &mut Vec<String>) {
    let Some(value) = value else {
        return;
    };
    match value {
        Value::String(s) => out.push(s.clone()),
        Value::Object(map) => {
            for key in ["summary", "desc", "description", "info", "hover"] {
                if let Some(v) = map.get(key) {
                    collect_summary_parts(Some(v), out);
                }
            }
        }
        Value::Array(arr) => {
            for v in arr.iter().take(3) {
                collect_summary_parts(Some(v), out);
            }
        }
        Value::Number(_) => {}
        _ => {}
    }
}

fn compact_ws(text: &str) -> String {
    text.split_whitespace().collect::<Vec<_>>().join(" ")
}

fn short_chars(text: &str, limit: usize) -> String {
    let mut out = String::new();
    for (idx, ch) in text.chars().enumerate() {
        if idx >= limit.saturating_sub(1) {
            out.push('…');
            return out;
        }
        out.push(ch);
    }
    out
}

fn is_report_candidate(item: &TrendItem) -> bool {
    let title_len = item.title.chars().filter(|c| !c.is_whitespace()).count();
    if title_len < 8 {
        return false;
    }
    if item.tags.iter().any(|tag| tag == "娱乐") {
        return false;
    }
    true
}

fn readable_summary(item: &TrendItem) -> String {
    if !item.summary.trim().is_empty() {
        return short_chars(item.summary.trim(), 140);
    }
    let tags = if item.tags.is_empty() {
        "综合".to_string()
    } else {
        item.tags.join(" / ")
    };
    format!(
        "来自{}热榜第 #{}，标签：{}。{}",
        item.source_name,
        item.rank,
        tags,
        short_chars(&item.title, 80)
    )
}

fn shanghai_date(now: DateTime<Utc>) -> String {
    (now + chrono::Duration::hours(8))
        .format("%Y-%m-%d")
        .to_string()
}

fn shanghai_time_text(dt: DateTime<Utc>) -> String {
    (dt + chrono::Duration::hours(8))
        .format("%Y-%m-%d %H:%M")
        .to_string()
}

fn stable_id(source: &str, title: &str) -> String {
    let mut hash: u64 = 14695981039346656037;
    for b in format!("{}:{}", source, title).as_bytes() {
        hash ^= *b as u64;
        hash = hash.wrapping_mul(1099511628211);
    }
    format!("{}-{:016x}", source, hash)
}

fn score_item(weight: f64, rank: usize, title: &str) -> f64 {
    let rank_score = (40.0 - rank.min(40) as f64).max(1.0) * 2.0;
    let tag_bonus = classify_tags(title).len() as f64 * 4.0;
    (rank_score * weight + tag_bonus).round()
}

fn classify_tags(title: &str) -> Vec<String> {
    let rules: [(&str, &[&str]); 10] = [
        (
            "AI",
            &[
                "ai",
                "人工智能",
                "大模型",
                "openai",
                "chatgpt",
                "机器人",
                "芯片",
                "算力",
            ],
        ),
        (
            "财经",
            &[
                "a股",
                "港股",
                "美股",
                "基金",
                "降息",
                "央行",
                "财报",
                "成交额",
                "关税",
                "汇率",
            ],
        ),
        (
            "科技",
            &[
                "手机",
                "芯片",
                "新能源",
                "汽车",
                "特斯拉",
                "比亚迪",
                "华为",
                "苹果",
            ],
        ),
        (
            "国际",
            &[
                "美国",
                "欧洲",
                "日本",
                "韩国",
                "俄罗斯",
                "乌克兰",
                "中东",
                "土耳其",
            ],
        ),
        (
            "社会",
            &[
                "警方", "法院", "官方", "通报", "调查", "事故", "偷税", "网红",
            ],
        ),
        (
            "政策",
            &["国安", "监管", "政策", "发布", "部门", "税", "海关"],
        ),
        (
            "娱乐",
            &["明星", "电影", "综艺", "恋综", "花少", "演唱会", "粉丝"],
        ),
        ("体育", &["nba", "足球", "比赛", "冠军", "球队"]),
        ("健康", &["医院", "医生", "疾病", "药", "医保", "食品"]),
        ("教育", &["学校", "大学", "高考", "考研", "学生", "教师"]),
    ];
    let lower = title.to_lowercase();
    let mut tags = Vec::new();
    for (tag, needles) in rules {
        if needles
            .iter()
            .any(|needle| lower.contains(&needle.to_lowercase()))
        {
            tags.push(tag.to_string());
        }
    }
    if tags.is_empty() {
        tags.push("综合".into());
    }
    tags
}

fn merge_tags(a: &[String], b: &[String]) -> Vec<String> {
    let mut out = a.to_vec();
    for tag in b {
        if !out.contains(tag) {
            out.push(tag.clone());
        }
    }
    out
}

const INDEX_HTML: &str = r#"<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Trend Radar Lite</title>
<style>
:root{--bg:#f4f0e6;--panel:#fffaf0;--text:#1f211c;--muted:#69705f;--line:#ded5c3;--accent:#0f766e;--hot:#c2410c;--shadow:0 18px 55px rgba(68,52,30,.12)}[data-theme=dark]{--bg:#111815;--panel:#1d2620;--text:#edf6ec;--muted:#a7b4a5;--line:#354237;--accent:#5eead4;--hot:#fdba74;--shadow:0 20px 70px rgba(0,0,0,.3)}*{box-sizing:border-box}body{margin:0;background:radial-gradient(900px 500px at -10% -10%,rgba(15,118,110,.18),transparent 55%),linear-gradient(135deg,var(--bg),#e7efe2);color:var(--text);font-family:"Avenir Next","PingFang SC","Microsoft YaHei",sans-serif}[data-theme=dark] body{background:radial-gradient(900px 500px at -10% -10%,rgba(94,234,212,.12),transparent 55%),linear-gradient(135deg,#101815,#1b241f)}.wrap{max-width:1180px;margin:0 auto;padding:24px 14px 42px}.hero{display:flex;justify-content:space-between;gap:14px;align-items:flex-start;margin-bottom:14px}.title{font-family:Georgia,"Noto Serif SC",serif;font-size:42px;line-height:1;margin:0}.sub{color:var(--muted);line-height:1.7;margin:10px 0 0}.toolbar{display:flex;gap:8px;flex-wrap:wrap}.btn,button{border:1px solid var(--line);border-radius:999px;background:var(--panel);color:var(--text);padding:9px 13px;font-weight:900;box-shadow:var(--shadow);cursor:pointer;text-decoration:none}.grid{display:grid;grid-template-columns:repeat(12,1fr);gap:12px}.card{grid-column:span 4;background:var(--panel);border:1px solid var(--line);border-radius:22px;padding:16px;box-shadow:var(--shadow)}.card.wide{grid-column:span 8}.card.full{grid-column:1/-1}.k{color:var(--muted);font-size:12px}.v{font-size:28px;font-weight:950}.list{display:grid;gap:9px}.item{border:1px solid var(--line);border-radius:16px;padding:11px;background:rgba(255,255,255,.18)}.name{font-weight:950}.muted{color:var(--muted)}.mini{font-size:12px}.tag{display:inline-flex;border:1px solid var(--line);border-radius:999px;padding:3px 8px;margin:3px 4px 0 0;font-size:12px;color:var(--accent);font-weight:900}.hot{color:var(--hot)}a{color:var(--accent);font-weight:900;text-decoration:none}a:hover{text-decoration:underline}.table{width:100%;border-collapse:collapse}.table th,.table td{padding:8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}.table th{font-size:12px;color:var(--muted)}input,select{width:100%;border:1px solid var(--line);border-radius:14px;padding:10px;background:var(--panel);color:var(--text)}@media(max-width:860px){.hero{display:block}.toolbar{margin-top:12px}.card,.card.wide{grid-column:1/-1}.title{font-size:34px}}
</style>
</head>
<body>
<div class="wrap">
  <section class="hero"><div><h1 class="title">Trend Radar Lite</h1><p class="sub">自动收集全网热榜，沉淀本地缓存，再交给 Nanobot / MCP 工具做分析。现在是轻量第一版：热榜、搜索、话题分析、MCP 风格工具接口。</p></div><div class="toolbar"><button onclick="refreshNow()">手动刷新</button><button onclick="toggleTheme()">明暗</button><a class="btn" href="/">驾驶舱</a><a class="btn" href="/sidecars">服务矩阵</a></div></section>
  <section class="grid">
    <article class="card"><div class="k">缓存新闻</div><div class="v" id="count">-</div><div class="muted mini" id="updated">加载中...</div></article>
    <article class="card"><div class="k">数据源</div><div class="v" id="sources">-</div><div id="sourceTags"></div></article>
    <article class="card"><div class="k">MCP 工具</div><div class="v" id="tools">7</div><div class="muted mini">/trends/mcp · /trends/api/mcp/tools</div></article>
    <article class="card wide"><h2>核心热点</h2><div class="list" id="top"></div></article>
    <article class="card"><h2>热点主题</h2><div id="topics"></div></article>
    <article class="card full"><h2>历史热搜榜</h2><div class="toolbar" style="margin-bottom:10px"><select id="historyDay" onchange="loadHistory()"></select><a class="btn" href="/trends/api/trends/daily-report" target="_blank">每日简报 JSON</a></div><div class="list" id="historyList"><div class="muted">加载中...</div></div></article>
    <article class="card full"><h2>搜索与话题分析</h2><input id="q" placeholder="输入 AI、财经、某家公司或任意关键词，回车搜索" onkeydown="if(event.key==='Enter')search()" /><div id="searchResult" style="margin-top:12px"></div></article>
    <article class="card full"><h2>MCP / API</h2><table class="table"><tbody><tr><td>工具列表</td><td><a href="/trends/api/mcp/tools" target="_blank">/trends/api/mcp/tools</a></td></tr><tr><td>JSON-RPC MCP</td><td><a href="/trends/mcp" target="_blank">/trends/mcp</a></td></tr><tr><td>最新新闻</td><td><a href="/trends/api/trends/latest?limit=50" target="_blank">/trends/api/trends/latest?limit=50</a></td></tr><tr><td>简报数据</td><td><a href="/trends/api/trends/brief" target="_blank">/trends/api/trends/brief</a></td></tr><tr><td>历史热搜</td><td><a href="/trends/api/trends/history" target="_blank">/trends/api/trends/history</a></td></tr><tr><td>每日简报</td><td><a href="/trends/api/trends/daily-report" target="_blank">/trends/api/trends/daily-report</a></td></tr></tbody></table></article>
  </section>
</div>
<script>
const root=document.documentElement;if(localStorage.trendTheme==='dark')root.setAttribute('data-theme','dark');
const BASE=location.pathname.startsWith('/trends')?'/trends':'';
const API=BASE+'/api';
function toggleTheme(){const d=root.getAttribute('data-theme')==='dark';root.setAttribute('data-theme',d?'light':'dark');localStorage.trendTheme=d?'light':'dark'}
function esc(s){return String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]))}
function fmtTime(s){if(!s)return '-';try{return new Date(s).toLocaleString('zh-CN',{hour12:false,timeZone:'Asia/Shanghai'})}catch{return s}}
function itemHtml(x){const summary=x.summary?`<div class="muted" style="margin-top:5px">${esc(x.summary)}</div>`:'';return `<div class="item"><div class="name"><span class="hot">#${esc(x.rank)}</span> [${esc(x.source_name)}] <a href="${esc(x.url||x.mobile_url||'#')}" target="_blank" rel="noopener">${esc(x.title)}</a></div>${summary}<div class="muted mini">score ${esc(x.score)} · seen ${esc(x.seen_count)} · best #${esc(x.best_rank)} · ${esc((x.tags||[]).join(' / '))} · ${fmtTime(x.last_seen_at)}</div></div>`}
async function getJson(url,opt){const r=await fetch(url,{cache:'no-store',...(opt||{})});if(!r.ok)throw new Error(url+' '+r.status);return r.json()}
async function load(){const [status,brief]=await Promise.all([getJson(API+'/trends/status'),getJson(API+'/trends/brief')]);document.getElementById('count').textContent=status.items_count||0;const errs=status.last_errors||[];document.getElementById('updated').textContent='更新：'+fmtTime(status.updated_at)+(errs.length?` · 部分源异常 ${errs.length}`:' · 全部正常');document.getElementById('sources').textContent=(status.sources||[]).length;document.getElementById('sourceTags').innerHTML=(status.sources||[]).map(s=>`<span class="tag">${esc(s.name)}</span>`).join('');document.getElementById('tools').textContent=status.mcp?.tools||7;document.getElementById('top').innerHTML=(brief.top_items||[]).slice(0,12).map(itemHtml).join('')||'<div class="muted">暂无数据，点手动刷新。</div>';document.getElementById('topics').innerHTML=(brief.topics||[]).slice(0,12).map(t=>`<span class="tag" onclick="topic('${esc(t.name)}')">${esc(t.name)} ${esc(t.count)}</span>`).join('');await loadHistory()}
async function loadHistory(){try{const sel=document.getElementById('historyDay');const chosen=sel.value;const data=await getJson(API+'/trends/history?limit=20'+(chosen?'&date='+encodeURIComponent(chosen):''));const days=data.days||[];if(!sel.dataset.loaded||!chosen){sel.innerHTML=days.map(d=>`<option value="${esc(d)}">${esc(d)}</option>`).join('');sel.dataset.loaded='1';if(data.date)sel.value=data.date}document.getElementById('historyList').innerHTML=(data.items||[]).slice(0,20).map(itemHtml).join('')||'<div class="muted">暂无历史快照，等待下一次刷新。</div>'}catch(e){document.getElementById('historyList').innerHTML='<div class="muted">历史热搜读取失败：'+esc(e.message)+'</div>'}}
async function refreshNow(){document.getElementById('updated').textContent='刷新中...';await getJson(API+'/trends/refresh',{method:'POST'});await load()}
async function search(){const q=document.getElementById('q').value.trim();if(!q)return;const data=await getJson(API+'/trends/search?q='+encodeURIComponent(q)+'&limit=30');document.getElementById('searchResult').innerHTML=`<div class="muted mini">命中 ${data.items.length} 条</div><div class="list">${data.items.map(itemHtml).join('')}</div>`}
async function topic(q){document.getElementById('q').value=q;const data=await getJson(API+'/trends/topic/'+encodeURIComponent(q));document.getElementById('searchResult').innerHTML=`<div class="item"><div class="name">${esc(q)}：${esc(data.analysis)}</div><div class="muted mini">${esc(data.count)} 条 · 平台 ${esc((data.platforms||[]).join(' / '))} · 最佳排名 #${esc(data.best_rank||'-')}</div></div><div class="list">${(data.items||[]).map(itemHtml).join('')}</div>`}
load().catch(e=>document.getElementById('updated').textContent=e.message);setInterval(load,60000)
</script>
</body>
</html>"#;

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;

    fn item(
        id: &str,
        source_id: &str,
        source_name: &str,
        rank: usize,
        title: &str,
        tags: Vec<&str>,
        score: f64,
    ) -> TrendItem {
        let now = Utc.with_ymd_and_hms(2026, 5, 13, 8, 0, 0).unwrap();
        TrendItem {
            id: id.to_string(),
            source_id: source_id.to_string(),
            source_name: source_name.to_string(),
            rank,
            title: title.to_string(),
            summary: String::new(),
            url: format!("https://example.com/{id}"),
            mobile_url: String::new(),
            first_seen_at: now,
            last_seen_at: now,
            seen_count: 1,
            best_rank: rank,
            score,
            tags: tags.into_iter().map(str::to_string).collect(),
        }
    }

    #[test]
    fn classifies_ai_and_defaults_non_matching_titles() {
        assert!(classify_tags("chatgpt model release").contains(&"AI".to_string()));
        let tags = classify_tags("local topic");
        assert_eq!(tags.len(), 1);
        assert!(!tags.contains(&"AI".to_string()));
    }

    #[test]
    fn filter_items_matches_title_source_and_tags() {
        let items = vec![
            item(
                "1",
                "weibo",
                "weibo",
                1,
                "OpenAI new model",
                vec!["AI"],
                80.0,
            ),
            item("2", "cls", "cls", 2, "market close", vec!["finance"], 70.0),
        ];

        assert_eq!(filter_items(items.clone(), "openai").len(), 1);
        assert_eq!(filter_items(items.clone(), "cls").len(), 1);
        assert_eq!(filter_items(items, "finance").len(), 1);
    }

    #[test]
    fn diverse_items_caps_each_source_before_fill() {
        let items = vec![
            item("a1", "a", "A", 1, "topic one", vec!["AI"], 90.0),
            item("a2", "a", "A", 2, "topic two", vec!["AI"], 89.0),
            item("a3", "a", "A", 3, "topic three", vec!["AI"], 88.0),
            item("b1", "b", "B", 4, "topic four", vec!["finance"], 70.0),
        ];

        let selected = diverse_items(&items, 3);
        assert_eq!(selected.iter().filter(|x| x.source_id == "a").count(), 2);
        assert_eq!(selected.iter().filter(|x| x.source_id == "b").count(), 1);
    }

    #[test]
    fn report_candidate_filters_noise() {
        assert!(!is_report_candidate(&item(
            "1",
            "weibo",
            "weibo",
            1,
            "celebrity reality show gossip topic",
            vec!["\u{5a31}\u{4e50}"],
            80.0
        )));
        assert!(!is_report_candidate(&item(
            "2",
            "weibo",
            "weibo",
            1,
            "short",
            vec!["misc"],
            80.0
        )));
        assert!(is_report_candidate(&item(
            "3",
            "cls",
            "cls",
            1,
            "AI industry chain reports important progress",
            vec!["AI"],
            80.0
        )));
    }

    #[test]
    fn stable_id_is_deterministic_and_source_scoped() {
        assert_eq!(
            stable_id("weibo", "same title"),
            stable_id("weibo", "same title")
        );
        assert_ne!(
            stable_id("weibo", "same title"),
            stable_id("zhihu", "same title")
        );
    }
}
