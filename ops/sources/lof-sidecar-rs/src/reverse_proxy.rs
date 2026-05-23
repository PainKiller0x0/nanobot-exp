use axum::{
    body::{Body, Bytes},
    http::{header, HeaderMap, Method, StatusCode, Uri},
    response::Response,
};
use reqwest::Client;

pub(crate) async fn reverse_proxy(
    client: &Client,
    upstream: &'static str,
    prefix: &'static str,
    path: &str,
    method: Method,
    uri: Uri,
    headers: HeaderMap,
    body: Bytes,
) -> Response {
    let upstream_path = if path.is_empty() {
        "/".to_string()
    } else {
        format!("/{}", path)
    };
    let query = uri.query().map(|q| format!("?{}", q)).unwrap_or_default();
    let url = format!("{}{}{}", upstream, upstream_path, query);

    let mut req = client.request(method, &url).body(body.to_vec());
    for (name, value) in headers.iter() {
        if *name == header::HOST
            || *name == header::CONNECTION
            || *name == header::CONTENT_LENGTH
            || *name == header::ACCEPT_ENCODING
        {
            continue;
        }
        req = req.header(name, value);
    }

    let Ok(resp) = req.send().await else {
        return response_with_status(StatusCode::BAD_GATEWAY, "upstream request failed");
    };
    let status = resp.status();
    let content_type = resp
        .headers()
        .get(header::CONTENT_TYPE)
        .and_then(|v| v.to_str().ok())
        .unwrap_or("")
        .to_string();
    let response_headers = resp.headers().clone();
    if content_type.contains("text/event-stream") {
        let builder = Response::builder()
            .status(status)
            .header(header::CONTENT_TYPE, content_type)
            .header(header::CACHE_CONTROL, "no-cache")
            .header("x-accel-buffering", "no");
        return forward_proxy_response_headers(builder, &response_headers)
            .body(Body::from_stream(resp.bytes_stream()))
            .unwrap_or_else(|_| {
                response_with_status(StatusCode::BAD_GATEWAY, "response build failed")
            });
    }

    let bytes = match resp.bytes().await {
        Ok(v) => v,
        Err(_) => return response_with_status(StatusCode::BAD_GATEWAY, "upstream read failed"),
    };

    if should_rewrite_text(&content_type) {
        match String::from_utf8(bytes.to_vec()) {
            Ok(text) => {
                let rewritten = rewrite_proxy_text(text, prefix);
                let rewritten = if content_type.contains("text/html") {
                    inject_sidecar_shell(rewritten, prefix)
                } else {
                    rewritten
                };
                let builder = Response::builder()
                    .status(status)
                    .header(header::CONTENT_TYPE, content_type);
                return forward_proxy_response_headers(builder, &response_headers)
                    .body(Body::from(rewritten))
                    .unwrap_or_else(|_| {
                        response_with_status(StatusCode::BAD_GATEWAY, "response build failed")
                    });
            }
            Err(_) => {}
        }
    }

    let builder = Response::builder()
        .status(status)
        .header(header::CONTENT_TYPE, content_type);
    forward_proxy_response_headers(builder, &response_headers)
        .body(Body::from(bytes))
        .unwrap_or_else(|_| response_with_status(StatusCode::BAD_GATEWAY, "response build failed"))
}

fn forward_proxy_response_headers(
    mut builder: axum::http::response::Builder,
    headers: &reqwest::header::HeaderMap,
) -> axum::http::response::Builder {
    for (name, value) in headers.iter() {
        let name_str = name.as_str().to_ascii_lowercase();
        if name_str.starts_with("x-obp-") || name_str == "cache-control" || name_str == "pragma" {
            builder = builder.header(name, value);
        }
    }
    builder
}

fn response_with_status(status: StatusCode, body: &'static str) -> Response {
    Response::builder()
        .status(status)
        .header(header::CONTENT_TYPE, "text/plain; charset=utf-8")
        .body(Body::from(body))
        .unwrap()
}

fn should_rewrite_text(content_type: &str) -> bool {
    content_type.contains("text/html")
        || content_type.contains("application/javascript")
        || content_type.contains("text/javascript")
        || content_type.contains("text/css")
}

fn rewrite_proxy_text(mut text: String, prefix: &str) -> String {
    for (from, to) in [
        ("'/api", format!("'{}{}", prefix, "/api")),
        ("\"/api", format!("\"{}{}", prefix, "/api")),
        ("`/api", format!("`{}{}", prefix, "/api")),
        ("'/admin", format!("'{}{}", prefix, "/admin")),
        ("\"/admin", format!("\"{}{}", prefix, "/admin")),
        ("`/admin", format!("`{}{}", prefix, "/admin")),
        ("'/v1", format!("'{}{}", prefix, "/v1")),
        ("\"/v1", format!("\"{}{}", prefix, "/v1")),
        ("`/v1", format!("`{}{}", prefix, "/v1")),
        ("href=\"/\"", format!("href=\"{}/\"", prefix)),
        ("href='/ '".trim(), format!("href='{}/'", prefix)),
    ] {
        text = text.replace(from, &to);
    }
    text
}

fn inject_sidecar_shell(mut text: String, prefix: &str) -> String {
    if text.contains("/assets/nb-shell.js") || text.contains("nb-sidecar-shell") {
        return text;
    }
    let label = match prefix {
        "/rss" => "RSS 文章",
        "/obp" => "OBP 模型网关",
        "/trends" => "热点雷达",
        "/reflexio" => "Reflexio",
        _ => "Sidecar",
    };
    let script = format!(
        r#"<script src="/assets/nb-shell.js" data-prefix="{}" data-label="{}" defer></script>"#,
        prefix, label
    );
    if let Some(pos) = text.rfind("</body>") {
        text.insert_str(pos, &script);
    } else {
        text.push_str(&script);
    }
    text
}
