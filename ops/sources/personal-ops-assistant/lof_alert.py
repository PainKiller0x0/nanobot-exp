#!/usr/bin/env python3
"""LOF premium threshold alert: push QQ when premium exceeds configured level."""

import json, os, sys, urllib.error, urllib.request
from datetime import datetime, timezone, timedelta

SHANGHAI = timezone(timedelta(hours=8))
LOF_API = "http://127.0.0.1:8093/api/lof"
QQ_NOTIFY_API = "http://127.0.0.1:8094/api/send"
PREMIUM_THRESHOLD = float(os.environ.get("LOF_ALERT_PREMIUM_THRESHOLD", "8.0"))
COOLDOWN_MINUTES = int(os.environ.get("LOF_ALERT_COOLDOWN_MINUTES", "120"))
STATE_FILE = "/root/.nanobot/data/lof_alert_state.json"

def now() -> datetime:
    return datetime.now(SHANGHAI)

def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"last_alert": None, "last_funds": {}}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def fetch_lof():
    try:
        with urllib.request.urlopen(LOF_API, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("rows", []) if isinstance(data, dict) else []
    except Exception as e:
        print(f"[LOF fetch error] {e}", file=sys.stderr)
        return []

def send_qq(message: str):
    payload = json.dumps({"text": message}).encode("utf-8")
    req = urllib.request.Request(QQ_NOTIFY_API, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"[QQ send error] {e}", file=sys.stderr)
        return False

def main():
    state = load_state()
    funds = fetch_lof()
    if not funds:
        return

    triggered = []
    for fund in funds:
        code = fund.get("code", "")
        name = fund.get("name", "")
        premium = fund.get("premium") or fund.get("t1_premium") or 0
        try:
            premium = float(premium)
        except (TypeError, ValueError):
            continue
        if premium >= PREMIUM_THRESHOLD:
            triggered.append((code, name, premium))

    if not triggered:
        return

    # Cooldown check
    last_alert = state.get("last_alert")
    if last_alert:
        try:
            last_dt = datetime.fromisoformat(last_alert)
            if (now() - last_dt).total_seconds() < COOLDOWN_MINUTES * 60:
                return
        except (ValueError, TypeError):
            pass

    # Build QQ message
    lines = [f"\u26a0\ufe0f LOF \u6ea2\u4ef7\u8b66\u62a5\uff08\u7f8e\u5143\u6ea2\u4ef7 \u2265 {PREMIUM_THRESHOLD}%\uff09"]
    for code, name, prem in triggered[:6]:
        lines.append(f"  {code} {name}  \u6ea2\u4ef7 {prem:.1f}%")
    if len(triggered) > 6:
        lines.append(f"  ... \u5176\u4ed6 {len(triggered) - 6} \u53ea")

    msg = "\n".join(lines)
    if send_qq(msg):
        state["last_alert"] = now().isoformat()
        state["last_funds"] = {c: {"name": n, "premium": p} for c, n, p in triggered}
        save_state(state)
        print(f"[{now().strftime('%H:%M')}] LOF alert sent: {len(triggered)} funds")
    else:
        print(f"[{now().strftime('%H:%M')}] LOF alert FAILED to send")

if __name__ == "__main__":
    main()
