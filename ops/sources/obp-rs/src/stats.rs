use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::BTreeMap;
use std::fs;
use std::path::Path;
use std::time::{SystemTime, UNIX_EPOCH};

const RECENT_LIMIT: usize = 100;
const SHANGHAI_OFFSET_SECS: i64 = 8 * 60 * 60;

#[derive(Debug, Serialize, Deserialize, Clone, Copy, Default)]
pub struct TokenUsage {
    #[serde(default)]
    pub prompt_tokens: u64,
    #[serde(default)]
    pub completion_tokens: u64,
    #[serde(default)]
    pub total_tokens: u64,
}

impl TokenUsage {
    pub fn from_response_bytes(bytes: &[u8]) -> Self {
        let Ok(value) = serde_json::from_slice::<Value>(bytes) else {
            return Self::default();
        };
        let usage = value.get("usage");
        Self {
            prompt_tokens: json_u64(usage.and_then(|v| v.get("prompt_tokens"))),
            completion_tokens: json_u64(usage.and_then(|v| v.get("completion_tokens"))),
            total_tokens: json_u64(usage.and_then(|v| v.get("total_tokens"))),
        }
    }
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct RequestLog {
    pub ts: i64,
    pub day: String,
    pub time: String,
    pub channel: String,
    pub channel_id: Option<u64>,
    pub model: String,
    pub status: u16,
    pub latency_ms: u64,
    pub latency: String,
    #[serde(default)]
    pub prompt_tokens: u64,
    #[serde(default)]
    pub completion_tokens: u64,
    #[serde(default)]
    pub total_tokens: u64,
}

impl RequestLog {
    pub fn new(
        channel_id: Option<u64>,
        channel: String,
        model: String,
        status: u16,
        latency_ms: u64,
        usage: TokenUsage,
    ) -> Self {
        let ts = now_unix_secs();
        let (day, time) = shanghai_strings(ts);
        Self {
            ts,
            day,
            time,
            channel,
            channel_id,
            model: normalize_key(model, "unknown"),
            status,
            latency_ms,
            latency: format!("{}ms", latency_ms),
            prompt_tokens: usage.prompt_tokens,
            completion_tokens: usage.completion_tokens,
            total_tokens: usage.total_tokens,
        }
    }
}

#[derive(Debug, Serialize, Deserialize, Clone, Default)]
pub struct UsageBucket {
    #[serde(default)]
    pub requests: u64,
    #[serde(default)]
    pub success: u64,
    #[serde(default)]
    pub errors: u64,
    #[serde(default)]
    pub latency_ms: u64,
    #[serde(default)]
    pub prompt_tokens: u64,
    #[serde(default)]
    pub completion_tokens: u64,
    #[serde(default)]
    pub total_tokens: u64,
}

impl UsageBucket {
    fn add(&mut self, log: &RequestLog) {
        self.requests = self.requests.saturating_add(1);
        if (200..400).contains(&log.status) {
            self.success = self.success.saturating_add(1);
        } else {
            self.errors = self.errors.saturating_add(1);
        }
        self.latency_ms = self.latency_ms.saturating_add(log.latency_ms);
        self.prompt_tokens = self.prompt_tokens.saturating_add(log.prompt_tokens);
        self.completion_tokens = self.completion_tokens.saturating_add(log.completion_tokens);
        self.total_tokens = self.total_tokens.saturating_add(log.total_tokens);
    }
}

#[derive(Debug, Serialize, Deserialize, Clone, Default)]
pub struct UsageStats {
    #[serde(default)]
    pub total: UsageBucket,
    #[serde(default)]
    pub by_day: BTreeMap<String, UsageBucket>,
    #[serde(default)]
    pub by_channel: BTreeMap<String, UsageBucket>,
    #[serde(default)]
    pub by_model: BTreeMap<String, UsageBucket>,
    #[serde(default)]
    pub recent: Vec<RequestLog>,
}

impl UsageStats {
    pub fn record(&mut self, log: RequestLog) {
        self.total.add(&log);
        self.by_day.entry(log.day.clone()).or_default().add(&log);
        self.by_channel
            .entry(normalize_key(log.channel.clone(), "unknown-channel"))
            .or_default()
            .add(&log);
        self.by_model
            .entry(normalize_key(log.model.clone(), "unknown-model"))
            .or_default()
            .add(&log);

        self.recent.push(log);
        if self.recent.len() > RECENT_LIMIT {
            let remove = self.recent.len() - RECENT_LIMIT;
            self.recent.drain(0..remove);
        }
    }
}

pub fn load_stats<P: AsRef<Path>>(path: P) -> UsageStats {
    if !path.as_ref().exists() {
        return UsageStats::default();
    }
    let data = fs::read_to_string(path).unwrap_or_default();
    serde_json::from_str(&data).unwrap_or_default()
}

pub fn save_stats<P: AsRef<Path>>(path: P, stats: &UsageStats) {
    let path = path.as_ref();
    if let Some(parent) = path.parent() {
        let _ = fs::create_dir_all(parent);
    }
    let data = serde_json::to_string_pretty(stats).unwrap_or_default();
    let tmp = path.with_extension("json.tmp");
    if fs::write(&tmp, &data).is_ok() && fs::rename(&tmp, path).is_ok() {
        return;
    }
    let _ = fs::write(path, data);
}

fn json_u64(value: Option<&Value>) -> u64 {
    value.and_then(Value::as_u64).unwrap_or(0)
}

fn normalize_key(value: String, fallback: &str) -> String {
    let trimmed = value.trim();
    if trimmed.is_empty() {
        fallback.to_string()
    } else {
        trimmed.to_string()
    }
}

fn now_unix_secs() -> i64 {
    match SystemTime::now().duration_since(UNIX_EPOCH) {
        Ok(duration) => duration.as_secs() as i64,
        Err(_) => 0,
    }
}

fn shanghai_strings(ts: i64) -> (String, String) {
    let adjusted = ts + SHANGHAI_OFFSET_SECS;
    let days = adjusted.div_euclid(86_400);
    let secs = adjusted.rem_euclid(86_400);
    let (year, month, day) = civil_from_days(days);
    let hour = secs / 3_600;
    let minute = (secs % 3_600) / 60;
    let second = secs % 60;
    let day_key = format!("{:04}-{:02}-{:02}", year, month, day);
    let time = format!("{} {:02}:{:02}:{:02}", day_key, hour, minute, second);
    (day_key, time)
}

fn civil_from_days(days: i64) -> (i32, u32, u32) {
    let z = days + 719_468;
    let era = if z >= 0 { z } else { z - 146_096 } / 146_097;
    let doe = z - era * 146_097;
    let yoe = (doe - doe / 1_460 + doe / 36_524 - doe / 146_096) / 365;
    let mut year = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = doy - (153 * mp + 2) / 5 + 1;
    let month = mp + if mp < 10 { 3 } else { -9 };
    if month <= 2 {
        year += 1;
    }
    (year as i32, month as u32, day as u32)
}
