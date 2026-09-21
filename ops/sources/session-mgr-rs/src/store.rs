use crate::types::*;
use std::fs;
use std::path::PathBuf;
use std::time::SystemTime;

pub struct SessionStore {
    pub session_dir: PathBuf,
}

impl SessionStore {
    pub fn new(dir: &str) -> Self {
        Self { session_dir: PathBuf::from(dir) }
    }

    pub fn list_session_files(&self) -> Vec<PathBuf> {
        let Ok(entries) = fs::read_dir(&self.session_dir) else { return vec![]; };
        let mut files: Vec<PathBuf> = entries
            .filter_map(|e| e.ok())
            .filter(|e| e.path().extension().map(|ext| ext == "jsonl").unwrap_or(false))
            .map(|e| e.path())
            .filter(|p| p.file_name().and_then(|n| n.to_str()).map(|n| !n.starts_with(CRON_PREFIX)).unwrap_or(false))
            .collect();
        files.sort_by(|a, b| {
            let a_md = a.metadata().ok().and_then(|m| m.modified().ok()).unwrap_or(SystemTime::UNIX_EPOCH);
            let b_md = b.metadata().ok().and_then(|m| m.modified().ok()).unwrap_or(SystemTime::UNIX_EPOCH);
            b_md.cmp(&a_md)
        });
        files
    }

    pub fn usage(&self) -> UsageResponse {
        let files = self.list_session_files();
        let mut total_messages: u64 = 0;
        let mut user_messages: u64 = 0;
        let mut assistant_messages: u64 = 0;
        let mut tool_calls: u64 = 0;
        let mut total_latency_ms: u64 = 0;
        let mut sessions: Vec<SessionSummary> = Vec::new();
        let mut errors: Vec<String> = Vec::new();

        for path in &files {
            let content = match fs::read_to_string(path) {
                Ok(c) => c,
                Err(e) => { errors.push(format!("read {}: {}", path.display(), e)); continue; }
            };
            let mut metadata = SessionMetadata::default();
            let mut message_count = 0;
            let mut sess_user = 0;
            let mut sess_assistant = 0;

            for line in content.lines() {
                if line.trim().is_empty() { continue; }
                if let Ok(entry) = serde_json::from_str::<SessionLine>(line) {
                    if entry.role.is_none() && line.contains("_type") {
                        if let Ok(m) = serde_json::from_str::<SessionMetadata>(line) { metadata = m; }
                        continue;
                    }
                    message_count += 1;
                    total_messages += 1;
                    match entry.role.as_deref() {
                        Some("user") => { user_messages += 1; sess_user += 1; }
                        Some("assistant") => { assistant_messages += 1; sess_assistant += 1; }
                        Some("tool") => { tool_calls += 1; }
                        _ => {}
                    }
                    if let Some(lat) = entry.latency_ms { total_latency_ms += lat; }
                } else {
                    errors.push(format!("parse {}: {}", path.display(), line.chars().take(80).collect::<String>()));
                }
            }
            if message_count > 0 {
                let key = path.file_stem().and_then(|s| s.to_str()).unwrap_or("?").to_string();
                sessions.push(SessionSummary { key, created_at: metadata.created_at, updated_at: metadata.updated_at, message_count, user_messages: sess_user, assistant_messages: sess_assistant });
            }
        }
        UsageResponse { ok: true, total_sessions: sessions.len(), total_messages, user_messages, assistant_messages, tool_calls, total_latency_ms, model_breakdown: vec![], sessions, errors }
    }

    pub fn search(&self, query: &str, limit: usize) -> InsightResponse {
        let files = self.list_session_files();
        let q = query.to_lowercase();
        let mut matches = Vec::new();
        for path in &files {
            let Ok(content) = fs::read_to_string(path) else { continue; };
            let fname = path.file_stem().and_then(|s| s.to_str()).unwrap_or("?").to_string();
            for line in content.lines() {
                if line.trim().is_empty() { continue; }
                if !line.to_lowercase().contains(&q) { continue; }
                let role = serde_json::from_str::<SessionLine>(line).ok().and_then(|e| e.role).unwrap_or_default();
                let content_preview = serde_json::from_str::<SessionLine>(line).ok().and_then(|e| e.content).unwrap_or_default();
                matches.push(InsightMatch { session: fname.clone(), role, content_preview: content_preview.chars().take(200).collect(), preview_len: content_preview.len() });
                if matches.len() >= limit { break; }
            }
            if matches.len() >= limit { break; }
        }
        InsightResponse { ok: true, query: query.to_string(), total_matches: matches.len(), matches }
    }
}
