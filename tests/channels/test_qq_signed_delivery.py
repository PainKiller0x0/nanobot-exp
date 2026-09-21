from __future__ import annotations

import pytest

from nanobot.exp.qq import signed_delivery


async def _no_wechat(*args, **kwargs):
    return None


async def _no_yage(*args, **kwargs):
    return None


@pytest.mark.asyncio
async def test_prepare_blocks_unsigned_yage_article() -> None:
    result = await signed_delivery.prepare_outbound_content(
        "[鸭哥 AI 手记] 今日摘要",
        session=None,
        run_wechat_signed=_no_wechat,
        run_yage_signed=_no_yage,
        chat_id="user1",
    )

    assert result.blocked
    assert result.reason == "missing_signature"


@pytest.mark.asyncio
async def test_prepare_valid_signed_payload_strips_wechat_ack(monkeypatch) -> None:
    raw = "NBRAW1-SHA256:" + "a" * 64 + "\n\nraw"

    def fake_verify(content, *, logger=None):
        assert content == raw
        return "正文\n<!-- NBACK_WECHAT sub:2 entry:42 -->"

    monkeypatch.setattr(
        signed_delivery.qq_signatures,
        "verify_and_unwrap_signed_payload",
        fake_verify,
    )

    result = await signed_delivery.prepare_outbound_content(
        raw,
        session=None,
        run_wechat_signed=_no_wechat,
        run_yage_signed=_no_yage,
        chat_id="user1",
    )

    assert not result.blocked
    assert result.is_signed_payload
    assert result.content == "正文"
    assert result.wechat_ack == (2, 42)


@pytest.mark.asyncio
async def test_prepare_recovers_signed_payload_by_digest(monkeypatch) -> None:
    raw = "NBRAW1-SHA256:" + "a" * 64 + "\n\nbroken"
    recovered = "NBRAW1-SHA256:" + "b" * 64 + "\n\nrecovered"

    def fake_verify(content, *, logger=None):
        if content == recovered:
            return "恢复后的正文"
        return None

    async def fake_recover(session, digest, *, timeout_sec, logger=None):
        assert digest == "a" * 64
        return recovered, 3

    monkeypatch.setattr(
        signed_delivery.qq_signatures,
        "verify_and_unwrap_signed_payload",
        fake_verify,
    )
    monkeypatch.setattr(
        signed_delivery.qq_rss_sidecar,
        "recover_wechat_by_digest",
        fake_recover,
    )

    result = await signed_delivery.prepare_outbound_content(
        raw,
        session=object(),
        run_wechat_signed=_no_wechat,
        run_yage_signed=_no_yage,
        chat_id="user1",
    )

    assert not result.blocked
    assert result.content == "恢复后的正文"


@pytest.mark.asyncio
async def test_ack_delivery_notifies_yage_and_wechat(monkeypatch) -> None:
    calls = []

    async def fake_ack_yage(session, source_url, *, timeout_sec, logger=None):
        calls.append(("yage", source_url, timeout_sec))
        return {"status": "ok", "updated": True}

    async def fake_ack_wechat(session, subscription_id, entry_id, *, timeout_sec, logger=None):
        calls.append(("wechat", subscription_id, entry_id, timeout_sec))
        return {"status": "ok", "updated": True}

    monkeypatch.setattr(
        signed_delivery.qq_rss_sidecar,
        "ack_yage_delivery",
        fake_ack_yage,
    )
    monkeypatch.setattr(
        signed_delivery.qq_rss_sidecar,
        "ack_wechat_delivery",
        fake_ack_wechat,
    )

    await signed_delivery.ack_delivery(
        object(),
        "原文链接：[查看原文](https://yage-ai.kit.com/posts/2026-05-08-news)",
        (2, 42),
        chat_id="user1",
    )

    assert calls == [
        ("yage", "https://yage-ai.kit.com/posts/2026-05-08-news", 10.0),
        ("wechat", 2, 42, 10.0),
    ]
