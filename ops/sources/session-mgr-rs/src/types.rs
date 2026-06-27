use serde::{Deserialize, Serialize};

pub const DEFAULT_SESSION_DIR: &str = "/root/.nanobot/workspace/sessions";
pub const CRON_PREFIX: &str = "cron_";

/// One line in a .jsonl session file
#[derive(Debug, Deserialize)]
pub struct SessionLine {
    pub role: Option<String>,
    pub content: Option<String>,
    #[serde(default)]
    pub tool_calls: Option<serde_json::Value>,
    pub name: Option<String>,
    pub latency_ms: Option<u64>,
    pub timestamp: Option<String>,
}

/// Parsed session metadata from the _type=metadata line
#[derive(Debug, Deserialize, Default)]
pub struct SessionMetadata {
    #[serde(rename = "_type")]
    pub type_field: Option<String>,
    pub key: Option<String>,
    pub created_at: Option<String>,
    pub updated_at: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct ModelStat {
    pub model: String,
    pub count: u64,
    pub total_latency_ms: u64,
    pub avg_latency_ms: u64,
}

#[derive(Debug, Clone, Serialize)]
pub struct SessionSummary {
    pub key: String,
    pub created_at: Option<String>,
    pub updated_at: Option<String>,
    pub message_count: usize,
    pub user_messages: usize,
    pub assistant_messages: usize,
}

#[derive(Debug, Serialize)]
pub struct UsageResponse {
    pub ok: bool,
    pub total_sessions: usize,
    pub total_messages: u64,
    pub user_messages: u64,
    pub assistant_messages: u64,
    pub tool_calls: u64,
    pub total_latency_ms: u64,
    pub model_breakdown: Vec<ModelStat>,
    pub sessions: Vec<SessionSummary>,
    pub errors: Vec<String>,
}

#[derive(Debug, Serialize)]
pub struct InsightResponse {
    pub ok: bool,
    pub query: String,
    pub total_matches: usize,
    pub matches: Vec<InsightMatch>,
}

#[derive(Debug, Serialize)]
pub struct InsightMatch {
    pub session: String,
    pub role: String,
    pub content_preview: String,
    pub preview_len: usize,
}

#[derive(Debug, Deserialize)]
pub struct InsightQuery {
    pub q: String,
    pub limit: Option<usize>,
}
