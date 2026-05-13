from nanobot.agent.capability_snapshot import capability_summary, dashboard_snapshot


def test_dashboard_snapshot_fetches_known_endpoints() -> None:
    calls: list[tuple[str, object]] = []

    def fetcher(path: str, default):
        calls.append((path, default))
        return {"path": path}

    snapshot = dashboard_snapshot(fetcher=fetcher)

    assert snapshot["system"] == {"path": "/api/system"}
    assert snapshot["sidecars"] == {"path": "/api/sidecars"}
    assert any(path == "/rss/api/entries?days=1&limit=5" for path, _ in calls)


def test_capability_summary_prefers_dashboard_summary() -> None:
    assert capability_summary({"summary": {"total": 3, "enabled": 2, "healthy": 1}}) == {
        "total": 3,
        "enabled": 2,
        "healthy": 1,
    }
