use crate::config::{save_config, Channel};
use crate::stats::{save_stats, RequestLog, TokenUsage, UsageStats};
use axum::{
    body::{to_bytes, Body},
    extract::State,
    http::{Request, Response, StatusCode},
    response::IntoResponse,
};
use reqwest::{Body as ReqBody, Client};
use serde_json::Value;
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::sync::Mutex;

const MAX_REQUEST_BYTES: usize = 16 * 1024 * 1024;

pub struct ProxyState {
    pub client: Client,
    pub channels: Mutex<Vec<Channel>>,
    pub stats: Mutex<UsageStats>,
    pub index: Mutex<usize>,
    pub config_path: String,
    pub stats_path: String,
}

pub async fn handle_proxy(
    State(state): State<Arc<ProxyState>>,
    req: Request<Body>,
) -> impl IntoResponse {
    let started = Instant::now();
    let channels = state.channels.lock().await;
    if channels.is_empty() {
        return (StatusCode::NOT_FOUND, "No channels available").into_response();
    }

    let mut idx = state.index.lock().await;
    let ch = channels[*idx % channels.len()].clone();
    *idx += 1;
    drop(idx);
    drop(channels);

    let target_url = format!("{}/v1/chat/completions", ch.base.trim_end_matches('/'));
    let (parts, body) = req.into_parts();
    let body_bytes = match to_bytes(body, MAX_REQUEST_BYTES).await {
        Ok(bytes) => bytes,
        Err(e) => {
            record_result(
                &state,
                &ch,
                "unknown".to_string(),
                StatusCode::BAD_REQUEST.as_u16(),
                started.elapsed(),
                TokenUsage::default(),
            )
            .await;
            return (
                StatusCode::BAD_REQUEST,
                format!("Invalid request body: {}", e),
            )
                .into_response();
        }
    };

    let request_json = serde_json::from_slice::<Value>(&body_bytes).ok();
    let model = request_json
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

    let mut target_req = state
        .client
        .post(&target_url)
        .header("Authorization", format!("Bearer {}", ch.key))
        .body(ReqBody::from(body_bytes.clone()));

    for (name, value) in parts.headers.iter() {
        if name != "host" && name != "authorization" {
            target_req = target_req.header(name, value);
        }
    }

    let response = match target_req.send().await {
        Ok(res) => res,
        Err(e) => {
            record_result(
                &state,
                &ch,
                model,
                StatusCode::BAD_GATEWAY.as_u16(),
                started.elapsed(),
                TokenUsage::default(),
            )
            .await;
            return (StatusCode::BAD_GATEWAY, format!("Upstream error: {}", e)).into_response();
        }
    };

    let status = StatusCode::from_u16(response.status().as_u16())
        .unwrap_or(StatusCode::INTERNAL_SERVER_ERROR);
    let status_u16 = status.as_u16();
    let mut res_builder = Response::builder().status(status);

    for (name, value) in response.headers().iter() {
        res_builder = res_builder.header(name, value);
    }

    if stream {
        record_result(
            &state,
            &ch,
            model,
            status_u16,
            started.elapsed(),
            TokenUsage::default(),
        )
        .await;
        let res_stream = response.bytes_stream();
        return res_builder
            .body(Body::from_stream(res_stream))
            .unwrap_or_else(|_| {
                (StatusCode::INTERNAL_SERVER_ERROR, "Internal Error").into_response()
            });
    }

    let response_bytes = match response.bytes().await {
        Ok(bytes) => bytes,
        Err(e) => {
            record_result(
                &state,
                &ch,
                model,
                StatusCode::BAD_GATEWAY.as_u16(),
                started.elapsed(),
                TokenUsage::default(),
            )
            .await;
            return (
                StatusCode::BAD_GATEWAY,
                format!("Upstream body error: {}", e),
            )
                .into_response();
        }
    };
    let usage = TokenUsage::from_response_bytes(&response_bytes);
    record_result(&state, &ch, model, status_u16, started.elapsed(), usage).await;

    res_builder
        .body(Body::from(response_bytes))
        .unwrap_or_else(|_| (StatusCode::INTERNAL_SERVER_ERROR, "Internal Error").into_response())
}

async fn record_result(
    state: &Arc<ProxyState>,
    ch: &Channel,
    model: String,
    status: u16,
    elapsed: Duration,
    usage: TokenUsage,
) {
    let latency_ms = elapsed.as_millis().min(u128::from(u64::MAX)) as u64;
    let log = RequestLog::new(ch.id, ch.name.clone(), model, status, latency_ms, usage);

    {
        let mut channels = state.channels.lock().await;
        if let Some(current) = channels
            .iter_mut()
            .find(|item| item.id == ch.id && item.name == ch.name)
        {
            current.requests = current.requests.saturating_add(1);
        }
        save_config(&state.config_path, &channels);
    }

    {
        let mut stats = state.stats.lock().await;
        stats.record(log);
        save_stats(&state.stats_path, &stats);
    }
}
