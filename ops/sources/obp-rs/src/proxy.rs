use crate::config::{save_config, Channel, RouterConfig};
use crate::stats::{save_stats, RequestLog, TokenUsage, UsageStats};
use axum::{
    body::{to_bytes, Body},
    extract::State,
    http::{header, HeaderMap, HeaderName, Request, Response, StatusCode},
    response::IntoResponse,
};
use reqwest::{Body as ReqBody, Client};
use serde_json::Value;
use std::sync::Arc;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use tokio::sync::Mutex;

use crate::protocol::{rewrite_body_for_upstream, rewrite_response_for_client, ApiProtocol};
const MAX_REQUEST_BYTES: usize = 16 * 1024 * 1024;

pub struct ProxyState {
    pub client: Client,
    pub channels: Mutex<Vec<Channel>>,
    pub router: Mutex<RouterConfig>,
    pub stats: Mutex<UsageStats>,
    pub index: Mutex<usize>,
    pub config_path: String,
    pub router_path: String,
    pub stats_path: String,
}

#[derive(Debug, Clone)]
struct RouteDecision {
    requested_model: String,
    desired_model: String,
    role: String,
    group: String,
    reason: String,
}

#[derive(Debug, Clone)]
struct Attempt {
    channel: Channel,
    actual_model: String,
    role: String,
    group: String,
    reason: String,
}

#[derive(Debug, Clone, Default)]
struct RouteHints {
    purpose: String,
    intent: String,
}

impl RouteHints {
    fn from_request(headers: &HeaderMap, request_json: Option<&Value>) -> Self {
        Self {
            purpose: first_non_empty(&[
                header_hint(headers, "x-obp-purpose"),
                json_hint(request_json, &["obp_purpose", "x_obp_purpose", "purpose"]),
            ]),
            intent: first_non_empty(&[
                header_hint(headers, "x-obp-intent"),
                json_hint(request_json, &["obp_intent", "x_obp_intent", "intent"]),
            ]),
        }
    }

    fn pro_reason(&self) -> Option<String> {
        for (label, value) in [
            ("purpose", self.purpose.as_str()),
            ("intent", self.intent.as_str()),
        ] {
            if hint_matches(value, PRO_HINTS) {
                return Some(format!("{} hint matched: {}", label, value));
            }
        }
        None
    }

    fn light_reason(&self) -> Option<String> {
        for (label, value) in [
            ("purpose", self.purpose.as_str()),
            ("intent", self.intent.as_str()),
        ] {
            if hint_matches(value, LIGHTWEIGHT_HINTS) {
                return Some(format!("{} hint keeps default: {}", label, value));
            }
        }
        None
    }
}

fn request_source(headers: &HeaderMap, request_json: Option<&Value>) -> String {
    let source = first_non_empty(&[
        header_hint(headers, "x-obp-source"),
        header_hint(headers, "x-nanobot-source"),
        json_hint(request_json, &["obp_source", "x_obp_source", "source"]),
    ]);
    sanitize_source(&source)
}

fn sanitize_source(source: &str) -> String {
    let cleaned: String = source
        .chars()
        .map(|ch| {
            if ch.is_ascii_alphanumeric() || matches!(ch, '-' | '_' | '.' | ':') {
                ch
            } else {
                '-'
            }
        })
        .collect();
    let trimmed = cleaned.trim_matches('-').trim();
    if trimmed.is_empty() {
        "unknown-source".to_string()
    } else {
        trimmed.chars().take(80).collect()
    }
}

fn effective_request_source(source: String, decision: &RouteDecision) -> String {
    if source != "unknown-source" {
        return source;
    }
    if is_internal_free_longcat_reason(&decision.reason) {
        return "default-nanobot-internal".to_string();
    }
    source
}

fn is_internal_free_longcat_reason(reason: &str) -> bool {
    let lower = reason.to_lowercase();
    lower.starts_with("free longcat") && lower.contains("heartbeat")
}

const PRO_HINTS: &[&str] = &[
    "compact",
    "compression",
    "summarize",
    "summary",
    "memory",
    "reflection",
    "reflexio",
    "dream",
    "review",
    "code_review",
    "architecture",
    "design",
    "migration",
    "reasoning",
    "analysis",
    "diagnose",
    "troubleshoot",
    "root_cause",
];

const LIGHTWEIGHT_HINTS: &[&str] = &[
    "status",
    "health",
    "weather",
    "cron",
    "schedule",
    "lof",
    "rss",
    "quote",
    "simple",
    "simple_chat",
    "fast_chat",
];

const FREE_LONGCAT_TEXT_PATTERNS: &[&str] = &[
    "heartbeat.md",
    "heartbeat agent",
    "heartbeat tool",
    "\"name\":\"heartbeat\"",
    "\"name\": \"heartbeat\"",
];

const CHANNEL_COOLDOWN_SECS: u64 = 120;

fn free_longcat_trigger(hints: &RouteHints, routing_text: &str) -> Option<String> {
    for (label, value) in [
        ("purpose", hints.purpose.as_str()),
        ("intent", hints.intent.as_str()),
    ] {
        if hint_matches(
            value,
            &["heartbeat", "healthcheck", "self_check", "self-check"],
        ) {
            return Some(format!("{} hint matched: {}", label, value));
        }
    }
    FREE_LONGCAT_TEXT_PATTERNS
        .iter()
        .find(|pattern| routing_text.contains(**pattern))
        .map(|pattern| (*pattern).to_string())
}

fn unix_now_secs() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_else(|_| Duration::from_secs(0))
        .as_secs()
}

const LIGHTWEIGHT_TEXT_PATTERNS: &[&str] = &[
    "heartbeat.md",
    "heartbeat agent",
    "heartbeat tool",
    "\"name\":\"heartbeat\"",
    "\"name\": \"heartbeat\"",
];

const PRO_TEXT_PATTERNS: &[&str] = &[
    "context compression",
    "context summary",
    "conversation summary",
    "memory consolidation",
    "compact conversation",
    "summarize conversation",
    "summarize this conversation",
    "summarize the conversation",
    "conversation so far",
    "consolidate memory",
    "code review",
    "review existing",
    "root cause",
    "上下文压缩",
    "压缩上下文",
    "总结对话",
    "对话总结",
    "记忆整理",
    "代码审查",
    "根因",
    "排障",
];

pub async fn handle_openai_proxy(
    State(state): State<Arc<ProxyState>>,
    req: Request<Body>,
) -> Response<Body> {
    handle_proxy(State(state), req, ApiProtocol::OpenAI).await
}

pub async fn handle_anthropic_proxy(
    State(state): State<Arc<ProxyState>>,
    req: Request<Body>,
) -> Response<Body> {
    handle_proxy(State(state), req, ApiProtocol::Anthropic).await
}

async fn handle_proxy(
    State(state): State<Arc<ProxyState>>,
    req: Request<Body>,
    protocol: ApiProtocol,
) -> Response<Body> {
    let started = Instant::now();
    let (parts, body) = req.into_parts();
    let body_bytes = match to_bytes(body, MAX_REQUEST_BYTES).await {
        Ok(bytes) => bytes,
        Err(e) => {
            return (
                StatusCode::BAD_REQUEST,
                format!("Invalid request body: {}", e),
            )
                .into_response();
        }
    };

    let request_json = serde_json::from_slice::<Value>(&body_bytes).ok();
    let requested_model = request_json
        .as_ref()
        .and_then(|v| v.get("model"))
        .and_then(Value::as_str)
        .unwrap_or("unknown")
        .to_string();
    let stream = request_json
        .as_ref()
        .and_then(|v| v.get("stream"))
        .and_then(Value::as_bool)
        .unwrap_or(false);
    let route_hints = RouteHints::from_request(&parts.headers, request_json.as_ref());
    let source = request_source(&parts.headers, request_json.as_ref());

    let router = state.router.lock().await.clone();
    if !router.external_enabled {
        return error_response(StatusCode::FORBIDDEN, "external_access_disabled");
    }
    if !external_model_allowed(&router, &requested_model) {
        return error_response(
            StatusCode::FORBIDDEN,
            &format!("model_not_allowed: {}", requested_model),
        );
    }

    let channels = state.channels.lock().await.clone();
    if channels.is_empty() {
        return (StatusCode::NOT_FOUND, "No channels available").into_response();
    }
    let stats = state.stats.lock().await.clone();
    let decision = route_decision(
        &router,
        &stats,
        request_json.as_ref(),
        &requested_model,
        &route_hints,
    );
    let source = effective_request_source(source, &decision);
    let attempts = build_attempts(&state, &channels, &router, &decision, protocol).await;
    if attempts.is_empty() {
        record_failure(
            &state,
            None,
            requested_model,
            decision.desired_model,
            decision.role,
            decision.reason,
            StatusCode::NOT_FOUND.as_u16(),
            started.elapsed(),
            &source,
        )
        .await;
        return (StatusCode::NOT_FOUND, "No active channels available").into_response();
    }

    let retry_statuses = router.retry_statuses.clone();
    let mut last_error: Option<Response<Body>> = None;
    for (attempt_idx, attempt) in attempts.iter().enumerate() {
        let Some(upstream_protocol) = ApiProtocol::from_channel(&attempt.channel) else {
            continue;
        };
        if stream && protocol != upstream_protocol {
            continue;
        }
        let target_url = upstream_protocol.target_url(&attempt.channel.base);
        let attempt_body = rewrite_body_for_upstream(
            &body_bytes,
            &attempt.actual_model,
            protocol,
            upstream_protocol,
        );
        let mut target_req = state
            .client
            .post(&target_url)
            .body(ReqBody::from(attempt_body));

        for (name, value) in parts.headers.iter() {
            if name != "host"
                && name != "authorization"
                && name != "content-length"
                && !name.as_str().eq_ignore_ascii_case("x-api-key")
                && !name.as_str().to_ascii_lowercase().starts_with("x-obp-")
            {
                target_req = target_req.header(name, value);
            }
        }
        target_req = upstream_protocol.apply_channel_auth(target_req, &attempt.channel);

        let response = match target_req.send().await {
            Ok(res) => res,
            Err(e) => {
                record_result(
                    &state,
                    &attempt.channel,
                    &decision.requested_model,
                    &attempt.actual_model,
                    &attempt.role,
                    &format!("{}; upstream error: {}", attempt.reason, e),
                    StatusCode::BAD_GATEWAY.as_u16(),
                    started.elapsed(),
                    TokenUsage::default(),
                    &source,
                )
                .await;
                continue;
            }
        };

        let status = StatusCode::from_u16(response.status().as_u16())
            .unwrap_or(StatusCode::INTERNAL_SERVER_ERROR);
        let status_u16 = status.as_u16();
        let retryable = retry_statuses.contains(&status_u16);

        if stream {
            if retryable && attempt_idx + 1 < attempts.len() {
                record_result(
                    &state,
                    &attempt.channel,
                    &decision.requested_model,
                    &attempt.actual_model,
                    &attempt.role,
                    &format!("{}; retryable status {}", attempt.reason, status_u16),
                    status_u16,
                    started.elapsed(),
                    TokenUsage::default(),
                    &source,
                )
                .await;
                continue;
            }
            record_result(
                &state,
                &attempt.channel,
                &decision.requested_model,
                &attempt.actual_model,
                &attempt.role,
                &attempt.reason,
                status_u16,
                started.elapsed(),
                TokenUsage::default(),
                &source,
            )
            .await;
            let mut res_builder = response_with_headers(status, response.headers());
            res_builder = route_headers(res_builder, attempt, &decision, &source);
            let res_stream = response.bytes_stream();
            return res_builder
                .body(Body::from_stream(res_stream))
                .unwrap_or_else(|_| {
                    (StatusCode::INTERNAL_SERVER_ERROR, "Internal Error").into_response()
                });
        }

        let headers = response.headers().clone();
        let response_bytes = match response.bytes().await {
            Ok(bytes) => bytes,
            Err(e) => {
                record_result(
                    &state,
                    &attempt.channel,
                    &decision.requested_model,
                    &attempt.actual_model,
                    &attempt.role,
                    &format!("{}; body error: {}", attempt.reason, e),
                    StatusCode::BAD_GATEWAY.as_u16(),
                    started.elapsed(),
                    TokenUsage::default(),
                    &source,
                )
                .await;
                continue;
            }
        };
        let response_bytes =
            rewrite_response_for_client(&response_bytes, status, protocol, upstream_protocol);
        let usage = TokenUsage::from_response_bytes(&response_bytes);
        record_result(
            &state,
            &attempt.channel,
            &decision.requested_model,
            &attempt.actual_model,
            &attempt.role,
            &attempt.reason,
            status_u16,
            started.elapsed(),
            usage,
            &source,
        )
        .await;

        let mut res_builder = if protocol == upstream_protocol {
            response_with_headers(status, &headers)
        } else {
            Response::builder()
                .status(status)
                .header(header::CONTENT_TYPE, "application/json; charset=utf-8")
        };
        res_builder = route_headers(res_builder, attempt, &decision, &source);
        let response = res_builder
            .body(Body::from(response_bytes.clone()))
            .unwrap_or_else(|_| {
                (StatusCode::INTERNAL_SERVER_ERROR, "Internal Error").into_response()
            });

        if retryable && attempt_idx + 1 < attempts.len() {
            last_error = Some(response);
            continue;
        }
        return response;
    }

    last_error.unwrap_or_else(|| {
        (
            StatusCode::BAD_GATEWAY,
            "All OBP upstream attempts failed".to_string(),
        )
            .into_response()
    })
}

fn error_response(status: StatusCode, message: &str) -> axum::response::Response {
    (
        status,
        [("content-type", "application/json; charset=utf-8")],
        serde_json::json!({
            "error": {
                "message": message,
                "type": "obp_router_error",
            }
        })
        .to_string(),
    )
        .into_response()
}

fn external_model_allowed(router: &RouterConfig, model: &str) -> bool {
    let allowed = &router.external_allowed_models;
    if allowed.is_empty() {
        return true;
    }
    let target = model.trim().to_lowercase();
    allowed
        .iter()
        .map(|item| item.trim())
        .filter(|item| !item.is_empty())
        .any(|pattern| model_pattern_matches(pattern, &target))
}

fn model_pattern_matches(pattern: &str, model: &str) -> bool {
    let pattern = pattern.to_lowercase();
    if pattern == "*" {
        return true;
    }
    if !pattern.contains('*') {
        return pattern == model;
    }
    let parts: Vec<&str> = pattern.split('*').filter(|part| !part.is_empty()).collect();
    if parts.is_empty() {
        return true;
    }
    let mut rest = model;
    for part in parts {
        let Some(idx) = rest.find(part) else {
            return false;
        };
        rest = &rest[idx + part.len()..];
    }
    true
}

fn route_decision(
    router: &RouterConfig,
    stats: &UsageStats,
    request_json: Option<&Value>,
    requested_model: &str,
    hints: &RouteHints,
) -> RouteDecision {
    if !router.enabled {
        return RouteDecision {
            requested_model: requested_model.to_string(),
            desired_model: requested_model.to_string(),
            role: "any".to_string(),
            group: String::new(),
            reason: "router disabled".to_string(),
        };
    }

    let free_routing_text = request_json
        .map(extract_routing_text)
        .unwrap_or_default()
        .to_lowercase();
    if let Some(pattern) = free_longcat_trigger(hints, &free_routing_text) {
        let mut decision = RouteDecision {
            requested_model: requested_model.to_string(),
            desired_model: router.emergency_model.clone(),
            role: "emergency".to_string(),
            group: group_for_role(router, "emergency"),
            reason: format!("free longcat task pattern matched: {}", pattern),
        };
        if router.dry_run {
            decision.reason = format!(
                "dry-run: would use {}/{} because {}",
                decision.role, decision.desired_model, decision.reason
            );
            decision.desired_model = requested_model.to_string();
            decision.role = "any".to_string();
            decision.group.clear();
        }
        return decision;
    }

    let monthly_cost = stats.current_month_cost();
    if router.monthly_hard_limit_rmb > 0.0 && monthly_cost >= router.monthly_hard_limit_rmb {
        let mut decision = RouteDecision {
            requested_model: requested_model.to_string(),
            desired_model: router.backup_model.clone(),
            role: "backup".to_string(),
            group: group_for_role(router, "backup"),
            reason: format!("monthly hard limit reached {:.2} CNY", monthly_cost),
        };
        if router.dry_run {
            decision.reason = format!(
                "dry-run: would use {}/{} because {}",
                decision.role, decision.desired_model, decision.reason
            );
            decision.desired_model = requested_model.to_string();
            decision.role = "any".to_string();
            decision.group.clear();
        }
        return decision;
    }

    if let Some(decision) = explicit_model_route(router, requested_model) {
        return decision;
    }

    let explicit_pro = contains_any(&requested_model.to_lowercase(), &["pro", "reasoner"]);
    let routing_text = request_json
        .map(extract_routing_text)
        .unwrap_or_default()
        .to_lowercase();
    let pro_text_hit = PRO_TEXT_PATTERNS
        .iter()
        .find(|pattern| routing_text.contains(**pattern))
        .map(|pattern| (*pattern).to_string());
    let light_text_hit = LIGHTWEIGHT_TEXT_PATTERNS
        .iter()
        .find(|pattern| routing_text.contains(**pattern))
        .map(|pattern| (*pattern).to_string());
    let keyword_hit = router
        .pro_keywords
        .iter()
        .find(|keyword| routing_text.contains(&keyword.to_lowercase()))
        .cloned();

    let mut wants_pro = explicit_pro;
    let mut reason = if explicit_pro {
        "requested pro/reasoner model".to_string()
    } else {
        "default lightweight route".to_string()
    };
    if !wants_pro {
        if let Some(pro_reason) = hints.pro_reason() {
            wants_pro = true;
            reason = pro_reason;
        }
    }
    if !wants_pro {
        if let Some(light_reason) = hints.light_reason() {
            reason = light_reason;
        }
    }
    if !wants_pro {
        if let Some(pattern) = light_text_hit.as_deref() {
            reason = format!("task pattern keeps default: {}", pattern);
        }
    }
    if !wants_pro && light_text_hit.is_none() && !hint_matches(&hints.intent, LIGHTWEIGHT_HINTS) {
        if let Some(pattern) = pro_text_hit {
            wants_pro = true;
            reason = format!("task pattern matched: {}", pattern);
        }
    }
    if !wants_pro && light_text_hit.is_none() && !hint_matches(&hints.intent, LIGHTWEIGHT_HINTS) {
        if let Some(keyword) = keyword_hit {
            wants_pro = true;
            reason = format!("keyword matched: {}", keyword);
        }
    }

    let budget_downgrade =
        router.monthly_downgrade_rmb > 0.0 && monthly_cost >= router.monthly_downgrade_rmb;
    let mut decision = if budget_downgrade && wants_pro {
        RouteDecision {
            requested_model: requested_model.to_string(),
            desired_model: router.default_model.clone(),
            role: "default".to_string(),
            group: group_for_role(router, "default"),
            reason: format!(
                "monthly downgrade threshold reached {:.2} CNY; suppressed pro route ({})",
                monthly_cost, reason
            ),
        }
    } else if wants_pro {
        RouteDecision {
            requested_model: requested_model.to_string(),
            desired_model: router.pro_model.clone(),
            role: "pro".to_string(),
            group: group_for_role(router, "pro"),
            reason,
        }
    } else {
        RouteDecision {
            requested_model: requested_model.to_string(),
            desired_model: router.default_model.clone(),
            role: "default".to_string(),
            group: group_for_role(router, "default"),
            reason,
        }
    };

    if router.dry_run {
        decision.reason = format!(
            "dry-run: would use {}/{} because {}",
            decision.role, decision.desired_model, decision.reason
        );
        decision.desired_model = requested_model.to_string();
        decision.role = "any".to_string();
        decision.group.clear();
    }

    decision
}

fn explicit_model_route(router: &RouterConfig, requested_model: &str) -> Option<RouteDecision> {
    let requested = requested_model.trim();
    if requested.is_empty() || requested.eq_ignore_ascii_case("unknown") {
        return None;
    }
    if model_eq(requested, &router.default_model) {
        // The default model remains smart-routable: long/complex prompts may still upgrade to Pro.
        return None;
    }
    if model_eq(requested, &router.pro_model) {
        return Some(RouteDecision {
            requested_model: requested.to_string(),
            desired_model: router.pro_model.clone(),
            role: "pro".to_string(),
            group: group_for_role(router, "pro"),
            reason: "requested configured pro model".to_string(),
        });
    }
    if model_eq(requested, &router.emergency_model) {
        return Some(RouteDecision {
            requested_model: requested.to_string(),
            desired_model: router.emergency_model.clone(),
            role: "emergency".to_string(),
            group: group_for_role(router, "emergency"),
            reason: "requested configured emergency model".to_string(),
        });
    }
    if model_eq(requested, &router.backup_model) {
        return Some(RouteDecision {
            requested_model: requested.to_string(),
            desired_model: router.backup_model.clone(),
            role: "backup".to_string(),
            group: group_for_role(router, "backup"),
            reason: "requested configured backup model".to_string(),
        });
    }
    Some(RouteDecision {
        requested_model: requested.to_string(),
        desired_model: requested.to_string(),
        role: "any".to_string(),
        group: String::new(),
        reason: "requested explicit model passthrough".to_string(),
    })
}

fn model_eq(a: &str, b: &str) -> bool {
    !b.trim().is_empty() && a.trim().eq_ignore_ascii_case(b.trim())
}

fn group_for_role(router: &RouterConfig, role: &str) -> String {
    match role {
        "default" => router.default_group.trim(),
        "pro" => router.pro_group.trim(),
        "emergency" => router.emergency_group.trim(),
        "backup" => router.backup_group.trim(),
        _ => "",
    }
    .to_lowercase()
}

#[derive(Debug, Clone)]
struct AttemptSpec {
    role: String,
    group: String,
    desired_model: String,
    fallback: bool,
}

async fn build_attempts(
    state: &Arc<ProxyState>,
    channels: &[Channel],
    router: &RouterConfig,
    decision: &RouteDecision,
    protocol: ApiProtocol,
) -> Vec<Attempt> {
    let mut specs = Vec::new();
    add_role_attempts(
        &mut specs,
        router,
        decision.role.clone(),
        decision.desired_model.clone(),
        false,
    );

    for &role in fallback_roles(&decision.role) {
        if role == "any" {
            add_attempt_spec(
                &mut specs,
                "any".to_string(),
                String::new(),
                decision.desired_model.clone(),
                true,
            );
        } else {
            add_role_attempts(
                &mut specs,
                router,
                role.to_string(),
                model_for_role(router, role).to_string(),
                true,
            );
        }
    }
    let mut attempts = Vec::new();
    for spec in specs {
        let mut candidates: Vec<Channel> = channels
            .iter()
            .filter(|ch| ch.is_active())
            .filter(|ch| ApiProtocol::from_channel(ch).is_some())
            .filter(|ch| spec.role == "any" || ch.role_key() == spec.role)
            .filter(|ch| spec.group.is_empty() || ch.group_key() == spec.group)
            .filter(|ch| {
                ch.supports_model(&spec.desired_model)
                    || ch.supports_model(&decision.requested_model)
            })
            .cloned()
            .collect();
        candidates.sort_by_key(|ch| {
            (
                ApiProtocol::channel_match_rank(ch, protocol),
                ch.priority,
                ch.group_key(),
                ch.name.clone(),
            )
        });
        rotate_candidates(state, &mut candidates).await;
        for ch in candidates {
            let actual = ch.mapped_model(&decision.requested_model, &spec.desired_model);
            let attempt = Attempt {
                channel: ch,
                actual_model: actual,
                role: spec.role.clone(),
                group: spec.group.clone(),
                reason: if !spec.fallback
                    && spec.role == decision.role
                    && spec.group == decision.group
                {
                    decision.reason.clone()
                } else if spec.group.is_empty() {
                    format!("fallback to {}", spec.role)
                } else {
                    format!("fallback to {}/{}", spec.role, spec.group)
                },
            };
            if !attempts.iter().any(|existing: &Attempt| {
                existing.channel.id == attempt.channel.id
                    && existing.actual_model == attempt.actual_model
            }) {
                attempts.push(attempt);
            }
        }
    }
    attempts
}

fn fallback_roles(role: &str) -> &'static [&'static str] {
    match role {
        // When the monthly hard limit is reached, save the emergency pool for true incidents.
        "backup" => &["emergency", "any"],
        // Normal traffic should fail over to emergency first because this means the main pool timed out or errored.
        "default" | "pro" => &["emergency", "backup", "any"],
        "emergency" => &["backup", "any"],
        _ => &["any"],
    }
}

fn model_for_role<'a>(router: &'a RouterConfig, role: &str) -> &'a str {
    match role {
        "pro" => router.pro_model.as_str(),
        "emergency" => router.emergency_model.as_str(),
        "backup" => router.backup_model.as_str(),
        "default" => router.default_model.as_str(),
        _ => router.default_model.as_str(),
    }
}

fn add_role_attempts(
    specs: &mut Vec<AttemptSpec>,
    router: &RouterConfig,
    role: String,
    desired_model: String,
    fallback: bool,
) {
    let group = group_for_role(router, &role);
    add_attempt_spec(
        specs,
        role.clone(),
        group.clone(),
        desired_model.clone(),
        fallback,
    );
    if !group.is_empty() {
        add_attempt_spec(specs, role, String::new(), desired_model, true);
    }
}

fn add_attempt_spec(
    specs: &mut Vec<AttemptSpec>,
    role: String,
    group: String,
    desired_model: String,
    fallback: bool,
) {
    if specs
        .iter()
        .any(|item| item.role == role && item.group == group && item.desired_model == desired_model)
    {
        return;
    }
    specs.push(AttemptSpec {
        role,
        group,
        desired_model,
        fallback,
    });
}

async fn rotate_candidates(state: &Arc<ProxyState>, candidates: &mut [Channel]) {
    if candidates.len() <= 1 {
        return;
    }
    let mut idx = state.index.lock().await;
    let offset = *idx % candidates.len();
    *idx = idx.saturating_add(1);
    candidates.rotate_left(offset);
}

fn response_with_headers(
    status: StatusCode,
    headers: &reqwest::header::HeaderMap,
) -> axum::http::response::Builder {
    let mut builder = Response::builder().status(status);
    for (name, value) in headers.iter() {
        if name != header::CONTENT_LENGTH {
            builder = builder.header(name, value);
        }
    }
    builder
}

fn route_headers(
    mut builder: axum::http::response::Builder,
    attempt: &Attempt,
    decision: &RouteDecision,
    source: &str,
) -> axum::http::response::Builder {
    let headers = [
        ("x-obp-route", attempt.role.as_str()),
        ("x-obp-group", attempt.group.as_str()),
        ("x-obp-requested-model", decision.requested_model.as_str()),
        ("x-obp-actual-model", attempt.actual_model.as_str()),
        ("x-obp-channel", attempt.channel.name.as_str()),
        ("x-obp-reason", attempt.reason.as_str()),
        ("x-obp-source", source),
    ];
    for (name, value) in headers {
        if let Ok(header_name) = HeaderName::from_bytes(name.as_bytes()) {
            builder = builder.header(header_name, value);
        }
    }
    builder
}

async fn record_failure(
    state: &Arc<ProxyState>,
    channel: Option<&Channel>,
    requested_model: String,
    actual_model: String,
    route: String,
    reason: String,
    status: u16,
    elapsed: Duration,
    source: &str,
) {
    if let Some(ch) = channel {
        record_result(
            state,
            ch,
            &requested_model,
            &actual_model,
            &route,
            &reason,
            status,
            elapsed,
            TokenUsage::default(),
            source,
        )
        .await;
    }
}

#[allow(clippy::too_many_arguments)]
async fn record_result(
    state: &Arc<ProxyState>,
    ch: &Channel,
    requested_model: &str,
    actual_model: &str,
    route: &str,
    route_reason: &str,
    status: u16,
    elapsed: Duration,
    usage: TokenUsage,
    source: &str,
) {
    let latency_ms = elapsed.as_millis().min(u128::from(u64::MAX)) as u64;
    let log = RequestLog::new(
        source.to_string(),
        ch.id,
        ch.name.clone(),
        requested_model.to_string(),
        actual_model.to_string(),
        route.to_string(),
        route_reason.to_string(),
        status,
        latency_ms,
        usage,
    );
    log_model_route(&log, ch);

    {
        let mut channels = state.channels.lock().await;
        if let Some(current) = channels
            .iter_mut()
            .find(|item| item.id == ch.id && item.name == ch.name)
        {
            current.requests = current.requests.saturating_add(1);
            if (200..400).contains(&status) {
                current.fail_count = 0;
                current.status = "active".to_string();
                current.disabled_until = None;
            } else {
                current.fail_count = current.fail_count.saturating_add(1);
                if current.fail_count >= 3 {
                    current.status = "cooldown".to_string();
                    current.disabled_until =
                        Some(unix_now_secs().saturating_add(CHANNEL_COOLDOWN_SECS));
                }
            }
        }
        save_config(&state.config_path, &channels);
    }

    {
        let mut stats = state.stats.lock().await;
        stats.record(log);
        save_stats(&state.stats_path, &stats);
    }
}

fn log_model_route(log: &RequestLog, ch: &Channel) {
    let group = if ch.group.trim().is_empty() {
        "-"
    } else {
        ch.group.trim()
    };
    if (200..400).contains(&log.status) {
        tracing::info!(
            target: "obp.model",
            time = %log.time,
            source = %log.source,
            channel = %log.channel,
            group = %group,
            requested_model = %log.requested_model,
            actual_model = %log.model,
            route = %log.route,
            status = log.status,
            latency_ms = log.latency_ms,
            prompt_tokens = log.prompt_tokens,
            cached_tokens = log.cached_tokens,
            completion_tokens = log.completion_tokens,
            cost_cny = log.cost_cny,
            reason = %log.route_reason,
            "obp_model_route"
        );
    } else {
        tracing::warn!(
            target: "obp.model",
            time = %log.time,
            channel = %log.channel,
            group = %group,
            requested_model = %log.requested_model,
            actual_model = %log.model,
            route = %log.route,
            status = log.status,
            latency_ms = log.latency_ms,
            prompt_tokens = log.prompt_tokens,
            cached_tokens = log.cached_tokens,
            completion_tokens = log.completion_tokens,
            cost_cny = log.cost_cny,
            reason = %log.route_reason,
            "obp_model_route"
        );
    }
}

fn contains_any(text: &str, needles: &[&str]) -> bool {
    needles.iter().any(|needle| text.contains(needle))
}

fn hint_matches(value: &str, patterns: &[&str]) -> bool {
    let value = value.trim().to_lowercase();
    !value.is_empty()
        && patterns
            .iter()
            .any(|pattern| value.contains(&pattern.to_lowercase()))
}

fn first_non_empty(values: &[String]) -> String {
    values
        .iter()
        .find(|value| !value.trim().is_empty())
        .map(|value| value.trim().to_lowercase())
        .unwrap_or_default()
}

fn header_hint(headers: &HeaderMap, name: &str) -> String {
    headers
        .get(name)
        .and_then(|value| value.to_str().ok())
        .map(|value| value.trim().to_lowercase())
        .unwrap_or_default()
}

fn json_hint(value: Option<&Value>, keys: &[&str]) -> String {
    let Some(value) = value else {
        return String::new();
    };
    if let Some(found) = json_direct_hint(value, keys) {
        return found;
    }
    for container in ["metadata", "extra_body", "obp"] {
        if let Some(found) = value
            .get(container)
            .and_then(|inner| json_direct_hint(inner, keys))
        {
            return found;
        }
    }
    String::new()
}

fn json_direct_hint(value: &Value, keys: &[&str]) -> Option<String> {
    for key in keys {
        if let Some(text) = value.get(*key).and_then(Value::as_str) {
            let normalized = text.trim().to_lowercase();
            if !normalized.is_empty() {
                return Some(normalized);
            }
        }
    }
    None
}

fn extract_routing_text(value: &Value) -> String {
    if let Some(messages) = value.get("messages").and_then(Value::as_array) {
        if let Some(message) = messages
            .iter()
            .rev()
            .find(|message| message_role_is(message, "user"))
        {
            return message_content_text(message);
        }
        if let Some(message) = messages.last() {
            return message_content_text(message);
        }
    }
    if let Some(input) = value.get("input") {
        return extract_text(input);
    }
    extract_text(value)
}

fn message_role_is(message: &Value, expected: &str) -> bool {
    message
        .get("role")
        .and_then(Value::as_str)
        .map(|role| role.eq_ignore_ascii_case(expected))
        .unwrap_or(false)
}

fn message_content_text(message: &Value) -> String {
    message
        .get("content")
        .map(extract_text)
        .unwrap_or_else(|| extract_text(message))
}

fn extract_text(value: &Value) -> String {
    match value {
        Value::String(text) => text.clone(),
        Value::Array(items) => items
            .iter()
            .map(extract_text)
            .collect::<Vec<_>>()
            .join("\n"),
        Value::Object(map) => map
            .iter()
            .filter(|(key, _)| key.as_str() != "tool_calls")
            .map(|(_, value)| extract_text(value))
            .collect::<Vec<_>>()
            .join("\n"),
        _ => String::new(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::RouterConfig;
    use crate::stats::UsageStats;

    #[test]
    fn heartbeat_routes_to_longcat_before_paid_default() {
        let router = RouterConfig::default();
        let body = serde_json::json!({
            "model": "deepseek-v4-flash",
            "messages": [
                {"role": "system", "content": "Read heartbeat.md and report if there is anything to do."},
                {"role": "user", "content": "Review the following HEARTBEAT.md and decide whether there are active tasks."}
            ]
        });
        let decision = route_decision(
            &router,
            &UsageStats::default(),
            Some(&body),
            "deepseek-v4-flash",
            &RouteHints::default(),
        );

        assert_eq!(decision.role, "emergency");
        assert_eq!(decision.group, "longcat");
        assert_eq!(decision.desired_model, "LongCat-Flash-Chat");
        assert!(decision.reason.contains("free longcat"));
    }

    #[test]
    fn heartbeat_without_source_is_labeled_as_default_internal_task() {
        let router = RouterConfig::default();
        let body = serde_json::json!({
            "model": "deepseek-v4-flash",
            "messages": [
                {"role": "system", "content": "Read heartbeat.md and report if there is anything to do."},
                {"role": "user", "content": "Review the following HEARTBEAT.md and decide whether there are active tasks."}
            ]
        });
        let source = request_source(&HeaderMap::new(), Some(&body));
        let decision = route_decision(
            &router,
            &UsageStats::default(),
            Some(&body),
            "deepseek-v4-flash",
            &RouteHints::default(),
        );

        assert_eq!(source, "unknown-source");
        assert_eq!(
            effective_request_source(source, &decision),
            "default-nanobot-internal"
        );
    }

    #[test]
    fn stale_heartbeat_context_does_not_pin_emergency() {
        let router = RouterConfig::default();
        let body = serde_json::json!({
            "model": "deepseek-v4-flash",
            "messages": [
                {"role": "system", "content": "Earlier we reviewed HEARTBEAT.md."},
                {"role": "assistant", "content": "The heartbeat check is done."},
                {"role": "user", "content": "Plain chat probe: reply OK."}
            ]
        });
        let decision = route_decision(
            &router,
            &UsageStats::default(),
            Some(&body),
            "deepseek-v4-flash",
            &RouteHints::default(),
        );

        assert_eq!(decision.role, "default");
        assert_eq!(decision.group, "deepseek");
        assert_eq!(decision.desired_model, "deepseek-v4-flash");
    }

    #[test]
    fn heartbeat_routes_to_longcat_even_after_hard_limit() {
        let mut router = RouterConfig::default();
        router.monthly_hard_limit_rmb = 0.1;
        let mut stats = UsageStats::default();
        stats.total.cost_cny = 99.0;
        let body = serde_json::json!({
            "model": "deepseek-v4-flash",
            "messages": [{"role": "user", "content": "heartbeat.md"}]
        });
        let decision = route_decision(
            &router,
            &stats,
            Some(&body),
            "deepseek-v4-flash",
            &RouteHints::default(),
        );

        assert_eq!(decision.role, "emergency");
        assert_eq!(decision.group, "longcat");
        assert_eq!(decision.desired_model, "LongCat-Flash-Chat");
    }
}
