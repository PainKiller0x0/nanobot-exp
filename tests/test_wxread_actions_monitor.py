import unittest
from datetime import date, datetime, timezone

from ops.scripts.wxread_actions_monitor import SHANGHAI, assess_day, check_runs


def run(created_at: str, status: str, conclusion: str | None = None) -> dict[str, object]:
    return {
        "created_at": created_at,
        "status": status,
        "conclusion": conclusion,
        "html_url": "https://github.com/PainKiller0x0/wxread/actions/runs/1",
    }


class WxreadActionsMonitorTests(unittest.TestCase):
    def test_current_success_is_silent(self) -> None:
        now = datetime(2026, 11, 10, 9, 15, tzinfo=SHANGHAI)
        runs = [run("2026-11-10T00:55:00Z", "completed", "success")]

        self.assertEqual(check_runs(runs, now), [])


    def test_missing_current_run_is_reported(self) -> None:
        now = datetime(2026, 11, 10, 9, 15, tzinfo=SHANGHAI)

        alerts = check_runs([], now)

        self.assertEqual(len(alerts), 1)
        self.assertIn("2026-11-10", alerts[0])
        self.assertIn("没有启动记录", alerts[0])


    def test_current_run_in_progress_is_not_called_missing(self) -> None:
        now = datetime(2026, 11, 10, 9, 15, tzinfo=SHANGHAI)
        runs = [run("2026-11-10T00:55:00Z", "in_progress")]

        self.assertEqual(check_runs(runs, now), [])


    def test_latest_failed_run_is_reported(self) -> None:
        now = datetime(2026, 11, 10, 9, 15, tzinfo=SHANGHAI)
        runs = [run("2026-11-10T00:55:00Z", "completed", "failure")]

        alerts = check_runs(runs, now)

        self.assertEqual(len(alerts), 1)
        self.assertIn("failure", alerts[0])
        self.assertIn("actions/runs/1", alerts[0])


    def test_yesterdays_long_running_job_is_reported(self) -> None:
        now = datetime(2026, 11, 10, 9, 15, tzinfo=SHANGHAI)
        started = datetime(2026, 11, 9, 0, 0, tzinfo=timezone.utc)
        runs = [run(started.isoformat(), "in_progress")]

        alert = assess_day(runs, date(2026, 11, 9), now, required=False)

        self.assertIsNotNone(alert)
        self.assertIn("超过 4 小时", alert or "")
