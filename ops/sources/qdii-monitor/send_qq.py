# NB_TIME_WINDOW_LOF
from datetime import datetime
from zoneinfo import ZoneInfo

_now = datetime.now(ZoneInfo("Asia/Shanghai"))
_wd = _now.weekday()  # 0=Mon ... 6=Sun
_hm = _now.hour * 60 + _now.minute
_in_morning = (9 * 60 + 30) <= _hm <= (11 * 60 + 30)
_in_afternoon = (13 * 60) <= _hm <= (15 * 60)
if not (_wd < 5 and (_in_morning or _in_afternoon)):
    raise SystemExit(0)

#!/usr/bin/env python3
"""
QDII-LOF 套利监控 - 通过 Rust sidecar 执行并返回报告
"""
import os
import sys
import warnings
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

warnings.filterwarnings("ignore", module="requests")
warnings.filterwarnings("ignore", message="urllib3 .* doesn't match a supported version!")
import requests

try:
    from requests import RequestsDependencyWarning
    warnings.simplefilter("ignore", RequestsDependencyWarning)
except Exception:
    pass

SIDE_URL = os.environ.get("LOF_SIDECAR_URL", "http://127.0.0.1:8093")
USE_AKSHARE_CAL = os.environ.get("LOF_USE_AKSHARE_CALENDAR", "0") == "1"
CACHE_MAX_AGE_SECS = int(os.environ.get("LOF_CACHE_MAX_AGE_SECS", "7200"))
RUN_TIMEOUT_SECS = float(os.environ.get("LOF_RUN_TIMEOUT_SECS", "60"))
SH_TZ = ZoneInfo("Asia/Shanghai")


def is_trading_day(check_date=None):
    if check_date is None:
        check_date = date.today()
    if not USE_AKSHARE_CAL:
        return check_date.weekday() < 5
    try:
        import akshare as ak

        df = ak.tool_trade_date_hist_sina()
        trade_dates = df["trade_date"].astype(str).tolist()
        return str(check_date) in trade_dates
    except Exception:
        return check_date.weekday() < 5


def _parse_finished_at(raw: str):
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt.astimezone(SH_TZ)
    except Exception:
        return None


def _is_cache_fresh_for_tag(tag: str, finished_local: datetime) -> bool:
    now = datetime.now(SH_TZ)
    if now - finished_local > timedelta(seconds=CACHE_MAX_AGE_SECS):
        return False

    if finished_local.date() != now.date():
        return False

    if "午" in tag:
        return (finished_local.hour, finished_local.minute) >= (13, 0)
    if "早" in tag:
        return (finished_local.hour, finished_local.minute) >= (9, 30)
    if "收盘" in tag:
        return (finished_local.hour, finished_local.minute) >= (14, 45)
    return True


def load_cached_report(tag: str) -> str:
    try:
        resp = requests.get(f"{SIDE_URL.rstrip('/')}/api/status", timeout=6)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return ""
    last_run = data.get("last_run") or {}
    report = (last_run.get("report") or "").strip()
    status = (last_run.get("status") or "").strip()
    finished_local = _parse_finished_at((last_run.get("finished_at") or "").strip())
    if report and status == "ok" and finished_local and _is_cache_fresh_for_tag(tag, finished_local):
        return report
    return ""



def run_fresh_report(tag: str) -> tuple[str, str]:
    try:
        resp = requests.post(
            f"{SIDE_URL.rstrip('/')}/api/run",
            json={"tag": tag},
            timeout=RUN_TIMEOUT_SECS,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.Timeout:
        return "", f"refresh exceeded {RUN_TIMEOUT_SECS}s"
    except Exception as e:
        return "", str(e)

    report = (data.get("report") or "").strip()
    if report:
        return report, ""
    return "", data.get("error") or "sidecar empty report"

def main() -> int:
    tag = sys.argv[1] if len(sys.argv) > 1 else "早市"

    if not is_trading_day():
        print(f"今日({date.today()})非交易日，不发送QDII监控报告")
        return 0

    report, refresh_error = run_fresh_report(tag)
    if report:
        print(report)
        return 0

    cached = load_cached_report(tag)
    if cached:
        print(f"[WARN] LOF realtime refresh failed, using cached report: {refresh_error}")
        print(cached)
        return 0

    print(f"[WARN] LOF sidecar failed: {refresh_error or 'sidecar empty report'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
