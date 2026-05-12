use std::time::{Duration, Instant};

use chrono::{DateTime, Duration as ChronoDuration, FixedOffset, Utc};
use reqwest::Client;
use serde::{Deserialize, Serialize};
use tokio::{net::TcpStream, process::Command};

fn manager_now() -> DateTime<FixedOffset> {
    let sh_tz = FixedOffset::east_opt(8 * 3600).expect("tz");
    Utc::now().with_timezone(&sh_tz)
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub(crate) struct ManagedSidecar {
    pub(crate) id: String,
    pub(crate) name: String,
    pub(crate) description: String,
    pub(crate) port: Option<u16>,
    pub(crate) unit: Option<String>,
    pub(crate) homepage_url: Option<String>,
    pub(crate) check_url: Option<String>,
    pub(crate) check_kind: Option<String>,
    pub(crate) public: bool,
    pub(crate) logs_command: String,
    pub(crate) restart_command: String,
}

#[derive(Debug, Clone, Serialize)]
pub(crate) struct ManagedSidecarStatus {
    pub(crate) id: String,
    pub(crate) name: String,
    pub(crate) description: String,
    pub(crate) port: Option<u16>,
    pub(crate) unit: Option<String>,
    pub(crate) homepage_url: Option<String>,
    pub(crate) public: bool,
    pub(crate) ok: bool,
    pub(crate) check_status: String,
    pub(crate) unit_status: Option<String>,
    pub(crate) http_code: Option<u16>,
    pub(crate) latency_ms: Option<u128>,
    pub(crate) error: Option<String>,
    pub(crate) active_since: Option<String>,
    pub(crate) recent_errors: Vec<String>,
    pub(crate) logs_command: String,
    pub(crate) restart_command: String,
}

#[derive(Debug, Clone, Serialize)]
pub(crate) struct SidecarManagerSummary {
    pub(crate) total: usize,
    pub(crate) healthy: usize,
    pub(crate) unhealthy: usize,
}

#[derive(Debug, Clone, Serialize)]
pub(crate) struct SidecarManagerResponse {
    pub(crate) now: String,
    pub(crate) summary: SidecarManagerSummary,
    pub(crate) items: Vec<ManagedSidecarStatus>,
}

pub(crate) async fn snapshot(client: &Client) -> SidecarManagerResponse {
    let configs = load_managed_sidecars().await;
    let mut items = Vec::new();
    for cfg in configs {
        items.push(check_managed_sidecar(client, cfg).await);
    }
    let healthy = items.iter().filter(|item| item.ok).count();
    let total = items.len();
    SidecarManagerResponse {
        now: manager_now().format("%Y-%m-%d %H:%M:%S %:z").to_string(),
        summary: SidecarManagerSummary {
            total,
            healthy,
            unhealthy: total.saturating_sub(healthy),
        },
        items,
    }
}

async fn load_managed_sidecars() -> Vec<ManagedSidecar> {
    let path = std::env::var("SIDECAR_MANAGER_CONFIG")
        .unwrap_or_else(|_| "/root/.nanobot/sidecars.json".to_string());
    match tokio::fs::read_to_string(&path).await {
        Ok(text) => serde_json::from_str::<Vec<ManagedSidecar>>(&text)
            .unwrap_or_else(|_| default_managed_sidecars()),
        Err(_) => default_managed_sidecars(),
    }
}

fn default_managed_sidecars() -> Vec<ManagedSidecar> {
    vec![ManagedSidecar {
        id: "lof".into(),
        name: "LOF Sidecar".into(),
        description: "LOF data board and reports".into(),
        port: Some(8093),
        unit: Some("lof-sidecar.service".into()),
        homepage_url: Some("/".into()),
        check_url: Some("http://127.0.0.1:8093/health".into()),
        check_kind: Some("http".into()),
        public: true,
        logs_command: "journalctl -u lof-sidecar.service -f".into(),
        restart_command: "systemctl restart lof-sidecar.service".into(),
    }]
}

async fn check_managed_sidecar(client: &Client, cfg: ManagedSidecar) -> ManagedSidecarStatus {
    let unit_status = check_systemd_unit(cfg.unit.as_deref()).await;
    let active_since = check_systemd_active_since(cfg.unit.as_deref()).await;
    let recent_errors =
        check_systemd_recent_errors(cfg.unit.as_deref(), active_since.as_deref()).await;
    let started = Instant::now();
    let mut ok = false;
    let mut check_status = "unknown".to_string();
    let mut http_code = None;
    let mut latency_ms = None;
    let mut error = None;
    let kind = cfg.check_kind.as_deref().unwrap_or("http");

    if kind == "tcp" {
        if let Some(port) = cfg.port {
            match tokio::time::timeout(
                Duration::from_secs(2),
                TcpStream::connect(("127.0.0.1", port)),
            )
            .await
            {
                Ok(Ok(_)) => {
                    ok = true;
                    check_status = "tcp open".to_string();
                    latency_ms = Some(started.elapsed().as_millis());
                }
                Ok(Err(e)) => {
                    check_status = "tcp closed".to_string();
                    error = Some(e.to_string());
                    latency_ms = Some(started.elapsed().as_millis());
                }
                Err(_) => {
                    check_status = "tcp timeout".to_string();
                    error = Some("tcp check timed out".to_string());
                    latency_ms = Some(started.elapsed().as_millis());
                }
            }
        } else {
            error = Some("missing port for tcp check".to_string());
        }
    } else if kind == "unit" {
        ok = matches!(unit_status.as_deref(), Some("active"));
        check_status = unit_status.clone().unwrap_or_else(|| "unknown".to_string());
        latency_ms = Some(started.elapsed().as_millis());
    } else if let Some(url) = cfg.check_url.as_deref() {
        match tokio::time::timeout(Duration::from_secs(3), client.get(url).send()).await {
            Ok(Ok(resp)) => {
                let status = resp.status();
                http_code = Some(status.as_u16());
                ok = status.is_success();
                check_status = format!("http {}", status.as_u16());
                latency_ms = Some(started.elapsed().as_millis());
            }
            Ok(Err(e)) => {
                check_status = "http error".to_string();
                error = Some(e.to_string());
                latency_ms = Some(started.elapsed().as_millis());
            }
            Err(_) => {
                check_status = "http timeout".to_string();
                error = Some("http check timed out".to_string());
                latency_ms = Some(started.elapsed().as_millis());
            }
        }
    } else if let Some(port) = cfg.port {
        match tokio::time::timeout(
            Duration::from_secs(2),
            TcpStream::connect(("127.0.0.1", port)),
        )
        .await
        {
            Ok(Ok(_)) => {
                ok = true;
                check_status = "tcp open".to_string();
                latency_ms = Some(started.elapsed().as_millis());
            }
            Ok(Err(e)) => {
                check_status = "tcp closed".to_string();
                error = Some(e.to_string());
                latency_ms = Some(started.elapsed().as_millis());
            }
            Err(_) => {
                check_status = "tcp timeout".to_string();
                error = Some("tcp check timed out".to_string());
                latency_ms = Some(started.elapsed().as_millis());
            }
        }
    } else {
        ok = matches!(unit_status.as_deref(), Some("active"));
        check_status = unit_status
            .clone()
            .unwrap_or_else(|| "not configured".to_string());
    }

    if cfg.unit.as_deref().is_some_and(|u| !u.trim().is_empty())
        && !matches!(unit_status.as_deref(), Some("active"))
    {
        ok = false;
    }

    ManagedSidecarStatus {
        id: cfg.id,
        name: cfg.name,
        description: cfg.description,
        port: cfg.port,
        unit: cfg.unit,
        homepage_url: cfg.homepage_url,
        public: cfg.public,
        ok,
        check_status,
        unit_status,
        http_code,
        latency_ms,
        error,
        active_since,
        recent_errors,
        logs_command: cfg.logs_command,
        restart_command: cfg.restart_command,
    }
}

async fn check_systemd_active_since(unit: Option<&str>) -> Option<String> {
    let unit = unit?.trim();
    if unit.is_empty() {
        return None;
    }
    let output = tokio::time::timeout(
        Duration::from_secs(2),
        Command::new("systemctl")
            .arg("show")
            .arg(unit)
            .arg("-p")
            .arg("ActiveEnterTimestamp")
            .arg("--value")
            .output(),
    )
    .await;
    match output {
        Ok(Ok(out)) => {
            let text = String::from_utf8_lossy(&out.stdout).trim().to_string();
            if text.is_empty() {
                None
            } else {
                Some(text)
            }
        }
        _ => None,
    }
}

fn journal_since_value(active_since: Option<&str>) -> Option<String> {
    let text = active_since?.trim();
    if text.is_empty() {
        return None;
    }
    let parts: Vec<&str> = text.split_whitespace().collect();
    if parts.len() >= 3 && parts[1].chars().take(4).all(|c| c.is_ascii_digit()) {
        let value = format!("{} {}", parts[1], parts[2]);
        chrono::NaiveDateTime::parse_from_str(&value, "%Y-%m-%d %H:%M:%S")
            .map(|dt| {
                (dt + ChronoDuration::seconds(1))
                    .format("%Y-%m-%d %H:%M:%S")
                    .to_string()
            })
            .unwrap_or(value)
            .into()
    } else {
        Some(text.to_string())
    }
}

async fn check_systemd_recent_errors(
    unit: Option<&str>,
    active_since: Option<&str>,
) -> Vec<String> {
    let Some(unit) = unit.map(str::trim).filter(|u| !u.is_empty()) else {
        return Vec::new();
    };
    let mut cmd = Command::new("journalctl");
    cmd.arg("-u")
        .arg(unit)
        .arg("-p")
        .arg("warning..alert")
        .arg("--no-pager")
        .arg("-n")
        .arg("20");
    if let Some(since) = journal_since_value(active_since) {
        cmd.arg(format!("--since={since}"));
    }
    let output = tokio::time::timeout(Duration::from_secs(2), cmd.output()).await;
    match output {
        Ok(Ok(out)) => String::from_utf8_lossy(&out.stdout)
            .lines()
            .filter(|line| {
                let text = line.trim();
                if text.is_empty()
                    || text.contains("-- No entries --")
                    || text.starts_with("-- Journal begins")
                    || text.starts_with("Hint:")
                {
                    return false;
                }
                let lower = text.to_ascii_lowercase();
                lower.contains("error")
                    || lower.contains("warn")
                    || lower.contains("failed")
                    || lower.contains("timeout")
                    || lower.contains("traceback")
                    || lower.contains("panic")
            })
            .take(3)
            .map(|line| {
                let mut text = line.trim().to_string();
                if text.chars().count() > 180 {
                    text = text.chars().take(180).collect::<String>();
                    text.push_str("...");
                }
                text
            })
            .collect(),
        _ => Vec::new(),
    }
}

async fn check_systemd_unit(unit: Option<&str>) -> Option<String> {
    let unit = unit?.trim();
    if unit.is_empty() {
        return None;
    }
    let output = tokio::time::timeout(
        Duration::from_secs(2),
        Command::new("systemctl")
            .arg("is-active")
            .arg(unit)
            .output(),
    )
    .await;
    match output {
        Ok(Ok(out)) => {
            let text = String::from_utf8_lossy(&out.stdout).trim().to_string();
            if text.is_empty() {
                Some("unknown".to_string())
            } else {
                Some(text)
            }
        }
        Ok(Err(e)) => Some(format!("error: {}", e)),
        Err(_) => Some("timeout".to_string()),
    }
}
