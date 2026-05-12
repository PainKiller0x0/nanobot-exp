use serde::Serialize;
use serde_json::{json, Value};
use std::{fs, path::PathBuf};

const LLM_COST_POLICY: &str = "free_only";
const LLM_AD_ROUTE_ON: &str = "free_longcat";
const LLM_AD_ROUTE_OFF: &str = "off";
pub(crate) const FREE_LLM_ERROR: &str =
    "RSS sidecar only allows free LongCat-Flash-Lite for automatic LLM checks";

#[derive(Clone, Default)]
pub(crate) struct LlmSettings {
    pub(crate) enabled: bool,
    pub(crate) api_base: String,
    pub(crate) api_key: String,
    pub(crate) model: String,
}

impl LlmSettings {
    pub(crate) fn configured(&self) -> bool {
        !self.api_base.trim().is_empty()
            && !self.api_key.trim().is_empty()
            && !self.model.trim().is_empty()
    }

    pub(crate) fn free_allowed(&self) -> bool {
        let base = self.api_base.to_lowercase();
        let model = self.model.to_lowercase();
        base.contains("longcat") && model.contains("longcat-flash-lite")
    }

    pub(crate) fn enabled(&self) -> bool {
        self.enabled && self.configured() && self.free_allowed()
    }

    pub(crate) fn with_payload(mut self, payload: &Value, preserve_masked_key: bool) -> Self {
        if let Some(v) = payload.get("enabled").and_then(|v| v.as_bool()) {
            self.enabled = v;
        }
        if let Some(v) = payload.get("api_base").and_then(|v| v.as_str()) {
            self.api_base = v.trim().to_string();
        }
        if let Some(v) = payload.get("api_key").and_then(|v| v.as_str()) {
            let incoming = v.trim();
            if !preserve_masked_key || (!incoming.is_empty() && !is_masked_secret(incoming)) {
                self.api_key = incoming.to_string();
            }
        }
        if let Some(v) = payload.get("model").and_then(|v| v.as_str()) {
            self.model = v.trim().to_string();
        }
        self
    }

    pub(crate) fn public_json(&self) -> Value {
        json!({
            "enabled": self.enabled,
            "api_base": self.api_base,
            "api_key": masked_secret(&self.api_key),
            "api_key_present": !self.api_key.trim().is_empty(),
            "model": self.model,
            "cost_policy": LLM_COST_POLICY,
            "auto_active": self.enabled(),
        })
    }

    pub(crate) fn stored_json(&self) -> Value {
        json!({
            "enabled": self.enabled,
            "api_base": self.api_base,
            "api_key": self.api_key,
            "model": self.model,
            "cost_policy": LLM_COST_POLICY,
        })
    }

    pub(crate) fn chat_completions_url(&self) -> String {
        let mut url = self.api_base.trim_end_matches('/').to_string();
        if !url.ends_with("/chat/completions") {
            url.push_str("/chat/completions");
        }
        url
    }

    pub(crate) fn ad_route_note(&self) -> &'static str {
        if self.enabled() {
            LLM_AD_ROUTE_ON
        } else {
            LLM_AD_ROUTE_OFF
        }
    }
}

#[derive(Debug, Clone)]
pub(crate) struct AutoRefreshConfig {
    pub(crate) enabled: bool,
    pub(crate) interval_seconds: i64,
}

impl Default for AutoRefreshConfig {
    fn default() -> Self {
        Self {
            enabled: true,
            interval_seconds: 3600,
        }
    }
}

#[derive(Debug, Clone, Serialize)]
pub(crate) struct AutoRefreshRuntime {
    pub(crate) thread_alive: bool,
    pub(crate) running: bool,
    pub(crate) last_run_at: Option<String>,
    pub(crate) next_run_at: Option<String>,
    pub(crate) last_status: String,
    pub(crate) last_message: String,
}

impl Default for AutoRefreshRuntime {
    fn default() -> Self {
        Self {
            thread_alive: false,
            running: false,
            last_run_at: None,
            next_run_at: None,
            last_status: "idle".to_string(),
            last_message: String::new(),
        }
    }
}

pub(crate) fn read_settings(path: &PathBuf) -> Value {
    match fs::read_to_string(path) {
        Ok(s) => serde_json::from_str(&s).unwrap_or_else(|_| json!({})),
        Err(_) => json!({}),
    }
}

pub(crate) fn load_llm_settings_compat(path: &PathBuf) -> LlmSettings {
    let settings = read_settings(path);
    let root = settings.as_object().cloned().unwrap_or_default();
    let llm_obj = settings
        .get("llm")
        .and_then(|v| v.as_object())
        .cloned()
        .unwrap_or_default();

    let get_field = |name: &str| -> String {
        root.get(name)
            .and_then(|v| v.as_str())
            .or_else(|| llm_obj.get(name).and_then(|v| v.as_str()))
            .unwrap_or("")
            .to_string()
    };

    let enabled = root
        .get("llm_enabled")
        .and_then(|v| v.as_bool())
        .or_else(|| llm_obj.get("enabled").and_then(|v| v.as_bool()))
        .unwrap_or(false);
    LlmSettings {
        enabled,
        api_base: get_field("api_base"),
        api_key: get_field("api_key"),
        model: get_field("model"),
    }
}

pub(crate) fn load_auto_refresh_config(path: &PathBuf) -> AutoRefreshConfig {
    let settings = read_settings(path);
    let enabled = settings
        .get("auto_refresh_enabled")
        .and_then(|v| v.as_bool())
        .unwrap_or(true);
    let seconds = settings
        .get("auto_refresh_seconds")
        .and_then(|v| v.as_i64())
        .or_else(|| {
            settings
                .get("auto_refresh_minutes")
                .and_then(|v| v.as_i64())
                .map(|m| m * 60)
        })
        .unwrap_or(3600)
        .clamp(5, 86400);
    AutoRefreshConfig {
        enabled,
        interval_seconds: seconds,
    }
}

pub(crate) fn write_settings(path: &PathBuf, data: &Value) -> Result<(), String> {
    let payload = serde_json::to_string_pretty(data).map_err(|e| e.to_string())?;
    fs::write(path, payload).map_err(|e| e.to_string())
}

fn masked_secret(value: &str) -> String {
    if value.trim().is_empty() {
        String::new()
    } else {
        "********".to_string()
    }
}

fn is_masked_secret(value: &str) -> bool {
    let v = value.trim();
    !v.is_empty() && v.chars().all(|c| c == '*')
}
