use std::{collections::HashMap, time::Duration};
use tokio::process::Command;

pub(crate) fn json_u64(value: &serde_json::Value, key: &str) -> u64 {
    value.get(key).and_then(|v| v.as_u64()).unwrap_or(0)
}

pub(crate) fn json_f64(value: &serde_json::Value, key: &str) -> f64 {
    value.get(key).and_then(|v| v.as_f64()).unwrap_or(0.0)
}

pub(crate) fn read_meminfo_mb() -> serde_json::Value {
    let text = std::fs::read_to_string("/proc/meminfo").unwrap_or_default();
    let mut values: HashMap<String, u64> = HashMap::new();
    for line in text.lines() {
        let mut parts = line.split_whitespace();
        let Some(key) = parts.next() else { continue };
        let Some(raw) = parts.next() else { continue };
        if let Ok(kb) = raw.parse::<u64>() {
            values.insert(key.trim_end_matches(':').to_string(), kb / 1024);
        }
    }
    let total = values.get("MemTotal").copied().unwrap_or(0);
    let available = values.get("MemAvailable").copied().unwrap_or(0);
    let used = total.saturating_sub(available);
    let swap_total = values.get("SwapTotal").copied().unwrap_or(0);
    let swap_free = values.get("SwapFree").copied().unwrap_or(0);
    serde_json::json!({
        "total_mb": total,
        "available_mb": available,
        "used_mb": used,
        "used_pct": if total > 0 { (used as f64 * 100.0 / total as f64 * 10.0).round() / 10.0 } else { 0.0 },
        "swap_used_mb": swap_total.saturating_sub(swap_free),
        "swap_total_mb": swap_total,
    })
}

pub(crate) fn read_loadavg() -> serde_json::Value {
    let text = std::fs::read_to_string("/proc/loadavg").unwrap_or_default();
    let parts: Vec<&str> = text.split_whitespace().take(3).collect();
    serde_json::json!({
        "one": parts.first().copied().unwrap_or("-"),
        "five": parts.get(1).copied().unwrap_or("-"),
        "fifteen": parts.get(2).copied().unwrap_or("-"),
    })
}

pub(crate) fn read_cpu_info() -> serde_json::Value {
    let cores = std::thread::available_parallelism()
        .map(|n| n.get())
        .unwrap_or(1);
    serde_json::json!({"cores": cores})
}

pub(crate) async fn read_disk_root() -> serde_json::Value {
    let output = tokio::time::timeout(
        Duration::from_secs(2),
        Command::new("df").arg("-Pm").arg("/").output(),
    )
    .await;
    match output {
        Ok(Ok(out)) => {
            let text = String::from_utf8_lossy(&out.stdout);
            let Some(line) = text.lines().nth(1) else {
                return serde_json::json!({"ok": false});
            };
            let cols: Vec<&str> = line.split_whitespace().collect();
            if cols.len() < 6 {
                return serde_json::json!({"ok": false});
            }
            serde_json::json!({
                "ok": true,
                "total_mb": cols.get(1).and_then(|v| v.parse::<u64>().ok()).unwrap_or(0),
                "used_mb": cols.get(2).and_then(|v| v.parse::<u64>().ok()).unwrap_or(0),
                "available_mb": cols.get(3).and_then(|v| v.parse::<u64>().ok()).unwrap_or(0),
                "used_pct": cols.get(4).copied().unwrap_or("-"),
                "mount": cols.get(5).copied().unwrap_or("/"),
            })
        }
        _ => serde_json::json!({"ok": false}),
    }
}
