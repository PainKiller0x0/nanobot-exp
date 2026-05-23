use std::{
    collections::{BTreeSet, HashMap},
    fs,
    net::SocketAddr,
    path::{Path, PathBuf},
    sync::Arc,
    time::{Duration, Instant},
};

use axum::{
    body::{Body, Bytes},
    extract::{Path as AxumPath, State},
    http::{header, HeaderMap, HeaderName, HeaderValue, Method, StatusCode, Uri},
    middleware,
    response::{Html, IntoResponse, Response},
    routing::{any, delete, get, post},
    Json, Router,
};
use chrono::{DateTime, FixedOffset, Utc};
use reqwest::Client;
use serde::{Deserialize, Serialize};
use tokio::process::Command;
use tokio::sync::Mutex;

mod lof_domain;
mod pages;
mod reverse_proxy;
mod sidecar_manager;
mod system_metrics;

use lof_domain::{is_trading_session, run_native_report, BoardData};
use pages::{
    common_js, dashboard, inbox_page, index, personal_ops_page, shell_js, sidecars_page,
    workbench_page,
};
use reverse_proxy::reverse_proxy;
use sidecar_manager::ManagedSidecarStatus;
use system_metrics::{
    json_f64, json_u64, read_cpu_info, read_disk_root, read_loadavg, read_meminfo_mb,
};

const X_ROBOTS_TAG: HeaderName = HeaderName::from_static("x-robots-tag");
const NOINDEX_HEADER_VALUE: HeaderValue =
    HeaderValue::from_static("noindex, nofollow, noarchive, nosnippet");
const ROBOTS_TXT: &str = "User-agent: *\nDisallow: /\n\n# 8093 is a private Nanobot dashboard. Every response carries X-Robots-Tag: noindex.\n";

#[derive(Debug, Clone, Serialize, Deserialize)]
struct SidecarStats {
    total_runs: u64,
    success_runs: u64,
    timeout_runs: u64,
    error_runs: u64,
}

impl Default for SidecarStats {
    fn default() -> Self {
        Self {
            total_runs: 0,
            success_runs: 0,
            timeout_runs: 0,
            error_runs: 0,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct LastRun {
    tag: String,
    started_at: DateTime<Utc>,
    finished_at: DateTime<Utc>,
    duration_ms: u128,
    status: String,
    report: String,
    error: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
struct SidecarState {
    stats: SidecarStats,
    last_run: Option<LastRun>,
    last_board: Option<BoardData>,
}

#[derive(Clone)]
struct AppState {
    script_dir: PathBuf,
    state_file: PathBuf,
    dashboard_history_file: PathBuf,
    auto_compact_events_file: PathBuf,
    inbox_dir: PathBuf,
    timeout_secs: u64,
    run_lock: Arc<Mutex<()>>,
    http: Client,
}

#[derive(Debug, Deserialize)]
struct RunRequest {
    tag: Option<String>,
}

#[derive(Debug, Deserialize)]
struct ObpLoginRequest {
    username: String,
    password: String,
}

#[derive(Debug, Deserialize)]
struct ObpPasswordRequest {
    username: String,
    password: String,
}

#[derive(Debug, Deserialize)]
struct RenderTextRequest {
    url: String,
    token: Option<String>,
    limit: Option<usize>,
}

#[derive(Debug, Deserialize)]
struct InboxRatingRequest {
    score: i64,
    note: Option<String>,
}

#[derive(Debug, Serialize)]
struct RunResponse {
    ok: bool,
    status: String,
    tag: String,
    duration_ms: u128,
    report: String,
    error: Option<String>,
}

#[derive(Debug, Serialize)]
struct TriggerResponse {
    queued: bool,
    tag: String,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(default)]
struct CapabilityCommand {
    label: String,
    command: String,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(default)]
struct Capability {
    id: String,
    name: String,
    description: String,
    category: String,
    kind: String,
    service_id: Option<String>,
    entry_url: Option<String>,
    enabled: bool,
    trigger_phrases: Vec<String>,
    commands: Vec<CapabilityCommand>,
    data_paths: Vec<String>,
    tags: Vec<String>,
    mcp_tools: Vec<String>,
    notes: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
struct CapabilityStatus {
    id: String,
    name: String,
    description: String,
    category: String,
    kind: String,
    service_id: Option<String>,
    entry_url: Option<String>,
    enabled: bool,
    ok: bool,
    health_status: String,
    sidecar_ok: Option<bool>,
    trigger_phrases: Vec<String>,
    commands: Vec<CapabilityCommand>,
    data_paths: Vec<String>,
    tags: Vec<String>,
    mcp_tools: Vec<String>,
    notes: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
struct CapabilitySummary {
    total: usize,
    enabled: usize,
    healthy: usize,
    degraded: usize,
}

#[derive(Debug, Clone, Serialize)]
struct CapabilityRegistryResponse {
    now: String,
    summary: CapabilitySummary,
    items: Vec<CapabilityStatus>,
}

#[tokio::main]
async fn main() {
    let port: u16 = std::env::var("LOF_SIDECAR_PORT")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(8093);
    let timeout_secs: u64 = std::env::var("LOF_SIDECAR_TIMEOUT_SECS")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(240);
    let script_dir = std::env::var("LOF_SCRIPT_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("/root/.nanobot/workspace/skills/qdii-monitor"));
    let state_file = std::env::var("LOF_SIDECAR_STATE_FILE")
        .map(PathBuf::from)
        .unwrap_or_else(|_| {
            PathBuf::from(
                "/root/.nanobot/workspace/skills/qdii-monitor/lof-sidecar-rs/data/state.json",
            )
        });

    if let Some(parent) = state_file.parent() {
        let _ = tokio::fs::create_dir_all(parent).await;
    }
    let dashboard_history_file = std::env::var("DASHBOARD_HISTORY_FILE")
        .map(PathBuf::from)
        .unwrap_or_else(|_| {
            state_file
                .parent()
                .unwrap_or_else(|| Path::new("."))
                .join("dashboard_history.json")
        });
    if let Some(parent) = dashboard_history_file.parent() {
        let _ = tokio::fs::create_dir_all(parent).await;
    }
    let auto_compact_events_file = std::env::var("AUTO_COMPACT_EVENTS_FILE")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("/root/.nanobot/workspace/auto_compact_events.jsonl"));
    if let Some(parent) = auto_compact_events_file.parent() {
        let _ = tokio::fs::create_dir_all(parent).await;
    }
    let inbox_dir = std::env::var("NANOBOT_INBOX_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("/root/.nanobot/data/knowledge-inbox"));
    let _ = tokio::fs::create_dir_all(&inbox_dir).await;

    let http = Client::builder()
        .connect_timeout(Duration::from_secs(5))
        .pool_idle_timeout(Duration::from_secs(60))
        .user_agent("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36")
        .build()
        .expect("build reqwest client");

    let app_state = AppState {
        script_dir,
        state_file,
        dashboard_history_file,
        auto_compact_events_file,
        inbox_dir,
        timeout_secs,
        run_lock: Arc::new(Mutex::new(())),
        http,
    };

    let history_state = app_state.clone();
    tokio::spawn(async move {
        let mut tick = tokio::time::interval(Duration::from_secs(3600));
        loop {
            tick.tick().await;
            let _ = refresh_dashboard_history(&history_state).await;
        }
    });

    let app = Router::new()
        .route("/", get(dashboard))
        .route("/lof", get(index))
        .route("/lof/", get(index))
        .route("/robots.txt", get(robots_txt))
        .route("/health", get(health))
        .route("/api/status", get(api_status))
        .route("/api/system", get(api_system))
        .route("/api/dashboard-history", get(api_dashboard_history))
        .route("/api/auto-compact", get(api_auto_compact))
        .route("/sidecars", get(sidecars_page))
        .route("/evolution", get(evolution_gone))
        .route("/inbox", get(inbox_page))
        .route("/workbench", get(workbench_page))
        .route("/workbench/", get(workbench_page))
        .route("/today", get(personal_ops_page))
        .route("/tasks", get(personal_ops_page))
        .route("/model-routes", get(personal_ops_page))
        .route("/assets/nb-shell.js", get(shell_js))
        .route("/assets/nb-common.js", get(common_js))
        .route("/api/sidecars", get(api_sidecars))
        .route("/api/inbox", get(api_inbox))
        .route("/api/inbox/:id", delete(api_delete_inbox))
        .route("/api/inbox/:id/rating", post(api_rate_inbox))
        .route("/api/internal/render-text", post(api_internal_render_text))
        .route("/api/capabilities", get(api_capabilities))
        .route("/api/evolution", get(evolution_gone))
        .route("/api/notify-jobs", get(api_notify_jobs))
        .route("/api/today", get(api_today))
        .route("/api/task-trace", get(api_task_trace))
        .route("/api/task-run/:id", post(api_task_run))
        .route("/api/model-routes", get(api_model_routes))
        .route("/rss", any(proxy_rss_root))
        .route("/rss/", any(proxy_rss_root))
        .route("/rss/*path", any(proxy_rss_path))
        .route("/reflexio", any(proxy_reflexio_root))
        .route("/reflexio/", any(proxy_reflexio_root))
        .route("/reflexio/*path", any(proxy_reflexio_path))
        .route("/obp-login", get(obp_login_page))
        .route("/obp-auth/status", get(obp_auth_status))
        .route("/obp-auth/login", post(obp_auth_login))
        .route("/obp-auth/logout", post(obp_auth_logout))
        .route("/obp-auth/password", post(obp_auth_password))
        .route("/obp", any(proxy_obp_root))
        .route("/obp/", any(proxy_obp_root))
        .route("/obp/*path", any(proxy_obp_path))
        .route("/trends", any(proxy_trends_root))
        .route("/trends/", any(proxy_trends_root))
        .route("/trends/*path", any(proxy_trends_path))
        .route("/api/run", post(api_run))
        .route("/api/trigger", post(api_trigger))
        .with_state(app_state.clone())
        .layer(middleware::map_response(add_noindex_headers));

    tokio::spawn(auto_refresh_loop(app_state.clone()));

    let addr = SocketAddr::from(([0, 0, 0, 0], port));
    println!("lof-sidecar-rs listening on http://{}", addr);
    let listener = tokio::net::TcpListener::bind(addr)
        .await
        .expect("bind failed");
    axum::serve(listener, app).await.expect("server failed");
}

async fn add_noindex_headers(mut response: Response) -> Response {
    response
        .headers_mut()
        .insert(X_ROBOTS_TAG, NOINDEX_HEADER_VALUE);
    response
}

async fn robots_txt() -> Response {
    Response::builder()
        .status(StatusCode::OK)
        .header(header::CONTENT_TYPE, "text/plain; charset=utf-8")
        .header(X_ROBOTS_TAG, NOINDEX_HEADER_VALUE)
        .header(header::CACHE_CONTROL, "no-store, max-age=0")
        .body(Body::from(ROBOTS_TXT))
        .unwrap_or_else(|_| Response::new(Body::from(ROBOTS_TXT)))
}

async fn evolution_gone() -> Response {
    Response::builder()
        .status(StatusCode::GONE)
        .header(header::CONTENT_TYPE, "text/plain; charset=utf-8")
        .header(X_ROBOTS_TAG, NOINDEX_HEADER_VALUE)
        .header(header::CACHE_CONTROL, "no-store, max-age=0")
        .body(Body::from(
            "This historical dashboard URL has been removed. Private evolution data is no longer exposed over HTTP.\n",
        ))
        .unwrap_or_else(|_| Response::new(Body::from("Gone\n")))
}

async fn health() -> impl IntoResponse {
    Json(serde_json::json!({
        "ok": true,
        "service": "lof-sidecar-rs",
        "time": Utc::now().to_rfc3339(),
    }))
}

async fn api_status(State(state): State<AppState>) -> impl IntoResponse {
    let current = load_state(&state.state_file).await;
    Json(current)
}

async fn api_system() -> impl IntoResponse {
    Json(serde_json::json!({
        "ok": true,
        "now": shanghai_now().format("%Y-%m-%d %H:%M:%S %:z").to_string(),
        "memory": read_meminfo_mb(),
        "loadavg": read_loadavg(),
        "cpu": read_cpu_info(),
        "disk_root": read_disk_root().await,
    }))
}

async fn api_dashboard_history(State(state): State<AppState>) -> impl IntoResponse {
    Json(refresh_dashboard_history(&state).await)
}

async fn api_auto_compact(State(state): State<AppState>) -> impl IntoResponse {
    Json(read_auto_compact_events(&state.auto_compact_events_file).await)
}

async fn read_auto_compact_events(path: &Path) -> serde_json::Value {
    let Ok(text) = tokio::fs::read_to_string(path).await else {
        return serde_json::json!({
            "ok": true,
            "path": path.display().to_string(),
            "items": [],
            "note": "暂无压缩事件。AutoCompact 只有在开启 idleCompactAfterMinutes 后才会写入。"
        });
    };
    let mut items: Vec<serde_json::Value> = text
        .lines()
        .filter_map(|line| serde_json::from_str::<serde_json::Value>(line).ok())
        .collect();
    items.reverse();
    items.truncate(30);
    serde_json::json!({
        "ok": true,
        "path": path.display().to_string(),
        "items": items,
    })
}

async fn api_inbox(State(state): State<AppState>) -> impl IntoResponse {
    Json(inbox_snapshot(&state.inbox_dir).await)
}

async fn api_delete_inbox(
    State(state): State<AppState>,
    AxumPath(ref_id): AxumPath<String>,
) -> Response {
    match delete_inbox_item(&state.inbox_dir, &ref_id).await {
        Ok(value) => (StatusCode::OK, Json(value)).into_response(),
        Err((status, message)) => (
            status,
            Json(serde_json::json!({
                "ok": false,
                "id": ref_id,
                "error": message,
            })),
        )
            .into_response(),
    }
}

async fn api_rate_inbox(
    State(state): State<AppState>,
    AxumPath(ref_id): AxumPath<String>,
    Json(req): Json<InboxRatingRequest>,
) -> Response {
    match rate_inbox_item(
        &state.inbox_dir,
        &ref_id,
        req.score,
        req.note.unwrap_or_default(),
    )
    .await
    {
        Ok(value) => (StatusCode::OK, Json(value)).into_response(),
        Err((status, message)) => (
            status,
            Json(serde_json::json!({
                "ok": false,
                "id": ref_id,
                "error": message,
            })),
        )
            .into_response(),
    }
}

async fn api_internal_render_text(Json(req): Json<RenderTextRequest>) -> Response {
    let Some(expected_token) = read_render_token().await else {
        return (
            StatusCode::SERVICE_UNAVAILABLE,
            Json(serde_json::json!({
                "ok": false,
                "error": "render token is not configured"
            })),
        )
            .into_response();
    };
    if req.token.as_deref() != Some(expected_token.as_str()) {
        return (
            StatusCode::UNAUTHORIZED,
            Json(serde_json::json!({
                "ok": false,
                "error": "unauthorized"
            })),
        )
            .into_response();
    }
    if !is_allowed_render_url(&req.url) {
        return (
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({
                "ok": false,
                "error": "only public Feishu document URLs are allowed"
            })),
        )
            .into_response();
    }

    let script = std::env::var("NANOBOT_BROWSER_OPERATOR").unwrap_or_else(|_| {
        "/root/.nanobot/workspace/skills/browser-operator/browser_once.py".to_string()
    });
    let limit = req.limit.unwrap_or(40_000).clamp(1_000, 60_000);
    let mut command = Command::new("python3");
    command.arg(script);
    if is_feishu_docx_url(&req.url) {
        command
            .arg("feishu-text")
            .arg(&req.url)
            .arg("--limit")
            .arg(limit.to_string())
            .arg("--wait-ms")
            .arg("8000")
            .arg("--timeout")
            .arg("100")
            .arg("--output-limit")
            .arg((limit + 10_000).to_string());
    } else {
        command
            .arg("deep-text")
            .arg(&req.url)
            .arg("--limit")
            .arg(limit.to_string())
            .arg("--scrolls")
            .arg("18")
            .arg("--delay-ms")
            .arg("450")
            .arg("--wait-ms")
            .arg("6000")
            .arg("--timeout")
            .arg("100")
            .arg("--output-limit")
            .arg((limit + 10_000).to_string());
    }

    let output = match tokio::time::timeout(Duration::from_secs(115), command.output()).await {
        Ok(Ok(output)) => output,
        Ok(Err(err)) => {
            return (
                StatusCode::BAD_GATEWAY,
                Json(serde_json::json!({
                    "ok": false,
                    "error": format!("render command failed: {}", err)
                })),
            )
                .into_response();
        }
        Err(_) => {
            return (
                StatusCode::GATEWAY_TIMEOUT,
                Json(serde_json::json!({
                    "ok": false,
                    "error": "render command timed out"
                })),
            )
                .into_response();
        }
    };
    let stdout = String::from_utf8_lossy(&output.stdout).to_string();
    let stderr = String::from_utf8_lossy(&output.stderr).to_string();
    let parsed = serde_json::from_str::<serde_json::Value>(&stdout).unwrap_or_else(|_| {
        serde_json::json!({
            "ok": false,
            "error": "render command returned non-json output",
            "stdout": stdout,
            "stderr": stderr,
        })
    });
    let text = parsed
        .pointer("/result/stdout")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    if !output.status.success() || !parsed.get("ok").and_then(|v| v.as_bool()).unwrap_or(false) {
        return (
            StatusCode::BAD_GATEWAY,
            Json(serde_json::json!({
                "ok": false,
                "error": "render command did not complete successfully",
                "details": parsed,
                "stderr": stderr,
            })),
        )
            .into_response();
    }

    Json(serde_json::json!({
        "ok": true,
        "url": req.url,
        "chars": text.chars().count(),
        "text": text,
    }))
    .into_response()
}

async fn read_render_token() -> Option<String> {
    let path = std::env::var("NANOBOT_INBOX_RENDER_TOKEN_FILE")
        .unwrap_or_else(|_| "/root/.nanobot/data/knowledge-inbox/render_token".to_string());
    let token = tokio::fs::read_to_string(path).await.ok()?;
    let token = token.trim().to_string();
    if token.is_empty() {
        None
    } else {
        Some(token)
    }
}

fn is_allowed_render_url(url: &str) -> bool {
    let Ok(parsed) = reqwest::Url::parse(url) else {
        return false;
    };
    if parsed.scheme() != "https" {
        return false;
    }
    let Some(host) = parsed.host_str().map(|h| h.to_ascii_lowercase()) else {
        return false;
    };
    host == "feishu.cn" || host.ends_with(".feishu.cn")
}

fn is_feishu_docx_url(url: &str) -> bool {
    let Ok(parsed) = reqwest::Url::parse(url) else {
        return false;
    };
    parsed.path().contains("/docx/")
        && parsed
            .host_str()
            .map(|host| {
                let host = host.to_ascii_lowercase();
                host == "feishu.cn" || host.ends_with(".feishu.cn")
            })
            .unwrap_or(false)
}

async fn refresh_dashboard_history(state: &AppState) -> serde_json::Value {
    let now = shanghai_now();
    let day = now.format("%Y-%m-%d").to_string();
    let memory = read_meminfo_mb();
    let mem_used = json_u64(&memory, "used_mb");
    let mem_pct = json_f64(&memory, "used_pct");

    let sidecars = sidecar_manager::snapshot(&state.http).await;
    let service_total = sidecars.summary.total as u64;
    let service_healthy = sidecars.summary.healthy as u64;
    let service_unhealthy = sidecars.summary.unhealthy as u64;

    let notify = fetch_json_value(&state.http, "http://127.0.0.1:8094/api/status")
        .await
        .unwrap_or_else(|| serde_json::json!({}));
    let jobs = notify
        .get("job_details")
        .or_else(|| notify.get("configured_jobs"))
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();
    let task_errors = jobs
        .iter()
        .filter(|j| {
            matches!(
                j.pointer("/status/last_status").and_then(|v| v.as_str()),
                Some("error") | Some("timeout")
            )
        })
        .count() as u64;
    let task_sent = jobs
        .iter()
        .filter(|j| {
            j.pointer("/status/last_sent")
                .and_then(|v| v.as_bool())
                .unwrap_or(false)
                && j.pointer("/status/last_finished_at")
                    .and_then(|v| v.as_str())
                    .is_some_and(|s| s.contains(&day))
        })
        .count() as u64;
    let task_runs = jobs
        .iter()
        .filter(|j| {
            j.pointer("/status/last_finished_at")
                .or_else(|| j.pointer("/status/last_started_at"))
                .and_then(|v| v.as_str())
                .is_some_and(|s| s.contains(&day))
        })
        .count() as u64;

    let rss = fetch_json_value(
        &state.http,
        "http://127.0.0.1:8091/api/entries?days=1&limit=100",
    )
    .await
    .unwrap_or_else(|| serde_json::json!({}));
    let article_count = rss
        .get("items")
        .and_then(|v| v.as_array())
        .map(|items| items.len() as u64)
        .unwrap_or(0);

    let lof = load_state(&state.state_file).await;
    let lof_high = lof
        .last_board
        .as_ref()
        .map(|board| {
            board
                .rows
                .iter()
                .filter(|row| row.rt_premium_pct.unwrap_or(0.0) >= 5.0)
                .count() as u64
        })
        .unwrap_or(0);

    let mut history = read_dashboard_history(&state.dashboard_history_file).await;
    let today_sample = serde_json::json!({
        "day": day,
        "updated_at": now.format("%Y-%m-%d %H:%M:%S %:z").to_string(),
        "memory_used_mb": mem_used,
        "memory_used_max_mb": mem_used,
        "memory_used_pct": mem_pct,
        "service_healthy": service_healthy,
        "service_total": service_total,
        "service_unhealthy": service_unhealthy,
        "service_unhealthy_max": service_unhealthy,
        "task_runs": task_runs,
        "task_sent": task_sent,
        "task_errors": task_errors,
        "task_errors_max": task_errors,
        "articles": article_count,
        "lof_high_premium": lof_high,
        "lof_high_premium_max": lof_high,
    });

    if let Some(existing) = history
        .iter_mut()
        .find(|item| item.get("day").and_then(|v| v.as_str()) == Some(day.as_str()))
    {
        update_dashboard_history_entry(existing, today_sample);
    } else {
        history.push(today_sample);
    }

    history.sort_by_key(|item| {
        item.get("day")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string()
    });
    if history.len() > 7 {
        let remove_count = history.len() - 7;
        history.drain(0..remove_count);
    }
    let _ = write_dashboard_history(&state.dashboard_history_file, &history).await;

    serde_json::json!({
        "ok": true,
        "now": now.format("%Y-%m-%d %H:%M:%S %:z").to_string(),
        "retention_days": 7,
        "items": history,
    })
}

async fn fetch_json_value(client: &Client, url: &str) -> Option<serde_json::Value> {
    let resp = tokio::time::timeout(Duration::from_secs(3), client.get(url).send())
        .await
        .ok()?
        .ok()?;
    if !resp.status().is_success() {
        return None;
    }
    resp.json::<serde_json::Value>().await.ok()
}

async fn read_dashboard_history(path: &Path) -> Vec<serde_json::Value> {
    match tokio::fs::read_to_string(path).await {
        Ok(text) => serde_json::from_str::<Vec<serde_json::Value>>(&text).unwrap_or_default(),
        Err(_) => Vec::new(),
    }
}

async fn write_dashboard_history(
    path: &Path,
    history: &[serde_json::Value],
) -> std::io::Result<()> {
    if let Some(parent) = path.parent() {
        tokio::fs::create_dir_all(parent).await?;
    }
    let body = serde_json::to_string_pretty(history).unwrap_or_else(|_| "[]".to_string());
    tokio::fs::write(path, format!("{body}\n")).await
}

fn update_dashboard_history_entry(existing: &mut serde_json::Value, sample: serde_json::Value) {
    let Some(obj) = existing.as_object_mut() else {
        *existing = sample;
        return;
    };
    if let Some(sample_obj) = sample.as_object() {
        for key in [
            "updated_at",
            "memory_used_mb",
            "memory_used_pct",
            "service_healthy",
            "service_total",
            "service_unhealthy",
            "task_runs",
            "task_sent",
            "task_errors",
            "articles",
            "lof_high_premium",
        ] {
            if let Some(value) = sample_obj.get(key) {
                obj.insert(key.to_string(), value.clone());
            }
        }
    }
    update_max_field(
        obj,
        "memory_used_max_mb",
        mem_value(&sample, "memory_used_max_mb"),
    );
    update_max_field(
        obj,
        "service_unhealthy_max",
        mem_value(&sample, "service_unhealthy_max"),
    );
    update_max_field(
        obj,
        "task_errors_max",
        mem_value(&sample, "task_errors_max"),
    );
    update_max_field(
        obj,
        "lof_high_premium_max",
        mem_value(&sample, "lof_high_premium_max"),
    );
}

fn update_max_field(obj: &mut serde_json::Map<String, serde_json::Value>, key: &str, value: u64) {
    let current = obj.get(key).and_then(|v| v.as_u64()).unwrap_or(0);
    obj.insert(key.to_string(), serde_json::json!(current.max(value)));
}

fn mem_value(value: &serde_json::Value, key: &str) -> u64 {
    value.get(key).and_then(|v| v.as_u64()).unwrap_or(0)
}

async fn api_sidecars(State(state): State<AppState>) -> impl IntoResponse {
    Json(sidecar_manager::snapshot(&state.http).await)
}

async fn api_capabilities(State(state): State<AppState>) -> impl IntoResponse {
    Json(capability_registry_snapshot(&state).await)
}

macro_rules! proxy_pair {
    ($root_fn:ident, $path_fn:ident, $upstream:literal, $prefix:literal) => {
        async fn $root_fn(
            State(state): State<AppState>,
            method: Method,
            uri: Uri,
            headers: HeaderMap,
            body: Bytes,
        ) -> Response {
            reverse_proxy(
                &state.http,
                $upstream,
                $prefix,
                "",
                method,
                uri,
                headers,
                body,
            )
            .await
        }

        async fn $path_fn(
            State(state): State<AppState>,
            AxumPath(path): AxumPath<String>,
            method: Method,
            uri: Uri,
            headers: HeaderMap,
            body: Bytes,
        ) -> Response {
            reverse_proxy(
                &state.http,
                $upstream,
                $prefix,
                &path,
                method,
                uri,
                headers,
                body,
            )
            .await
        }
    };
}

proxy_pair!(
    proxy_rss_root,
    proxy_rss_path,
    "http://127.0.0.1:8091",
    "/rss"
);
proxy_pair!(
    proxy_reflexio_root,
    proxy_reflexio_path,
    "http://127.0.0.1:8081",
    "/reflexio"
);
proxy_pair!(
    proxy_trends_root,
    proxy_trends_path,
    "http://127.0.0.1:8095",
    "/trends"
);

async fn proxy_obp_root(
    State(state): State<AppState>,
    method: Method,
    uri: Uri,
    headers: HeaderMap,
    body: Bytes,
) -> Response {
    if !is_obp_proxy_authorized(&headers) {
        return obp_unauthorized_response(&headers, &method);
    }
    let headers = prepare_obp_upstream_headers(headers);
    reverse_proxy(
        &state.http,
        "http://127.0.0.1:8000",
        "/obp",
        "",
        method,
        uri,
        headers,
        body,
    )
    .await
}

async fn proxy_obp_path(
    State(state): State<AppState>,
    AxumPath(path): AxumPath<String>,
    method: Method,
    uri: Uri,
    headers: HeaderMap,
    body: Bytes,
) -> Response {
    if !is_obp_proxy_authorized(&headers) {
        return obp_unauthorized_response(&headers, &method);
    }
    let headers = prepare_obp_upstream_headers(headers);
    reverse_proxy(
        &state.http,
        "http://127.0.0.1:8000",
        "/obp",
        &path,
        method,
        uri,
        headers,
        body,
    )
    .await
}

fn prepare_obp_upstream_headers(mut headers: HeaderMap) -> HeaderMap {
    if let Some(token) = current_obp_secret("OBP_PROXY_TOKEN") {
        if let Ok(value) = HeaderValue::from_str(&format!("Bearer {token}")) {
            headers.insert(header::AUTHORIZATION, value);
        }
    }
    headers.remove(header::COOKIE);
    headers
}

async fn obp_login_page() -> Html<&'static str> {
    Html(OBP_LOGIN_HTML)
}

async fn obp_auth_status(headers: HeaderMap) -> impl IntoResponse {
    Json(serde_json::json!({
        "authenticated": is_obp_proxy_authorized(&headers),
        "form_login": true,
    }))
}

async fn obp_auth_login(Json(req): Json<ObpLoginRequest>) -> Response {
    let basic_b64 = encode_basic_pair(&req.username, &req.password);
    if current_obp_basic_b64().is_some_and(|saved| saved == basic_b64) {
        return json_with_cookie(
            StatusCode::OK,
            serde_json::json!({"ok": true}),
            Some(session_cookie_value()),
        );
    }
    json_response(
        StatusCode::UNAUTHORIZED,
        serde_json::json!({"ok": false, "error": "invalid_credentials"}),
    )
}

async fn obp_auth_logout() -> Response {
    Response::builder()
        .status(StatusCode::OK)
        .header(header::CONTENT_TYPE, "application/json; charset=utf-8")
        .header(
            header::SET_COOKIE,
            "obp_session=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax",
        )
        .body(Body::from(r#"{"ok":true}"#))
        .unwrap()
}

async fn obp_auth_password(headers: HeaderMap, Json(req): Json<ObpPasswordRequest>) -> Response {
    if !is_obp_proxy_authorized(&headers) {
        return json_response(
            StatusCode::UNAUTHORIZED,
            serde_json::json!({"ok": false, "error": "unauthorized"}),
        );
    }
    if req.username.trim().is_empty() || req.password.is_empty() {
        return json_response(
            StatusCode::BAD_REQUEST,
            serde_json::json!({"ok": false, "error": "username_and_password_required"}),
        );
    }
    match save_obp_basic_b64(&encode_basic_pair(req.username.trim(), &req.password)) {
        Ok(()) => json_with_cookie(
            StatusCode::OK,
            serde_json::json!({"ok": true}),
            Some(session_cookie_value()),
        ),
        Err(err) => json_response(
            StatusCode::INTERNAL_SERVER_ERROR,
            serde_json::json!({"ok": false, "error": err.to_string()}),
        ),
    }
}

fn is_obp_proxy_authorized(headers: &HeaderMap) -> bool {
    let token = current_obp_secret("OBP_PROXY_TOKEN").unwrap_or_default();
    if token.is_empty() {
        return true;
    }

    if headers
        .get("x-obp-token")
        .and_then(|v| v.to_str().ok())
        .is_some_and(|v| v.trim() == token)
    {
        return true;
    }

    if cookie_value(headers, "obp_session").is_some_and(|v| v == session_cookie_value()) {
        return true;
    }

    let Some(auth) = headers
        .get(header::AUTHORIZATION)
        .and_then(|v| v.to_str().ok())
    else {
        return false;
    };
    let auth = auth.trim();
    if auth == format!("Bearer {token}") {
        return true;
    }

    current_obp_basic_b64().is_some_and(|basic_b64| auth == format!("Basic {basic_b64}"))
}

fn obp_unauthorized_response(headers: &HeaderMap, method: &Method) -> Response {
    let accept_html = *method == Method::GET
        && headers
            .get(header::ACCEPT)
            .and_then(|v| v.to_str().ok())
            .is_some_and(|value| value.contains("text/html"));
    if accept_html {
        return Response::builder()
            .status(StatusCode::SEE_OTHER)
            .header(header::LOCATION, "/obp-login")
            .body(Body::empty())
            .unwrap();
    }
    json_response(
        StatusCode::UNAUTHORIZED,
        serde_json::json!({"ok": false, "error": "obp_requires_authentication"}),
    )
}

fn json_response(status: StatusCode, value: serde_json::Value) -> Response {
    Response::builder()
        .status(status)
        .header(header::CONTENT_TYPE, "application/json; charset=utf-8")
        .body(Body::from(value.to_string()))
        .unwrap()
}

fn json_with_cookie(
    status: StatusCode,
    value: serde_json::Value,
    session_value: Option<String>,
) -> Response {
    let mut builder = Response::builder()
        .status(status)
        .header(header::CONTENT_TYPE, "application/json; charset=utf-8");
    if let Some(value) = session_value {
        builder = builder.header(
            header::SET_COOKIE,
            format!("obp_session={value}; Path=/; Max-Age=2592000; HttpOnly; SameSite=Lax"),
        );
    }
    builder.body(Body::from(value.to_string())).unwrap()
}

fn session_cookie_value() -> String {
    current_obp_secret("OBP_PROXY_TOKEN")
        .or_else(current_obp_basic_b64)
        .unwrap_or_default()
}

fn current_obp_basic_b64() -> Option<String> {
    current_obp_secret("OBP_PROXY_BASIC_B64")
}

fn current_obp_secret(key: &str) -> Option<String> {
    if let Some(value) = read_obp_env_file_value(key) {
        return Some(value);
    }
    std::env::var(key)
        .ok()
        .map(|v| v.trim().to_string())
        .filter(|v| !v.is_empty())
}

fn read_obp_env_file_value(key: &str) -> Option<String> {
    let path = obp_proxy_env_path();
    let data = fs::read_to_string(path).ok()?;
    for line in data.lines() {
        let Some((name, value)) = line.split_once('=') else {
            continue;
        };
        if name.trim() == key {
            let value = value
                .trim()
                .trim_matches('"')
                .trim_matches('\'')
                .to_string();
            if !value.is_empty() {
                return Some(value);
            }
        }
    }
    None
}

fn save_obp_basic_b64(value: &str) -> std::io::Result<()> {
    let path = obp_proxy_env_path();
    let mut lines = fs::read_to_string(&path)
        .unwrap_or_default()
        .lines()
        .map(ToString::to_string)
        .collect::<Vec<_>>();
    let mut updated = false;
    for line in &mut lines {
        if line.trim_start().starts_with("OBP_PROXY_BASIC_B64=") {
            *line = format!("OBP_PROXY_BASIC_B64={value}");
            updated = true;
            break;
        }
    }
    if !updated {
        lines.push(format!("OBP_PROXY_BASIC_B64={value}"));
    }
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    fs::write(&path, format!("{}\n", lines.join("\n")))?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let _ = fs::set_permissions(&path, fs::Permissions::from_mode(0o600));
    }
    Ok(())
}

fn obp_proxy_env_path() -> PathBuf {
    std::env::var("OBP_PROXY_ENV_FILE")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("/root/.nanobot/secrets/obp-proxy.env"))
}

fn cookie_value(headers: &HeaderMap, key: &str) -> Option<String> {
    let cookie = headers.get(header::COOKIE)?.to_str().ok()?;
    for item in cookie.split(';') {
        let (name, value) = item.trim().split_once('=')?;
        if name == key {
            return Some(value.to_string());
        }
    }
    None
}

fn encode_basic_pair(username: &str, password: &str) -> String {
    base64_encode(format!("{}:{}", username.trim(), password).as_bytes())
}

fn base64_encode(bytes: &[u8]) -> String {
    const TABLE: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut out = String::with_capacity(bytes.len().div_ceil(3) * 4);
    for chunk in bytes.chunks(3) {
        let b0 = chunk[0];
        let b1 = *chunk.get(1).unwrap_or(&0);
        let b2 = *chunk.get(2).unwrap_or(&0);
        out.push(TABLE[(b0 >> 2) as usize] as char);
        out.push(TABLE[(((b0 & 0b0000_0011) << 4) | (b1 >> 4)) as usize] as char);
        if chunk.len() > 1 {
            out.push(TABLE[(((b1 & 0b0000_1111) << 2) | (b2 >> 6)) as usize] as char);
        } else {
            out.push('=');
        }
        if chunk.len() > 2 {
            out.push(TABLE[(b2 & 0b0011_1111) as usize] as char);
        } else {
            out.push('=');
        }
    }
    out
}

const OBP_LOGIN_HTML: &str = r#"<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>OBP 登录</title>
<style>
:root{color-scheme:dark light}body{margin:0;min-height:100vh;display:grid;place-items:center;font-family:ui-sans-serif,system-ui;background:radial-gradient(circle at 20% 10%,#14b8a633,transparent 34%),linear-gradient(135deg,#020617,#0f172a);color:#e5e7eb}.card{width:min(92vw,420px);border:1px solid #334155;border-radius:28px;background:#0f172add;box-shadow:0 28px 80px #0008;padding:28px}h1{margin:0 0 8px;font-size:32px;letter-spacing:-.04em}.hint{color:#94a3b8;line-height:1.7;font-size:14px}.field{display:block;margin-top:16px;font-size:13px;font-weight:800;color:#cbd5e1}.input{box-sizing:border-box;width:100%;margin-top:7px;border:1px solid #475569;border-radius:14px;background:#020617;color:#f8fafc;padding:13px 14px;font-size:16px;outline:none}.input:focus{border-color:#2dd4bf;box-shadow:0 0 0 4px #2dd4bf22}.btn{width:100%;border:0;border-radius:16px;margin-top:20px;padding:13px 16px;font-size:16px;font-weight:900;background:#ccfbf1;color:#042f2e;cursor:pointer}.err{min-height:20px;margin-top:12px;color:#fb7185;font-size:13px;font-weight:800}.foot{margin-top:18px;color:#64748b;font-size:12px;line-height:1.6}
</style>
</head>
<body>
<form class="card" id="login">
<div style="font-size:12px;font-weight:900;letter-spacing:.22em;color:#5eead4">MODEL ROUTER</div>
<h1>OBP 登录</h1>
<div class="hint">使用网页表单登录，浏览器可以正常保存密码。API 调用仍然使用 Bearer Token 或 Basic Auth。</div>
<label class="field">用户名<input class="input" name="username" autocomplete="username" required autofocus></label>
<label class="field">密码<input class="input" name="password" type="password" autocomplete="current-password" required></label>
<button class="btn" type="submit">进入 OBP 控制台</button>
<div class="err" id="err"></div>
<div class="foot">登录成功后会跳转到 /obp/，并写入 HttpOnly 会话 Cookie。</div>
</form>
<script>
document.getElementById('login').addEventListener('submit', async (event)=>{
  event.preventDefault();
  const fd=new FormData(event.currentTarget);
  const err=document.getElementById('err');
  err.textContent='';
  const res=await fetch('/obp-auth/login',{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:fd.get('username'),password:fd.get('password')})});
  if(res.ok){ location.href='/obp/'; return; }
  err.textContent='账号或密码不对';
});
</script>
</body>
</html>"#;

async fn api_notify_jobs(State(state): State<AppState>) -> impl IntoResponse {
    match state
        .http
        .get("http://127.0.0.1:8094/api/status")
        .send()
        .await
    {
        Ok(resp) => {
            let status = resp.status();
            match resp.json::<serde_json::Value>().await {
                Ok(value) if status.is_success() => (StatusCode::OK, Json(value)),
                Ok(value) => (
                    StatusCode::BAD_GATEWAY,
                    Json(
                        serde_json::json!({"ok": false, "error": format!("notify status {}", status), "body": value}),
                    ),
                ),
                Err(e) => (
                    StatusCode::BAD_GATEWAY,
                    Json(serde_json::json!({"ok": false, "error": e.to_string()})),
                ),
            }
        }
        Err(e) => (
            StatusCode::BAD_GATEWAY,
            Json(serde_json::json!({"ok": false, "error": e.to_string()})),
        ),
    }
}

fn notify_job_items(notify: &serde_json::Value) -> Vec<serde_json::Value> {
    if let Some(items) = notify.get("job_details").and_then(|v| v.as_array()) {
        return items.clone();
    }
    let statuses = notify.get("jobs").and_then(|v| v.as_object());
    notify
        .get("configured_jobs")
        .and_then(|v| v.as_array())
        .map(|items| {
            items
                .iter()
                .cloned()
                .map(|mut item| {
                    if let Some(obj) = item.as_object_mut() {
                        let id = obj.get("id").and_then(|v| v.as_str()).unwrap_or_default();
                        let status = statuses
                            .and_then(|map| map.get(id))
                            .cloned()
                            .unwrap_or_else(|| serde_json::json!({}));
                        obj.insert("status".to_string(), status);
                    }
                    item
                })
                .collect()
        })
        .unwrap_or_default()
}

fn json_array(value: &serde_json::Value, key: &str) -> Vec<serde_json::Value> {
    value
        .get(key)
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default()
}

fn json_text(value: Option<&serde_json::Value>) -> String {
    match value {
        Some(serde_json::Value::String(s)) => s.clone(),
        Some(serde_json::Value::Number(n)) => n.to_string(),
        Some(serde_json::Value::Bool(v)) => v.to_string(),
        Some(v) if !v.is_null() => v.to_string(),
        _ => String::new(),
    }
}

fn today_actions(
    task_alerts: &[serde_json::Value],
    lof_high: &[serde_json::Value],
    rss_count: usize,
    trend_count: usize,
    inbox_count: usize,
) -> Vec<serde_json::Value> {
    let mut actions = Vec::new();

    for alert in task_alerts.iter().take(2) {
        let title = json_text(alert.get("name"));
        let id = json_text(alert.get("id"));
        actions.push(serde_json::json!({
            "level": "bad",
            "title": format!("任务异常：{}", if title.is_empty() { id } else { title }),
            "body": json_text(alert.get("reason")),
            "action": "打开任务追踪",
            "url": "/tasks",
        }));
    }

    for row in lof_high.iter().take(2) {
        let code = json_text(row.get("code"));
        let name = json_text(row.get("name"));
        let premium = row
            .get("rt_premium_pct")
            .and_then(|v| v.as_f64())
            .map(|v| format!("{v:.2}%"))
            .unwrap_or_else(|| "-".to_string());
        actions.push(serde_json::json!({
            "level": "warn",
            "title": format!("关注高溢价：{} {}", code, name),
            "body": format!("实时溢价 {premium}，先看是否值得避开追高。"),
            "action": "打开投资看板",
            "url": "/lof",
        }));
    }

    if actions.len() < 3 && rss_count > 0 {
        actions.push(serde_json::json!({
            "level": "info",
            "title": format!("阅读今日 RSS：{rss_count} 篇"),
            "body": "优先看微信订阅和鸭哥 AI 要闻，广告/付费导流已由 RSS 侧过滤。",
            "action": "打开内容工作台",
            "url": "/workbench",
        }));
    }
    if actions.len() < 3 && trend_count > 0 {
        actions.push(serde_json::json!({
            "level": "info",
            "title": format!("扫一眼热点雷达：{trend_count} 条"),
            "body": "只看与科技、经济、政策相关的高信号新闻，跳过低价值娱乐噪音。",
            "action": "打开内容工作台",
            "url": "/workbench",
        }));
    }
    if actions.len() < 3 && inbox_count > 0 {
        actions.push(serde_json::json!({
            "level": "info",
            "title": format!("收件箱待处理：{inbox_count} 条"),
            "body": "把值得看的材料标记、复制 Markdown 或直接删除无效条目。",
            "action": "打开知识收件箱",
            "url": "/inbox",
        }));
    }
    if actions.is_empty() {
        actions.push(serde_json::json!({
            "level": "ok",
            "title": "今天没有红色事项",
            "body": "系统、任务和投资雷达都没有需要立刻处理的告警。",
            "action": "保持观察",
            "url": "/",
        }));
    }
    actions.truncate(3);
    actions
}

fn collect_source_names(root: &serde_json::Value, names: &mut BTreeSet<String>) {
    if let Some(map) = root.get("by_source").and_then(|v| v.as_object()) {
        for key in map.keys() {
            names.insert(key.clone());
        }
    }
    if let Some(map) = root.get("by_source_month").and_then(|v| v.as_object()) {
        for key in map.keys() {
            names.insert(key.clone());
        }
    }
}

fn bucket_for_source(root: &serde_json::Value, source: &str, month: &str) -> serde_json::Value {
    root.get("by_source_month")
        .and_then(|v| v.get(source))
        .and_then(|v| v.get(month))
        .or_else(|| root.get("by_source").and_then(|v| v.get(source)))
        .cloned()
        .unwrap_or_else(|| serde_json::json!({}))
}

fn bucket_requests(bucket: &serde_json::Value) -> u64 {
    bucket
        .get("requests")
        .and_then(|v| v.as_u64())
        .unwrap_or_default()
}

fn bucket_cost(bucket: &serde_json::Value) -> f64 {
    bucket
        .get("cost_cny")
        .and_then(|v| v.as_f64())
        .unwrap_or_default()
}

fn source_cost_rows(stats: &serde_json::Value) -> Vec<serde_json::Value> {
    let month = shanghai_now().format("%Y-%m").to_string();
    let mut names = BTreeSet::new();
    collect_source_names(stats, &mut names);
    if let Some(paid) = stats.get("paid") {
        collect_source_names(paid, &mut names);
    }
    if let Some(free) = stats.get("free") {
        collect_source_names(free, &mut names);
    }

    let paid_root = stats.get("paid").unwrap_or(&serde_json::Value::Null);
    let free_root = stats.get("free").unwrap_or(&serde_json::Value::Null);
    let mut rows = names
        .into_iter()
        .map(|source| {
            let paid = bucket_for_source(paid_root, &source, &month);
            let free = bucket_for_source(free_root, &source, &month);
            let total = bucket_for_source(stats, &source, &month);
            let paid_cost = bucket_cost(&paid);
            let total_requests = bucket_requests(&total)
                .max(bucket_requests(&paid).saturating_add(bucket_requests(&free)));
            serde_json::json!({
                "source": source,
                "month": month,
                "paid": paid,
                "free": free,
                "total": total,
                "paid_cost_cny": paid_cost,
                "free_requests": bucket_requests(&free),
                "total_requests": total_requests,
            })
        })
        .collect::<Vec<_>>();

    rows.sort_by(|a, b| {
        bucket_cost(b.get("paid").unwrap_or(&serde_json::Value::Null))
            .partial_cmp(&bucket_cost(
                a.get("paid").unwrap_or(&serde_json::Value::Null),
            ))
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| {
                bucket_requests(b.get("total").unwrap_or(&serde_json::Value::Null)).cmp(
                    &bucket_requests(a.get("total").unwrap_or(&serde_json::Value::Null)),
                )
            })
    });
    rows.truncate(20);
    rows
}

async fn api_today(State(state): State<AppState>) -> impl IntoResponse {
    let rss = fetch_json_value(
        &state.http,
        "http://127.0.0.1:8091/api/entries?days=1&limit=30",
    )
    .await
    .unwrap_or_else(|| serde_json::json!({}));
    let trend = fetch_json_value(&state.http, "http://127.0.0.1:8095/api/trends/brief")
        .await
        .unwrap_or_else(|| serde_json::json!({}));
    let notify = fetch_json_value(&state.http, "http://127.0.0.1:8094/api/status")
        .await
        .unwrap_or_else(|| serde_json::json!({}));
    let inbox = inbox_snapshot(&state.inbox_dir).await;
    let lof = load_state(&state.state_file).await;

    let lof_high = lof
        .last_board
        .as_ref()
        .map(|board| {
            board
                .rows
                .iter()
                .filter(|row| row.rt_premium_pct.unwrap_or(0.0) >= 5.0)
                .take(12)
                .map(|row| serde_json::to_value(row).unwrap_or(serde_json::Value::Null))
                .collect::<Vec<_>>()
        })
        .unwrap_or_default();
    let jobs = notify_job_items(&notify);
    let task_alerts = jobs
        .iter()
        .filter(|job| {
            matches!(
                job.pointer("/status/last_status").and_then(|v| v.as_str()),
                Some("error") | Some("timeout")
            )
        })
        .map(|job| {
            serde_json::json!({
                "id": job.get("id").cloned().unwrap_or(serde_json::Value::Null),
                "name": job.get("name").cloned().unwrap_or(serde_json::Value::Null),
                "reason": job.pointer("/status/last_error").cloned().unwrap_or_else(|| serde_json::json!("最近任务异常")),
            })
        })
        .collect::<Vec<_>>();

    let rss_items = json_array(&rss, "items");
    let trend_items = json_array(&trend, "top_items");
    let inbox_items = json_array(&inbox, "items");
    let actions = today_actions(
        &task_alerts,
        &lof_high,
        rss_items.len(),
        trend_items.len(),
        inbox_items.len(),
    );

    Json(serde_json::json!({
        "ok": true,
        "now": shanghai_now().format("%Y-%m-%d %H:%M:%S %:z").to_string(),
        "rss_items": rss_items,
        "trend_items": trend_items,
        "inbox_items": inbox_items,
        "lof_high": lof_high,
        "task_alerts": task_alerts,
        "actions": actions,
    }))
}

async fn api_task_trace(State(state): State<AppState>) -> impl IntoResponse {
    let notify = fetch_json_value(&state.http, "http://127.0.0.1:8094/api/status")
        .await
        .unwrap_or_else(|| serde_json::json!({"ok": false, "error": "notify_unreachable"}));
    Json(serde_json::json!({
        "ok": notify.get("ok").and_then(|v| v.as_bool()).unwrap_or(true),
        "now": shanghai_now().format("%Y-%m-%d %H:%M:%S %:z").to_string(),
        "stats": notify.get("stats").cloned().unwrap_or_else(|| serde_json::json!({})),
        "items": notify_job_items(&notify),
        "history_ready": true,
    }))
}

async fn api_task_run(State(state): State<AppState>, AxumPath(id): AxumPath<String>) -> Response {
    if id.trim().is_empty() || id.contains('/') || id.contains('\\') {
        return (
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({"ok": false, "error": "invalid_job_id"})),
        )
            .into_response();
    }
    let url = format!("http://127.0.0.1:8094/api/run/{id}");
    match tokio::time::timeout(Duration::from_secs(180), state.http.post(url).send()).await {
        Ok(Ok(resp)) => {
            let status =
                StatusCode::from_u16(resp.status().as_u16()).unwrap_or(StatusCode::BAD_GATEWAY);
            let value = resp
                .json::<serde_json::Value>()
                .await
                .unwrap_or_else(|_| serde_json::json!({"ok": status.is_success()}));
            (status, Json(value)).into_response()
        }
        Ok(Err(err)) => (
            StatusCode::BAD_GATEWAY,
            Json(serde_json::json!({"ok": false, "error": err.to_string()})),
        )
            .into_response(),
        Err(_) => (
            StatusCode::GATEWAY_TIMEOUT,
            Json(serde_json::json!({"ok": false, "error": "notify_run_timeout"})),
        )
            .into_response(),
    }
}

async fn api_model_routes(State(state): State<AppState>) -> impl IntoResponse {
    let stats = fetch_json_value(&state.http, "http://127.0.0.1:8000/admin/stats")
        .await
        .unwrap_or_else(|| serde_json::json!({}));
    let router = fetch_json_value(&state.http, "http://127.0.0.1:8000/admin/router")
        .await
        .unwrap_or_else(|| serde_json::json!({}));
    let mut recent = json_array(&stats, "recent");
    if recent.is_empty() {
        recent = stats
            .pointer("/logs/recent")
            .and_then(|v| v.as_array())
            .cloned()
            .unwrap_or_default();
    }
    recent.reverse();
    recent.truncate(80);

    let mut pro_reasons = serde_json::Map::new();
    let mut pro_count = 0_u64;
    for log in &recent {
        let route = log
            .get("route")
            .and_then(|v| v.as_str())
            .unwrap_or_default();
        let model = log
            .get("model")
            .and_then(|v| v.as_str())
            .unwrap_or_default()
            .to_ascii_lowercase();
        if route.contains("pro") || model.contains("pro") {
            pro_count += 1;
            let reason = log
                .get("route_reason")
                .and_then(|v| v.as_str())
                .unwrap_or("unknown")
                .to_string();
            let count = pro_reasons
                .get(&reason)
                .and_then(|v| v.as_u64())
                .unwrap_or(0)
                + 1;
            pro_reasons.insert(reason, serde_json::json!(count));
        }
    }

    let source_costs = source_cost_rows(&stats);

    Json(serde_json::json!({
        "ok": true,
        "now": shanghai_now().format("%Y-%m-%d %H:%M:%S %:z").to_string(),
        "stats": stats,
        "router": router,
        "recent": recent,
        "pro_count": pro_count,
        "pro_reasons": pro_reasons,
        "source_costs": source_costs,
    }))
}

fn shanghai_now() -> DateTime<FixedOffset> {
    let sh_tz = FixedOffset::east_opt(8 * 3600).expect("tz");
    Utc::now().with_timezone(&sh_tz)
}

async fn load_capabilities() -> Vec<Capability> {
    let path = std::env::var("CAPABILITY_REGISTRY_CONFIG")
        .unwrap_or_else(|_| "/root/.nanobot/capabilities.json".to_string());
    match tokio::fs::read_to_string(&path).await {
        Ok(text) => serde_json::from_str::<Vec<Capability>>(&text)
            .unwrap_or_else(|_| default_capabilities()),
        Err(_) => default_capabilities(),
    }
}

fn default_capabilities() -> Vec<Capability> {
    vec![Capability {
        id: "lof-monitor".into(),
        name: "LOF Monitor".into(),
        description: "Fallback capability registry when capabilities.json is missing.".into(),
        category: "finance".into(),
        kind: "sidecar".into(),
        service_id: Some("lof".into()),
        entry_url: Some("/lof".into()),
        enabled: true,
        trigger_phrases: vec!["lof status".into()],
        commands: vec![CapabilityCommand {
            label: "logs".into(),
            command: "journalctl -u lof-sidecar.service -f".into(),
        }],
        data_paths: Vec::new(),
        tags: vec!["finance".into(), "sidecar".into()],
        mcp_tools: Vec::new(),
        notes: Some("Install /root/.nanobot/capabilities.json for the full registry.".into()),
    }]
}

async fn capability_registry_snapshot(state: &AppState) -> CapabilityRegistryResponse {
    let sidecars = sidecar_manager::snapshot(&state.http).await;
    let sidecar_by_id: HashMap<String, ManagedSidecarStatus> = sidecars
        .items
        .into_iter()
        .map(|item| (item.id.clone(), item))
        .collect();
    let mut items = Vec::new();
    for cap in load_capabilities().await {
        let sidecar = cap
            .service_id
            .as_deref()
            .and_then(|id| sidecar_by_id.get(id));
        let sidecar_ok = sidecar.map(|item| item.ok);
        let ok = cap.enabled && sidecar_ok.unwrap_or(true);
        let health_status = if !cap.enabled {
            "disabled".to_string()
        } else if let Some(item) = sidecar {
            if item.ok {
                format!("sidecar ok: {}", item.check_status)
            } else {
                format!("sidecar degraded: {}", item.check_status)
            }
        } else {
            "available on demand".to_string()
        };
        items.push(CapabilityStatus {
            id: cap.id,
            name: cap.name,
            description: cap.description,
            category: cap.category,
            kind: cap.kind,
            service_id: cap.service_id,
            entry_url: cap.entry_url,
            enabled: cap.enabled,
            ok,
            health_status,
            sidecar_ok,
            trigger_phrases: cap.trigger_phrases,
            commands: cap.commands,
            data_paths: cap.data_paths,
            tags: cap.tags,
            mcp_tools: cap.mcp_tools,
            notes: cap.notes,
        });
    }
    let total = items.len();
    let enabled = items.iter().filter(|item| item.enabled).count();
    let healthy = items.iter().filter(|item| item.ok).count();
    CapabilityRegistryResponse {
        now: shanghai_now().format("%Y-%m-%d %H:%M:%S %:z").to_string(),
        summary: CapabilitySummary {
            total,
            enabled,
            healthy,
            degraded: total.saturating_sub(healthy),
        },
        items,
    }
}

fn inbox_item_id(item: &serde_json::Value) -> Option<&str> {
    item.get("id").and_then(|value| value.as_str())
}

fn resolve_inbox_map_key(
    map: &serde_json::Map<String, serde_json::Value>,
    ref_id: &str,
) -> Result<String, (StatusCode, String)> {
    if map.contains_key(ref_id) {
        return Ok(ref_id.to_string());
    }
    let mut matches: Vec<String> = map
        .iter()
        .filter_map(|(key, item)| {
            let id = inbox_item_id(item).unwrap_or(key);
            if key.starts_with(ref_id) || id.starts_with(ref_id) {
                Some(key.clone())
            } else {
                None
            }
        })
        .collect();
    matches.sort();
    matches.dedup();
    match matches.len() {
        0 => Err((StatusCode::NOT_FOUND, "没找到这个收件箱条目".to_string())),
        1 => Ok(matches.remove(0)),
        _ => Err((
            StatusCode::CONFLICT,
            "匹配到多个条目，请使用完整 ID".to_string(),
        )),
    }
}

fn resolve_inbox_array_index(
    items: &[serde_json::Value],
    ref_id: &str,
) -> Result<usize, (StatusCode, String)> {
    if let Some(pos) = items
        .iter()
        .position(|item| inbox_item_id(item).is_some_and(|id| id == ref_id))
    {
        return Ok(pos);
    }
    let matches: Vec<usize> = items
        .iter()
        .enumerate()
        .filter_map(|(idx, item)| {
            inbox_item_id(item)
                .is_some_and(|id| id.starts_with(ref_id))
                .then_some(idx)
        })
        .collect();
    match matches.len() {
        0 => Err((StatusCode::NOT_FOUND, "没找到这个收件箱条目".to_string())),
        1 => Ok(matches[0]),
        _ => Err((
            StatusCode::CONFLICT,
            "匹配到多个条目，请使用完整 ID".to_string(),
        )),
    }
}

async fn write_inbox_json(
    items_file: &Path,
    value: &serde_json::Value,
) -> Result<(), (StatusCode, String)> {
    if let Some(parent) = items_file.parent() {
        tokio::fs::create_dir_all(parent)
            .await
            .map_err(|err| (StatusCode::INTERNAL_SERVER_ERROR, err.to_string()))?;
    }
    let body = serde_json::to_string_pretty(value)
        .map_err(|err| (StatusCode::INTERNAL_SERVER_ERROR, err.to_string()))?;
    let tmp = items_file.with_extension("json.tmp");
    tokio::fs::write(&tmp, format!("{}\n", body))
        .await
        .map_err(|err| (StatusCode::INTERNAL_SERVER_ERROR, err.to_string()))?;
    tokio::fs::rename(&tmp, items_file)
        .await
        .map_err(|err| (StatusCode::INTERNAL_SERVER_ERROR, err.to_string()))?;
    Ok(())
}

async fn remove_inbox_markdown(
    inbox_dir: &Path,
    item: &serde_json::Value,
) -> (bool, Option<String>) {
    let Some(raw_path) = item.get("markdown_path").and_then(|value| value.as_str()) else {
        return (false, None);
    };
    let path = PathBuf::from(raw_path);
    let path = if path.is_absolute() {
        path
    } else {
        inbox_dir.join(path)
    };
    let Ok(root) = tokio::fs::canonicalize(inbox_dir).await else {
        return (false, Some(raw_path.to_string()));
    };
    let Ok(resolved) = tokio::fs::canonicalize(&path).await else {
        return (false, Some(raw_path.to_string()));
    };
    if !resolved.starts_with(&root) {
        return (false, Some(raw_path.to_string()));
    }
    match tokio::fs::remove_file(&resolved).await {
        Ok(_) => (true, Some(raw_path.to_string())),
        Err(_) => (false, Some(raw_path.to_string())),
    }
}

fn inbox_decision_label(score: i64) -> &'static str {
    if score >= 75 {
        "值得优先看"
    } else if score >= 58 {
        "可以稍后看"
    } else if score >= 42 {
        "只需扫一眼"
    } else {
        "大概率可跳过"
    }
}

fn apply_inbox_rating(
    item: &mut serde_json::Value,
    score: i64,
    note: &str,
) -> Result<(), (StatusCode, String)> {
    let Some(obj) = item.as_object_mut() else {
        return Err((
            StatusCode::INTERNAL_SERVER_ERROR,
            "inbox item is not an object".to_string(),
        ));
    };
    let score = score.clamp(0, 100);
    if !obj.contains_key("auto_decision_score") {
        let auto_score = obj
            .get("decision_score")
            .cloned()
            .unwrap_or(serde_json::Value::Null);
        let auto_label = obj
            .get("decision_label")
            .cloned()
            .unwrap_or(serde_json::Value::Null);
        let auto_reasons = obj
            .get("decision_reasons")
            .cloned()
            .unwrap_or_else(|| serde_json::json!([]));
        obj.insert("auto_decision_score".to_string(), auto_score);
        obj.insert("auto_decision_label".to_string(), auto_label);
        obj.insert("auto_decision_reasons".to_string(), auto_reasons);
    }
    if !obj.contains_key("auto_base_score") {
        let base_score = obj
            .get("auto_decision_score")
            .cloned()
            .or_else(|| obj.get("decision_score").cloned())
            .unwrap_or(serde_json::Value::Null);
        let base_label = obj
            .get("auto_decision_label")
            .cloned()
            .or_else(|| obj.get("decision_label").cloned())
            .unwrap_or(serde_json::Value::Null);
        let base_reasons = obj
            .get("auto_decision_reasons")
            .cloned()
            .or_else(|| obj.get("decision_reasons").cloned())
            .unwrap_or_else(|| serde_json::json!([]));
        obj.insert("auto_base_score".to_string(), base_score);
        obj.insert("auto_base_label".to_string(), base_label);
        obj.insert("auto_base_reasons".to_string(), base_reasons);
    }
    if !obj.contains_key("profile_version") {
        obj.insert(
            "profile_version".to_string(),
            serde_json::json!("taste-v0.2"),
        );
    }
    let clean_note = note.trim();
    let mut reasons = vec![serde_json::json!(format!("手动评分覆盖：{score}/100"))];
    if !clean_note.is_empty() {
        reasons.push(serde_json::json!(format!("备注：{clean_note}")));
    }
    if let Some(auto_reasons) = obj.get("auto_decision_reasons").and_then(|v| v.as_array()) {
        for reason in auto_reasons.iter().take(2) {
            reasons.push(reason.clone());
        }
    }
    obj.insert("manual_score".to_string(), serde_json::json!(score));
    obj.insert(
        "manual_score_note".to_string(),
        serde_json::json!(clean_note),
    );
    obj.insert(
        "manual_score_at".to_string(),
        serde_json::json!(shanghai_now().to_rfc3339()),
    );
    obj.insert("decision_score".to_string(), serde_json::json!(score));
    obj.insert(
        "decision_label".to_string(),
        serde_json::json!(inbox_decision_label(score)),
    );
    obj.insert(
        "decision_reasons".to_string(),
        serde_json::Value::Array(reasons),
    );
    Ok(())
}

async fn rate_inbox_item(
    inbox_dir: &Path,
    ref_id: &str,
    score: i64,
    note: String,
) -> Result<serde_json::Value, (StatusCode, String)> {
    let ref_id = ref_id.trim();
    if ref_id.is_empty() || ref_id.contains('/') || ref_id.contains('\\') {
        return Err((StatusCode::BAD_REQUEST, "invalid inbox item id".to_string()));
    }
    let items_file = inbox_dir.join("items.json");
    let raw = tokio::fs::read_to_string(&items_file)
        .await
        .unwrap_or_else(|_| "{}".to_string());
    let mut parsed =
        serde_json::from_str::<serde_json::Value>(&raw).unwrap_or_else(|_| serde_json::json!({}));
    let updated = match &mut parsed {
        serde_json::Value::Object(map) => {
            let key = resolve_inbox_map_key(map, ref_id)?;
            let item = map
                .get_mut(&key)
                .ok_or_else(|| (StatusCode::NOT_FOUND, "inbox item not found".to_string()))?;
            apply_inbox_rating(item, score, &note)?;
            item.clone()
        }
        serde_json::Value::Array(items) => {
            let idx = resolve_inbox_array_index(items, ref_id)?;
            let item = items
                .get_mut(idx)
                .ok_or_else(|| (StatusCode::NOT_FOUND, "inbox item not found".to_string()))?;
            apply_inbox_rating(item, score, &note)?;
            item.clone()
        }
        _ => {
            return Err((
                StatusCode::INTERNAL_SERVER_ERROR,
                "items.json format is not supported".to_string(),
            ))
        }
    };
    write_inbox_json(&items_file, &parsed).await?;
    Ok(serde_json::json!({
        "ok": true,
        "item": updated,
    }))
}

async fn delete_inbox_item(
    inbox_dir: &Path,
    ref_id: &str,
) -> Result<serde_json::Value, (StatusCode, String)> {
    let ref_id = ref_id.trim();
    if ref_id.is_empty() || ref_id.contains('/') || ref_id.contains('\\') {
        return Err((StatusCode::BAD_REQUEST, "条目 ID 不合法".to_string()));
    }
    let items_file = inbox_dir.join("items.json");
    let raw = tokio::fs::read_to_string(&items_file)
        .await
        .unwrap_or_else(|_| "{}".to_string());
    let mut parsed =
        serde_json::from_str::<serde_json::Value>(&raw).unwrap_or_else(|_| serde_json::json!({}));
    let deleted = match &mut parsed {
        serde_json::Value::Object(map) => {
            let key = resolve_inbox_map_key(map, ref_id)?;
            map.remove(&key)
                .ok_or_else(|| (StatusCode::NOT_FOUND, "没找到这个收件箱条目".to_string()))?
        }
        serde_json::Value::Array(items) => {
            let idx = resolve_inbox_array_index(items, ref_id)?;
            items.remove(idx)
        }
        _ => {
            return Err((
                StatusCode::INTERNAL_SERVER_ERROR,
                "items.json 格式不支持".to_string(),
            ))
        }
    };
    write_inbox_json(&items_file, &parsed).await?;
    let (markdown_deleted, markdown_path) = remove_inbox_markdown(inbox_dir, &deleted).await;
    Ok(serde_json::json!({
        "ok": true,
        "deleted": true,
        "id": inbox_item_id(&deleted).unwrap_or(ref_id),
        "title": deleted.get("title").and_then(|value| value.as_str()).unwrap_or(""),
        "markdown_deleted": markdown_deleted,
        "markdown_path": markdown_path,
    }))
}

async fn inbox_snapshot(inbox_dir: &Path) -> serde_json::Value {
    let items_file = inbox_dir.join("items.json");
    let raw = tokio::fs::read_to_string(&items_file)
        .await
        .unwrap_or_else(|_| "{}".to_string());
    let parsed = serde_json::from_str::<serde_json::Value>(&raw).unwrap_or(serde_json::Value::Null);
    let mut items: Vec<serde_json::Value> = match parsed {
        serde_json::Value::Array(items) => items,
        serde_json::Value::Object(map) => map.into_values().collect(),
        _ => Vec::new(),
    };
    items.sort_by_key(|item| {
        item.get("captured_at")
            .and_then(|value| value.as_str())
            .unwrap_or("")
            .to_string()
    });
    items.reverse();
    let today = shanghai_now().format("%Y-%m-%d").to_string();
    let score_of = |item: &serde_json::Value| {
        item.get("decision_score")
            .and_then(|value| value.as_i64())
            .unwrap_or(0)
    };
    let total = items.len();
    let priority = items.iter().filter(|item| score_of(item) >= 75).count();
    let maybe = items
        .iter()
        .filter(|item| (58..75).contains(&score_of(item)))
        .count();
    let skipped = items.iter().filter(|item| score_of(item) < 42).count();
    let today_count = items
        .iter()
        .filter(|item| {
            item.get("captured_at")
                .and_then(|value| value.as_str())
                .is_some_and(|value| value.starts_with(&today))
        })
        .count();
    if items.len() > 100 {
        items.truncate(100);
    }
    serde_json::json!({
        "ok": true,
        "now": shanghai_now().format("%Y-%m-%d %H:%M:%S %:z").to_string(),
        "data_file": items_file,
        "markdown_dir": inbox_dir.join("markdown"),
        "summary": {
            "total": total,
            "today": today_count,
            "priority": priority,
            "maybe": maybe,
            "skipped": skipped,
        },
        "items": items,
    })
}

async fn api_run(State(state): State<AppState>, Json(req): Json<RunRequest>) -> impl IntoResponse {
    let tag = req.tag.unwrap_or_else(|| "收盘".to_string());
    let run = execute_run(&state, &tag).await;

    let (status_code, ok) = if run.status == "ok" {
        (StatusCode::OK, true)
    } else {
        (StatusCode::SERVICE_UNAVAILABLE, false)
    };

    (
        status_code,
        Json(RunResponse {
            ok,
            status: run.status.clone(),
            tag,
            duration_ms: run.duration_ms,
            report: run.report,
            error: run.error,
        }),
    )
}

async fn api_trigger(
    State(state): State<AppState>,
    Json(req): Json<RunRequest>,
) -> impl IntoResponse {
    let tag = req.tag.unwrap_or_else(|| "异步刷新".to_string());
    let st = state.clone();
    let tag_bg = tag.clone();
    tokio::spawn(async move {
        let _ = execute_run(&st, &tag_bg).await;
    });
    (
        StatusCode::ACCEPTED,
        Json(TriggerResponse { queued: true, tag }),
    )
}

async fn auto_refresh_loop(state: AppState) {
    let interval_secs: i64 = std::env::var("LOF_AUTO_REFRESH_SECS")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(300);
    let mut last_run_ts: i64 = 0;
    loop {
        let now = Utc::now();
        if is_trading_session(now) {
            let now_ts = now.timestamp();
            if now_ts - last_run_ts >= interval_secs {
                let _ = execute_run(&state, "自动刷新").await;
                last_run_ts = Utc::now().timestamp();
            }
        }
        tokio::time::sleep(Duration::from_secs(15)).await;
    }
}

async fn execute_run(state: &AppState, tag: &str) -> LastRun {
    let _guard = state.run_lock.lock().await;
    let started_at = Utc::now();
    let start = Instant::now();

    let timed = tokio::time::timeout(
        Duration::from_secs(state.timeout_secs),
        run_native_report(&state.http, &state.script_dir, tag),
    )
    .await;

    let (run, board) = match timed {
        Err(_) => (
            LastRun {
                tag: tag.to_string(),
                started_at,
                finished_at: Utc::now(),
                duration_ms: start.elapsed().as_millis(),
                status: "timeout".to_string(),
                report: String::new(),
                error: Some(format!(
                    "native run timed out after {}s",
                    state.timeout_secs
                )),
            },
            None,
        ),
        Ok(Err(e)) => (
            LastRun {
                tag: tag.to_string(),
                started_at,
                finished_at: Utc::now(),
                duration_ms: start.elapsed().as_millis(),
                status: "error".to_string(),
                report: String::new(),
                error: Some(e),
            },
            None,
        ),
        Ok(Ok((report, board))) => (
            LastRun {
                tag: tag.to_string(),
                started_at,
                finished_at: Utc::now(),
                duration_ms: start.elapsed().as_millis(),
                status: "ok".to_string(),
                report,
                error: None,
            },
            Some(board),
        ),
    };

    persist_run(state, run, board).await
}

async fn load_state(path: &Path) -> SidecarState {
    match tokio::fs::read_to_string(path).await {
        Ok(content) => serde_json::from_str::<SidecarState>(&content).unwrap_or_default(),
        Err(_) => SidecarState::default(),
    }
}

async fn save_state(path: &Path, s: &SidecarState) {
    let tmp = path.with_extension("json.tmp");
    if let Ok(content) = serde_json::to_string_pretty(s) {
        let _ = tokio::fs::write(&tmp, content).await;
        let _ = tokio::fs::rename(tmp, path).await;
    }
}

async fn persist_run(state: &AppState, run: LastRun, board: Option<BoardData>) -> LastRun {
    let mut current = load_state(&state.state_file).await;
    current.stats.total_runs += 1;
    match run.status.as_str() {
        "ok" => current.stats.success_runs += 1,
        "timeout" => current.stats.timeout_runs += 1,
        _ => current.stats.error_runs += 1,
    }
    current.last_run = Some(run.clone());
    if let Some(b) = board {
        current.last_board = Some(b);
    }
    save_state(&state.state_file, &current).await;
    run
}
