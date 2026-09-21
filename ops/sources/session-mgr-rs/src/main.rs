mod types;
mod store;

use axum::extract::{Query, State};
use axum::response::Json;
use axum::routing::get;
use axum::Router;
use serde_json::json;
use std::net::SocketAddr;
use std::sync::Arc;

use crate::store::SessionStore;

struct AppState {
    store: SessionStore,
}

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt::init();

    let session_dir = std::env::var("SESSION_MGR_DIR")
        .unwrap_or_else(|_| types::DEFAULT_SESSION_DIR.to_string());
    let port: u16 = std::env::var("SESSION_MGR_PORT")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(8096);

    let state = Arc::new(AppState {
        store: SessionStore::new(&session_dir),
    });

    let app = Router::new()
        .route("/health", get(health))
        .route("/usage", get(get_usage))
        .route("/insights", get(get_insights))
        .with_state(state);

    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    tracing::info!("session-mgr-rs listening on {}", addr);
    let listener = tokio::net::TcpListener::bind(addr)
        .await
        .expect("bind failed");
    axum::serve(listener, app).await.expect("server failed");
}

async fn health() -> Json<serde_json::Value> {
    Json(json!({"ok": true, "service": "session-mgr-rs"}))
}

async fn get_usage(State(state): State<Arc<AppState>>) -> Json<types::UsageResponse> {
    Json(state.store.usage())
}

async fn get_insights(
    State(state): State<Arc<AppState>>,
    Query(params): Query<types::InsightQuery>,
) -> Json<types::InsightResponse> {
    let limit = params.limit.unwrap_or(20).clamp(1, 100);
    Json(state.store.search(&params.q, limit))
}
