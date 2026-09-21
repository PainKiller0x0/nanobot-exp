from __future__ import annotations

import pytest

from nanobot.exp.qq import rss_sidecar


def test_argv_params_latest() -> None:
    parsed = rss_sidecar._argv_params(  # type: ignore[attr-defined]
        ["latest", "--days", "7", "--limit", "50", "--subscription-id", "2", "--refresh"]
    )

    assert parsed == (
        "/api/latest",
        {
            "days": "7",
            "limit": "50",
            "subscription_id": "2",
            "refresh": "true",
        },
    )


def test_argv_params_ask_keeps_question() -> None:
    parsed = rss_sidecar._argv_params(  # type: ignore[attr-defined]
        ["ask", "--question", "Alpha 是什么", "--entry-id", "42"]
    )

    assert parsed == (
        "/api/ask",
        {
            "question": "Alpha 是什么",
            "entry_id": "42",
        },
    )


def test_argv_params_ignores_unknown_command() -> None:
    assert rss_sidecar._argv_params(["timeline"]) is None  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_recover_wechat_by_digest_calls_rust_endpoint(monkeypatch) -> None:
    calls = []

    async def fake_get_json(session, path, params, *, timeout_sec, logger=None):
        calls.append((session, path, params, timeout_sec))
        return {
            "status": "ok",
            "signed_payload": "NBRAW1-SHA256:abc\n\nbody",
            "subscription_id": 2,
        }

    monkeypatch.setattr(rss_sidecar, "_get_json", fake_get_json)

    assert await rss_sidecar.recover_wechat_by_digest(object(), "abc", timeout_sec=9) == (
        "NBRAW1-SHA256:abc\n\nbody",
        2,
    )
    assert calls == [(calls[0][0], "/api/push/wechat-recover", {"digest": "abc"}, 9)]


@pytest.mark.asyncio
async def test_ack_wechat_delivery_ignores_invalid_marker(monkeypatch) -> None:
    async def fake_get_json(*args, **kwargs):  # pragma: no cover - must not be called
        raise AssertionError("unexpected network call")

    monkeypatch.setattr(rss_sidecar, "_get_json", fake_get_json)

    assert await rss_sidecar.ack_wechat_delivery(object(), 1, 0) is None
    assert await rss_sidecar.ack_wechat_delivery(object(), -1, 3) is None


@pytest.mark.asyncio
async def test_ack_yage_delivery_calls_rust_endpoint(monkeypatch) -> None:
    calls = []

    async def fake_get_json(session, path, params, *, timeout_sec, logger=None):
        calls.append((path, params, timeout_sec))
        return {"status": "ok", "updated": True}

    monkeypatch.setattr(rss_sidecar, "_get_json", fake_get_json)

    result = await rss_sidecar.ack_yage_delivery(
        object(),
        " https://yage-ai.kit.com/posts/2026-05-08-x ",
    )
    assert result == {
        "status": "ok",
        "updated": True,
    }
    assert calls == [
        (
            "/api/push/yage-ack",
            {"url": "https://yage-ai.kit.com/posts/2026-05-08-x"},
            10.0,
        )
    ]
