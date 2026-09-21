use anyhow::{Context, Result};
use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    response::{Html, IntoResponse},
    routing::{get, patch, post},
    Json, Router,
};
use chrono::Utc;
use rusqlite::{params, params_from_iter, Connection, OptionalExtension};
use serde::{Deserialize, Serialize};
use std::{
    collections::HashSet,
    env, fs,
    net::SocketAddr,
    path::PathBuf,
    sync::{Arc, Mutex},
    time::Instant,
};
use tower_http::trace::TraceLayer;

const DEFAULT_SCOPE: &str = "default-nanobot";
const MAX_CONTENT: usize = 4_000;
const MAX_TURN: usize = 8_000;
const MAX_RECALL: usize = 8;

#[derive(Clone)]
struct AppState {
    store: Arc<Mutex<Store>>,
}

struct Store {
    conn: Connection,
}

#[derive(Debug, Clone, Serialize)]
struct MemoryItem {
    id: i64,
    scope: String,
    kind: String,
    content: String,
    status: String,
    source: String,
    channel: String,
    session_key: String,
    confidence: f64,
    pinned: bool,
    created_at: String,
    updated_at: String,
}

#[derive(Debug, Serialize)]
struct RecallItem {
    id: i64,
    kind: String,
    content: String,
    source: String,
    channel: String,
    created_at: String,
    score: f64,
}

#[derive(Debug, Serialize)]
struct RecallResponse {
    hot: Vec<RecallItem>,
    results: Vec<RecallItem>,
    elapsed_ms: u128,
}

#[derive(Debug, Deserialize)]
struct RecallRequest {
    query: String,
    scope: Option<String>,
    session_key: Option<String>,
    limit: Option<usize>,
}

#[derive(Debug, Deserialize)]
struct CreateMemoryRequest {
    content: String,
    scope: Option<String>,
    kind: Option<String>,
    status: Option<String>,
    source: Option<String>,
    channel: Option<String>,
    session_key: Option<String>,
    confidence: Option<f64>,
    pinned: Option<bool>,
}

#[derive(Debug, Deserialize)]
struct UpdateMemoryRequest {
    content: Option<String>,
    status: Option<String>,
    pinned: Option<bool>,
    confidence: Option<f64>,
}

#[derive(Debug, Deserialize)]
struct TurnRequest {
    scope: Option<String>,
    session_key: Option<String>,
    channel: Option<String>,
    user_text: String,
    assistant_text: String,
}

#[derive(Debug, Deserialize)]
struct ListQuery {
    status: Option<String>,
    scope: Option<String>,
    limit: Option<usize>,
    q: Option<String>,
}

#[derive(Debug, Deserialize)]
struct KnowledgeItem {
    id: String,
    title: String,
    source: Option<String>,
    summary: Option<String>,
    keywords: Option<Vec<String>>,
    score: Option<f64>,
    markdown_path: Option<String>,
    created_at: Option<String>,
}
#[derive(Debug, Deserialize)]
struct KnowledgeSyncRequest {
    items: Vec<KnowledgeItem>,
    scope: Option<String>,
}

#[derive(Debug, Serialize)]
struct Stats {
    memories: i64,
    confirmed: i64,
    candidates: i64,
    episodes: i64,
    knowledge: i64,
    imported_legacy: i64,
}

#[tokio::main]
async fn main() -> Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(env::var("RUST_LOG").unwrap_or_else(|_| "info".into()))
        .init();
    let db_path = PathBuf::from(
        env::var("MEMORY_RS_DB")
            .unwrap_or_else(|_| "/root/.nanobot/data/memory-rs/memory.db".into()),
    );
    if let Some(parent) = db_path.parent() {
        fs::create_dir_all(parent)?;
    }
    let legacy_db = env::var("MEMORY_LEGACY_DB")
        .ok()
        .filter(|v| !v.trim().is_empty())
        .map(PathBuf::from);
    let mut store = Store::open(&db_path)?;
    if let Some(path) = legacy_db.as_ref() {
        store.import_legacy(path)?;
    }
    let host = env::var("MEMORY_RS_HOST").unwrap_or_else(|_| "127.0.0.1".into());
    let port: u16 = env::var("MEMORY_RS_PORT")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(8105);
    let state = AppState {
        store: Arc::new(Mutex::new(store)),
    };
    let app = Router::new()
        .route("/", get(dashboard))
        .route("/health", get(health))
        .route("/api/stats", get(stats))
        .route("/api/recall", post(recall))
        .route("/api/turns", post(record_turn))
        .route("/api/memories", get(list_memories).post(create_memory))
        .route(
            "/api/memories/:id",
            patch(update_memory).delete(delete_memory),
        )
        .route("/api/memories/:id/accept", post(accept_memory))
        .route("/api/memories/:id/ignore", post(ignore_memory))
        .route("/api/knowledge", get(list_knowledge).post(sync_knowledge))
        .route("/api/injections", get(list_injections))
        .layer(TraceLayer::new_for_http())
        .with_state(state);
    let addr: SocketAddr = format!("{}:{}", host, port)
        .parse()
        .context("invalid MEMORY_RS_HOST/PORT")?;
    let primary_listener = tokio::net::TcpListener::bind(addr).await?;
    let bridge_host = env::var("MEMORY_RS_BRIDGE_HOST")
        .ok()
        .filter(|value| !value.trim().is_empty());
    if let Some(bridge_host) = bridge_host {
        let bridge_addr: SocketAddr = format!("{}:{}", bridge_host, port)
            .parse()
            .context("invalid MEMORY_RS_BRIDGE_HOST/PORT")?;
        if bridge_addr != addr {
            let bridge_listener = tokio::net::TcpListener::bind(bridge_addr).await?;
            tracing::info!(%addr, %bridge_addr, "memory-rs listening on local and container bridge addresses");
            tokio::select! {
                result = axum::serve(primary_listener, app.clone()) => result?,
                result = axum::serve(bridge_listener, app) => result?,
            }
            return Ok(());
        }
    }
    tracing::info!(%addr, "memory-rs listening");
    axum::serve(primary_listener, app).await?;
    Ok(())
}

impl Store {
    fn open(path: &PathBuf) -> Result<Self> {
        let conn = Connection::open(path)?;
        conn.pragma_update(None, "journal_mode", "WAL")?;
        conn.pragma_update(None, "foreign_keys", "ON")?;
        conn.execute_batch(
            "CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY, scope TEXT NOT NULL, kind TEXT NOT NULL, content TEXT NOT NULL,
                normalized TEXT NOT NULL, status TEXT NOT NULL, source TEXT NOT NULL, channel TEXT NOT NULL,
                session_key TEXT NOT NULL, confidence REAL NOT NULL, pinned INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_dedupe ON memories(scope, normalized, status);
            CREATE INDEX IF NOT EXISTS idx_memory_scope_status ON memories(scope, status, pinned, id DESC);
            CREATE TABLE IF NOT EXISTS episodes (
                id INTEGER PRIMARY KEY, scope TEXT NOT NULL, session_key TEXT NOT NULL, channel TEXT NOT NULL,
                user_text TEXT NOT NULL, assistant_text TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_episode_scope ON episodes(scope, id DESC);
            CREATE TABLE IF NOT EXISTS knowledge (
                id INTEGER PRIMARY KEY, external_id TEXT NOT NULL UNIQUE, scope TEXT NOT NULL, title TEXT NOT NULL,
                source TEXT NOT NULL, summary TEXT NOT NULL, keywords TEXT NOT NULL, score REAL NOT NULL,
                markdown_path TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_knowledge_scope ON knowledge(scope, id DESC);
            CREATE TABLE IF NOT EXISTS ngrams (
                entity TEXT NOT NULL, entity_id INTEGER NOT NULL, gram TEXT NOT NULL,
                PRIMARY KEY(entity, entity_id, gram)
            );
            CREATE INDEX IF NOT EXISTS idx_ngrams_lookup ON ngrams(entity, gram);
            CREATE TABLE IF NOT EXISTS injection_log (
                id INTEGER PRIMARY KEY, scope TEXT NOT NULL, session_key TEXT NOT NULL, query TEXT NOT NULL,
                memory_ids TEXT NOT NULL, elapsed_ms INTEGER NOT NULL, created_at TEXT NOT NULL
            );"
        )?;
        Ok(Self { conn })
    }

    fn now() -> String {
        Utc::now().to_rfc3339()
    }

    fn add_ngrams(&self, entity: &str, id: i64, text: &str) -> Result<()> {
        self.conn.execute(
            "DELETE FROM ngrams WHERE entity=?1 AND entity_id=?2",
            params![entity, id],
        )?;
        let mut grams = ngrams(text);
        if grams.is_empty() {
            grams.insert(normalize(text));
        }
        let tx = self.conn.unchecked_transaction()?;
        for gram in grams.into_iter().take(512) {
            tx.execute(
                "INSERT OR IGNORE INTO ngrams(entity, entity_id, gram) VALUES(?1,?2,?3)",
                params![entity, id, gram],
            )?;
        }
        tx.commit()?;
        Ok(())
    }

    fn create_memory(&self, req: CreateMemoryRequest) -> Result<MemoryItem> {
        let content = clip(&req.content, MAX_CONTENT);
        anyhow::ensure!(!content.is_empty(), "memory content is empty");
        let scope = clean(req.scope.as_deref(), DEFAULT_SCOPE);
        let kind = clean(req.kind.as_deref(), "note");
        let status = clean(req.status.as_deref(), "confirmed");
        let source = clean(req.source.as_deref(), "manual");
        let channel = clean(req.channel.as_deref(), "direct");
        let session_key = clean(req.session_key.as_deref(), "");
        let normalized = normalize(&content);
        let now = Self::now();
        let existing: Option<i64> = self
            .conn
            .query_row(
                "SELECT id FROM memories WHERE scope=?1 AND normalized=?2 AND status=?3",
                params![scope, normalized, status],
                |r| r.get(0),
            )
            .optional()?;
        let id = if let Some(id) = existing {
            self.conn.execute("UPDATE memories SET updated_at=?1, confidence=MAX(confidence, ?2), pinned=MAX(pinned, ?3) WHERE id=?4", params![now, req.confidence.unwrap_or(0.8), req.pinned.unwrap_or(false) as i64, id])?;
            id
        } else {
            self.conn.execute(
                "INSERT INTO memories(scope,kind,content,normalized,status,source,channel,session_key,confidence,pinned,created_at,updated_at) VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?11)",
                params![scope, kind, content, normalized, status, source, channel, session_key, req.confidence.unwrap_or(0.8).clamp(0.0, 1.0), req.pinned.unwrap_or(false) as i64, now],
            )?;
            self.conn.last_insert_rowid()
        };
        self.add_ngrams("memory", id, &content)?;
        self.memory(id)
    }

    fn memory(&self, id: i64) -> Result<MemoryItem> {
        self.conn.query_row("SELECT id,scope,kind,content,status,source,channel,session_key,confidence,pinned,created_at,updated_at FROM memories WHERE id=?1", [id], memory_row).context("memory not found")
    }

    fn list_memories(&self, q: &ListQuery) -> Result<Vec<MemoryItem>> {
        let scope = clean(q.scope.as_deref(), DEFAULT_SCOPE);
        let status = q.status.as_deref().unwrap_or("confirmed");
        let limit = q.limit.unwrap_or(60).clamp(1, 200) as i64;
        if let Some(query) = q.q.as_deref().filter(|v| !v.trim().is_empty()) {
            let ids = self.entity_ids("memory", query, limit as usize * 3)?;
            if ids.is_empty() {
                return Ok(vec![]);
            }
            let marks = placeholders(ids.len());
            let sql = format!("SELECT id,scope,kind,content,status,source,channel,session_key,confidence,pinned,created_at,updated_at FROM memories WHERE scope=? AND status=? AND id IN ({}) ORDER BY pinned DESC, id DESC LIMIT ?", marks);
            let mut values: Vec<rusqlite::types::Value> =
                vec![scope.into(), status.to_string().into()];
            values.extend(ids.into_iter().map(Into::into));
            values.push(limit.into());
            let mut stmt = self.conn.prepare(&sql)?;
            return stmt
                .query_map(params_from_iter(values), memory_row)?
                .collect::<rusqlite::Result<Vec<_>>>()
                .map_err(Into::into);
        }
        let mut stmt = self.conn.prepare("SELECT id,scope,kind,content,status,source,channel,session_key,confidence,pinned,created_at,updated_at FROM memories WHERE scope=?1 AND status=?2 ORDER BY pinned DESC, id DESC LIMIT ?3")?;
        let rows = stmt
            .query_map(params![scope, status, limit], memory_row)?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        Ok(rows)
    }

    fn update_memory(&self, id: i64, req: UpdateMemoryRequest) -> Result<MemoryItem> {
        let old = self.memory(id)?;
        let content = req
            .content
            .as_deref()
            .map(|v| clip(v, MAX_CONTENT))
            .filter(|v| !v.is_empty())
            .unwrap_or(old.content.clone());
        let status = req.status.unwrap_or(old.status);
        let now = Self::now();
        self.conn.execute("UPDATE memories SET content=?1, normalized=?2, status=?3, pinned=?4, confidence=?5, updated_at=?6 WHERE id=?7", params![content, normalize(&content), status, req.pinned.unwrap_or(old.pinned) as i64, req.confidence.unwrap_or(old.confidence).clamp(0.0,1.0), now, id])?;
        self.add_ngrams("memory", id, &content)?;
        self.memory(id)
    }

    fn record_turn(&self, req: TurnRequest) -> Result<()> {
        let user_text = clip(&req.user_text, MAX_TURN);
        let assistant_text = clip(&req.assistant_text, MAX_TURN);
        if user_text.is_empty() || assistant_text.is_empty() {
            return Ok(());
        }
        let scope = clean(req.scope.as_deref(), DEFAULT_SCOPE);
        let session = clean(req.session_key.as_deref(), "");
        let channel = clean(req.channel.as_deref(), "chat");
        let now = Self::now();
        self.conn.execute("INSERT INTO episodes(scope,session_key,channel,user_text,assistant_text,created_at) VALUES(?1,?2,?3,?4,?5,?6)", params![scope, session, channel, user_text, assistant_text, now])?;
        let id = self.conn.last_insert_rowid();
        self.add_ngrams("episode", id, &format!("{} {}", user_text, assistant_text))?;
        if let Some((kind, candidate)) = extract_candidate(&user_text) {
            let _ = self.create_memory(CreateMemoryRequest {
                content: candidate,
                scope: Some(scope),
                kind: Some(kind),
                status: Some("candidate".into()),
                source: Some("conversation-candidate".into()),
                channel: Some(channel),
                session_key: Some(session),
                confidence: Some(0.65),
                pinned: Some(false),
            })?;
        }
        Ok(())
    }

    fn recall(&self, req: &RecallRequest) -> Result<RecallResponse> {
        let began = Instant::now();
        let scope = clean(req.scope.as_deref(), DEFAULT_SCOPE);
        let limit = req.limit.unwrap_or(MAX_RECALL).clamp(1, 12);
        let hot = self.hot(&scope, 4)?;
        let mut results = self.search_memories(&scope, &req.query, limit)?;
        results.extend(self.search_episodes(&scope, &req.query, limit)?);
        results.extend(self.search_knowledge(&scope, &req.query, limit)?);
        results.sort_by(|a, b| {
            b.score
                .partial_cmp(&a.score)
                .unwrap_or(std::cmp::Ordering::Equal)
        });
        results.dedup_by(|a, b| a.kind == b.kind && a.id == b.id);
        results.truncate(limit);
        let ids = results
            .iter()
            .chain(hot.iter())
            .map(|v| format!("{}:{}", v.kind, v.id))
            .collect::<Vec<_>>()
            .join(",");
        self.conn.execute("INSERT INTO injection_log(scope,session_key,query,memory_ids,elapsed_ms,created_at) VALUES(?1,?2,?3,?4,?5,?6)", params![scope, clean(req.session_key.as_deref(), ""), clip(&req.query, 800), ids, began.elapsed().as_millis() as i64, Self::now()])?;
        Ok(RecallResponse {
            hot,
            results,
            elapsed_ms: began.elapsed().as_millis(),
        })
    }

    fn hot(&self, scope: &str, limit: usize) -> Result<Vec<RecallItem>> {
        let mut stmt = self.conn.prepare("SELECT id,kind,content,source,channel,created_at,1.0 FROM memories WHERE scope=?1 AND status='confirmed' ORDER BY pinned DESC, CASE kind WHEN 'preference' THEN 0 WHEN 'decision' THEN 1 ELSE 2 END, id DESC LIMIT ?2")?;
        let rows = stmt
            .query_map(params![scope, limit as i64], recall_row)?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        Ok(rows)
    }

    fn entity_ids(&self, entity: &str, query: &str, limit: usize) -> Result<Vec<i64>> {
        let grams: Vec<String> = ngrams(query).into_iter().take(48).collect();
        if grams.is_empty() {
            return Ok(vec![]);
        }
        let marks = placeholders(grams.len());
        let sql = format!("SELECT entity_id FROM ngrams WHERE entity=? AND gram IN ({}) GROUP BY entity_id ORDER BY COUNT(*) DESC LIMIT ?", marks);
        let mut values: Vec<rusqlite::types::Value> = vec![entity.to_string().into()];
        values.extend(grams.into_iter().map(Into::into));
        values.push((limit as i64).into());
        let mut stmt = self.conn.prepare(&sql)?;
        let rows = stmt
            .query_map(params_from_iter(values), |r| r.get(0))?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        Ok(rows)
    }

    fn search_memories(&self, scope: &str, query: &str, limit: usize) -> Result<Vec<RecallItem>> {
        let ids = self.entity_ids("memory", query, limit * 3)?;
        if ids.is_empty() {
            return Ok(vec![]);
        }
        let marks = placeholders(ids.len());
        let sql = format!("SELECT id,kind,content,source,channel,created_at, CASE status WHEN 'confirmed' THEN 0.95 ELSE 0.35 END FROM memories WHERE scope=? AND status='confirmed' AND id IN ({})", marks);
        let mut vals: Vec<rusqlite::types::Value> = vec![scope.to_string().into()];
        vals.extend(ids.into_iter().map(Into::into));
        let mut stmt = self.conn.prepare(&sql)?;
        let rows = stmt
            .query_map(params_from_iter(vals), recall_row)?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        Ok(rows)
    }

    fn search_episodes(&self, scope: &str, query: &str, limit: usize) -> Result<Vec<RecallItem>> {
        let ids = self.entity_ids("episode", query, limit * 3)?;
        if ids.is_empty() {
            return Ok(vec![]);
        }
        let marks = placeholders(ids.len());
        let sql = format!("SELECT id,'episode',substr(user_text,1,800),channel,channel,created_at,0.55 FROM episodes WHERE scope=? AND id IN ({})", marks);
        let mut vals: Vec<rusqlite::types::Value> = vec![scope.to_string().into()];
        vals.extend(ids.into_iter().map(Into::into));
        let mut stmt = self.conn.prepare(&sql)?;
        let rows = stmt
            .query_map(params_from_iter(vals), recall_row)?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        Ok(rows)
    }

    fn search_knowledge(&self, scope: &str, query: &str, limit: usize) -> Result<Vec<RecallItem>> {
        let ids = self.entity_ids("knowledge", query, limit * 3)?;
        if ids.is_empty() {
            return Ok(vec![]);
        }
        let marks = placeholders(ids.len());
        let sql = format!("SELECT id,'knowledge',title || ': ' || substr(summary,1,700),source,'knowledge-inbox',created_at,0.45 FROM knowledge WHERE scope=? AND id IN ({})", marks);
        let mut vals: Vec<rusqlite::types::Value> = vec![scope.to_string().into()];
        vals.extend(ids.into_iter().map(Into::into));
        let mut stmt = self.conn.prepare(&sql)?;
        let rows = stmt
            .query_map(params_from_iter(vals), recall_row)?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        Ok(rows)
    }

    fn sync_knowledge(&self, request: KnowledgeSyncRequest) -> Result<usize> {
        let scope = clean(request.scope.as_deref(), DEFAULT_SCOPE);
        let mut changed = 0;
        for item in request.items.into_iter().take(2000) {
            if item.id.trim().is_empty() || item.title.trim().is_empty() {
                continue;
            }
            let source = clean(item.source.as_deref(), "knowledge-inbox");
            let summary = clip(item.summary.as_deref().unwrap_or(""), 2_000);
            let keywords = item.keywords.unwrap_or_default().join(" ");
            let now = Self::now();
            self.conn.execute("INSERT INTO knowledge(external_id,scope,title,source,summary,keywords,score,markdown_path,created_at,updated_at) VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9,?10) ON CONFLICT(external_id) DO UPDATE SET title=excluded.title,source=excluded.source,summary=excluded.summary,keywords=excluded.keywords,score=excluded.score,markdown_path=excluded.markdown_path,updated_at=excluded.updated_at", params![item.id, scope, clip(&item.title,500), source, summary, clip(&keywords,1000), item.score.unwrap_or(0.0), clean(item.markdown_path.as_deref(),""), item.created_at.unwrap_or(now.clone()), now])?;
            let id: i64 = self.conn.query_row(
                "SELECT id FROM knowledge WHERE external_id=?1",
                [item.id],
                |r| r.get(0),
            )?;
            let row: (String, String, String) = self.conn.query_row(
                "SELECT title,summary,keywords FROM knowledge WHERE id=?1",
                [id],
                |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
            )?;
            self.add_ngrams("knowledge", id, &format!("{} {} {}", row.0, row.1, row.2))?;
            changed += 1;
        }
        Ok(changed)
    }

    fn import_legacy(&mut self, legacy: &PathBuf) -> Result<i64> {
        if !legacy.exists() {
            return Ok(0);
        }
        let legacy_conn =
            Connection::open_with_flags(legacy, rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY)?;
        let mut stmt = match legacy_conn
            .prepare("SELECT user_id,category,content,source,created_at FROM memories")
        {
            Ok(v) => v,
            Err(_) => return Ok(0),
        };
        let rows = stmt.query_map([], |r| {
            Ok((
                r.get::<_, String>(0)?,
                r.get::<_, String>(1)?,
                r.get::<_, String>(2)?,
                r.get::<_, String>(3)?,
                r.get::<_, String>(4)?,
            ))
        })?;
        let mut imported = 0;
        for row in rows {
            let (scope, kind, content, source, _at) = row?;
            let before = self
                .conn
                .query_row("SELECT COUNT(*) FROM memories", [], |r| r.get::<_, i64>(0))?;
            let _ = self.create_memory(CreateMemoryRequest {
                content,
                scope: Some(if scope.is_empty() {
                    DEFAULT_SCOPE.into()
                } else {
                    scope
                }),
                kind: Some(kind),
                status: Some("confirmed".into()),
                source: Some(format!("legacy-reflexio:{}", source)),
                channel: Some("legacy".into()),
                session_key: Some("".into()),
                confidence: Some(0.9),
                pinned: Some(false),
            })?;
            let after = self
                .conn
                .query_row("SELECT COUNT(*) FROM memories", [], |r| r.get::<_, i64>(0))?;
            imported += after - before;
        }
        Ok(imported)
    }

    fn stats(&self) -> Result<Stats> {
        let count = |sql: &str| self.conn.query_row(sql, [], |r| r.get::<_, i64>(0));
        Ok(Stats {
            memories: count("SELECT COUNT(*) FROM memories WHERE status!='deleted'")?,
            confirmed: count("SELECT COUNT(*) FROM memories WHERE status='confirmed'")?,
            candidates: count("SELECT COUNT(*) FROM memories WHERE status='candidate'")?,
            episodes: count("SELECT COUNT(*) FROM episodes")?,
            knowledge: count("SELECT COUNT(*) FROM knowledge")?,
            imported_legacy: count(
                "SELECT COUNT(*) FROM memories WHERE source LIKE 'legacy-reflexio:%'",
            )?,
        })
    }
}

fn memory_row(r: &rusqlite::Row<'_>) -> rusqlite::Result<MemoryItem> {
    Ok(MemoryItem {
        id: r.get(0)?,
        scope: r.get(1)?,
        kind: r.get(2)?,
        content: r.get(3)?,
        status: r.get(4)?,
        source: r.get(5)?,
        channel: r.get(6)?,
        session_key: r.get(7)?,
        confidence: r.get(8)?,
        pinned: r.get::<_, i64>(9)? != 0,
        created_at: r.get(10)?,
        updated_at: r.get(11)?,
    })
}
fn recall_row(r: &rusqlite::Row<'_>) -> rusqlite::Result<RecallItem> {
    Ok(RecallItem {
        id: r.get(0)?,
        kind: r.get(1)?,
        content: r.get(2)?,
        source: r.get(3)?,
        channel: r.get(4)?,
        created_at: r.get(5)?,
        score: r.get(6)?,
    })
}
fn clean(value: Option<&str>, fallback: &str) -> String {
    value
        .unwrap_or(fallback)
        .trim()
        .chars()
        .take(160)
        .collect::<String>()
}
fn clip(value: &str, limit: usize) -> String {
    value.trim().chars().take(limit).collect()
}
fn normalize(value: &str) -> String {
    value
        .chars()
        .filter(|c| !c.is_whitespace() && !c.is_ascii_punctuation())
        .flat_map(|c| c.to_lowercase())
        .collect()
}
fn ngrams(value: &str) -> HashSet<String> {
    let chars: Vec<char> = normalize(value).chars().collect();
    let mut out = HashSet::new();
    for part in chars.windows(2) {
        out.insert(part.iter().collect());
    }
    if chars.len() == 1 {
        out.insert(chars[0].to_string());
    }
    out
}
fn placeholders(len: usize) -> String {
    std::iter::repeat("?")
        .take(len)
        .collect::<Vec<_>>()
        .join(",")
}
fn extract_candidate(text: &str) -> Option<(String, String)> {
    let text = clip(text, 600);
    if text.len() < 8 || text.contains("http://") || text.contains("https://") {
        return None;
    }
    let hints: Vec<(&str, &[&str])> = vec![
        (
            "preference",
            &[
                "我喜欢",
                "我不喜欢",
                "我希望",
                "我讨厌",
                "我习惯",
                "尽量",
                "不要",
                "优先",
            ],
        ),
        ("decision", &["决定", "以后就", "改成", "默认"]),
    ];
    for (kind, words) in hints {
        if words.iter().any(|v| text.contains(v)) {
            return Some((kind.into(), text));
        }
    }
    None
}

async fn health() -> impl IntoResponse {
    Json(serde_json::json!({"ok":true,"service":"memory-rs"}))
}
async fn dashboard() -> Html<&'static str> {
    Html(include_str!("dashboard.html"))
}
async fn stats(State(state): State<AppState>) -> Result<Json<Stats>, ApiError> {
    Ok(Json(lock(&state)?.stats()?))
}
async fn recall(
    State(state): State<AppState>,
    Json(req): Json<RecallRequest>,
) -> Result<Json<RecallResponse>, ApiError> {
    Ok(Json(lock(&state)?.recall(&req)?))
}
async fn create_memory(
    State(state): State<AppState>,
    Json(req): Json<CreateMemoryRequest>,
) -> Result<(StatusCode, Json<MemoryItem>), ApiError> {
    Ok((StatusCode::CREATED, Json(lock(&state)?.create_memory(req)?)))
}
async fn list_memories(
    State(state): State<AppState>,
    Query(q): Query<ListQuery>,
) -> Result<Json<Vec<MemoryItem>>, ApiError> {
    Ok(Json(lock(&state)?.list_memories(&q)?))
}
async fn update_memory(
    State(state): State<AppState>,
    Path(id): Path<i64>,
    Json(req): Json<UpdateMemoryRequest>,
) -> Result<Json<MemoryItem>, ApiError> {
    Ok(Json(lock(&state)?.update_memory(id, req)?))
}
async fn delete_memory(
    State(state): State<AppState>,
    Path(id): Path<i64>,
) -> Result<Json<MemoryItem>, ApiError> {
    Ok(Json(lock(&state)?.update_memory(
        id,
        UpdateMemoryRequest {
            content: None,
            status: Some("deleted".into()),
            pinned: None,
            confidence: None,
        },
    )?))
}
async fn accept_memory(
    State(state): State<AppState>,
    Path(id): Path<i64>,
) -> Result<Json<MemoryItem>, ApiError> {
    Ok(Json(lock(&state)?.update_memory(
        id,
        UpdateMemoryRequest {
            content: None,
            status: Some("confirmed".into()),
            pinned: None,
            confidence: Some(0.85),
        },
    )?))
}
async fn ignore_memory(
    State(state): State<AppState>,
    Path(id): Path<i64>,
) -> Result<Json<MemoryItem>, ApiError> {
    Ok(Json(lock(&state)?.update_memory(
        id,
        UpdateMemoryRequest {
            content: None,
            status: Some("ignored".into()),
            pinned: None,
            confidence: None,
        },
    )?))
}
async fn record_turn(
    State(state): State<AppState>,
    Json(req): Json<TurnRequest>,
) -> Result<StatusCode, ApiError> {
    lock(&state)?.record_turn(req)?;
    Ok(StatusCode::ACCEPTED)
}
async fn sync_knowledge(
    State(state): State<AppState>,
    Json(req): Json<KnowledgeSyncRequest>,
) -> Result<Json<serde_json::Value>, ApiError> {
    let count = lock(&state)?.sync_knowledge(req)?;
    Ok(Json(serde_json::json!({"ok":true,"synced":count})))
}
async fn list_knowledge(
    State(state): State<AppState>,
    Query(q): Query<ListQuery>,
) -> Result<Json<Vec<serde_json::Value>>, ApiError> {
    let store = lock(&state)?;
    let scope = clean(q.scope.as_deref(), DEFAULT_SCOPE);
    let limit = q.limit.unwrap_or(60).clamp(1, 200) as i64;
    let mut stmt=store.conn.prepare("SELECT id,external_id,title,source,summary,keywords,score,markdown_path,created_at,updated_at FROM knowledge WHERE scope=?1 ORDER BY score DESC,id DESC LIMIT ?2")?;
    let rows=stmt.query_map(params![scope,limit],|r| Ok(serde_json::json!({"id":r.get::<_,i64>(0)?,"external_id":r.get::<_,String>(1)?,"title":r.get::<_,String>(2)?,"source":r.get::<_,String>(3)?,"summary":r.get::<_,String>(4)?,"keywords":r.get::<_,String>(5)?,"score":r.get::<_,f64>(6)?,"markdown_path":r.get::<_,String>(7)?,"created_at":r.get::<_,String>(8)?,"updated_at":r.get::<_,String>(9)?})))?.collect::<rusqlite::Result<Vec<_>>>()?;
    Ok(Json(rows))
}
async fn list_injections(
    State(state): State<AppState>,
) -> Result<Json<Vec<serde_json::Value>>, ApiError> {
    let store = lock(&state)?;
    let mut stmt=store.conn.prepare("SELECT id,scope,session_key,query,memory_ids,elapsed_ms,created_at FROM injection_log ORDER BY id DESC LIMIT 80")?;
    let rows=stmt.query_map([],|r| Ok(serde_json::json!({"id":r.get::<_,i64>(0)?,"scope":r.get::<_,String>(1)?,"session_key":r.get::<_,String>(2)?,"query":r.get::<_,String>(3)?,"memory_ids":r.get::<_,String>(4)?,"elapsed_ms":r.get::<_,i64>(5)?,"created_at":r.get::<_,String>(6)?})))?.collect::<rusqlite::Result<Vec<_>>>()?;
    Ok(Json(rows))
}
fn lock(state: &AppState) -> Result<std::sync::MutexGuard<'_, Store>, ApiError> {
    state
        .store
        .lock()
        .map_err(|_| ApiError::internal("memory database lock poisoned"))
}
#[derive(Debug)]
struct ApiError(anyhow::Error);
impl ApiError {
    fn internal(message: &str) -> Self {
        Self(anyhow::anyhow!(message.to_string()))
    }
}
impl From<anyhow::Error> for ApiError {
    fn from(v: anyhow::Error) -> Self {
        Self(v)
    }
}
impl From<rusqlite::Error> for ApiError {
    fn from(v: rusqlite::Error) -> Self {
        Self(v.into())
    }
}
impl IntoResponse for ApiError {
    fn into_response(self) -> axum::response::Response {
        tracing::warn!(error=%self.0,"memory-rs request failed");
        (
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({"ok":false,"error":self.0.to_string()})),
        )
            .into_response()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn chinese_ngrams_are_searchable() {
        let grams = ngrams("我喜欢广州的天气");
        assert!(grams.contains("喜欢"));
        assert!(grams.contains("广州"));
    }

    #[test]
    fn candidate_filter_ignores_urls() {
        assert!(extract_candidate("我喜欢 https://example.com").is_none());
        assert!(extract_candidate("我希望以后默认用中文回复").is_some());
    }

    #[test]
    fn knowledge_sync_upserts_metadata() {
        let path = std::env::temp_dir().join(format!("memory-rs-test-{}.db", std::process::id()));
        let _ = std::fs::remove_file(&path);
        let store = Store::open(&path).unwrap();
        let request = KnowledgeSyncRequest {
            scope: Some("test".into()),
            items: vec![KnowledgeItem {
                id: "article-1".into(),
                title: "测试文章".into(),
                source: Some("rss".into()),
                summary: Some("只索引摘要".into()),
                keywords: Some(vec!["测试".into()]),
                score: Some(88.0),
                markdown_path: None,
                created_at: None,
            }],
        };
        assert_eq!(store.sync_knowledge(request).unwrap(), 1);
        let count: i64 = store
            .conn
            .query_row(
                "SELECT COUNT(*) FROM knowledge WHERE scope='test'",
                [],
                |row| row.get(0),
            )
            .unwrap();
        assert_eq!(count, 1);
        drop(store);
        let _ = std::fs::remove_file(path);
    }
}
