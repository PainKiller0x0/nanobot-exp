"""Tests for QQ article runtime adapters."""

import pytest

from nanobot.exp.qq import article_runtime


@pytest.mark.asyncio
async def test_run_sidecar_json_prefers_rust_adapter(monkeypatch) -> None:
    calls: list[tuple] = []

    async def fake_run_client_json(session, args, *, timeout_sec, logger=None):
        calls.append((session, list(args), timeout_sec))
        return {"status": "ok"}

    monkeypatch.setattr(article_runtime.rss_sidecar, "run_client_json", fake_run_client_json)

    result = await article_runtime.run_sidecar_json("session", ["latest"], timeout_sec=3.0)

    assert result == {"status": "ok"}
    assert calls == [("session", ["latest"], 3.0)]


@pytest.mark.asyncio
async def test_run_yage_signed_prefers_rust_adapter(monkeypatch) -> None:
    calls: list[tuple] = []

    async def fake_yage_signed(session, *, timeout_sec, nth, target_date, force_latest, logger=None):
        calls.append((session, timeout_sec, nth, target_date, force_latest))
        return "signed-yage"

    monkeypatch.setattr(article_runtime.rss_sidecar, "yage_signed", fake_yage_signed)

    result = await article_runtime.run_yage_signed(
        "session",
        timeout_sec=4.0,
        nth=2,
        target_date=None,
        force_latest=False,
    )

    assert result == "signed-yage"
    assert calls == [("session", 4.0, 2, None, False)]


@pytest.mark.asyncio
async def test_run_wechat_signed_rejects_invalid_subscription(monkeypatch) -> None:
    async def fail_if_called(*args, **kwargs):
        raise AssertionError("rust adapter should not be called")

    monkeypatch.setattr(article_runtime.rss_sidecar, "wechat_signed", fail_if_called)

    assert await article_runtime.run_wechat_signed("session", 0) is None


@pytest.mark.asyncio
async def test_run_wechat_signed_prefers_rust_adapter(monkeypatch) -> None:
    calls: list[tuple] = []

    async def fake_wechat_signed(session, subscription_id, *, timeout_sec, force, logger=None):
        calls.append((session, subscription_id, timeout_sec, force))
        return "signed-wechat"

    monkeypatch.setattr(article_runtime.rss_sidecar, "wechat_signed", fake_wechat_signed)

    result = await article_runtime.run_wechat_signed(
        "session",
        3,
        timeout_sec=5.0,
        force=False,
    )

    assert result == "signed-wechat"
    assert calls == [("session", 3, 5.0, False)]
