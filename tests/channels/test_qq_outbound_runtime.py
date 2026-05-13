"""Tests for QQ outbound send orchestration."""

from types import SimpleNamespace

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.exp.qq import outbound_runtime


def _prepared(
    *,
    content: str = "hello",
    suppressed: bool = False,
    blocked: bool = False,
    is_signed_payload: bool = False,
):
    return SimpleNamespace(
        content=content,
        suppressed=suppressed,
        blocked=blocked,
        reason="test",
        is_signed_payload=is_signed_payload,
        wechat_ack=None,
    )


async def _none(*args, **kwargs):
    return None


@pytest.mark.asyncio
async def test_send_outbound_reports_media_failure(monkeypatch) -> None:
    texts: list[dict] = []

    async def fake_media(**kwargs):
        return False

    async def fake_text(**kwargs):
        texts.append(kwargs)

    async def fake_prepare(*args, **kwargs):
        return _prepared(content="")

    monkeypatch.setattr(outbound_runtime.signed_delivery, "prepare_outbound_content", fake_prepare)

    await outbound_runtime.send_outbound(
        OutboundMessage(channel="qq", chat_id="user1", content="", media=["https://x.test/a.png"]),
        session=None,
        chat_type_cache={},
        text_chunk_max_len=1200,
        send_media=fake_media,
        send_text_only=fake_text,
        send_text_streaming=_none,
        should_stream_text=lambda **kwargs: False,
        run_wechat_signed=_none,
        run_yage_signed=_none,
        report_signature_blocked=_none,
    )

    assert texts == [
        {
            "chat_id": "user1",
            "is_group": False,
            "msg_id": None,
            "content": "[Attachment send failed: a.png]",
        }
    ]


@pytest.mark.asyncio
async def test_send_outbound_uses_streaming_when_allowed(monkeypatch) -> None:
    streamed: list[dict] = []
    texts: list[dict] = []

    async def fake_prepare(*args, **kwargs):
        return _prepared(content="hello stream")

    async def fake_stream(**kwargs):
        streamed.append(kwargs)

    async def fake_text(**kwargs):
        texts.append(kwargs)

    monkeypatch.setattr(outbound_runtime.signed_delivery, "prepare_outbound_content", fake_prepare)

    await outbound_runtime.send_outbound(
        OutboundMessage(channel="qq", chat_id="g1", content="hello", metadata={"message_id": "m1"}),
        session=None,
        chat_type_cache={"g1": "group"},
        text_chunk_max_len=1200,
        send_media=lambda **kwargs: _none(),
        send_text_only=fake_text,
        send_text_streaming=fake_stream,
        should_stream_text=lambda **kwargs: True,
        run_wechat_signed=_none,
        run_yage_signed=_none,
        report_signature_blocked=_none,
    )

    assert texts == []
    assert streamed == [
        {
            "chat_id": "g1",
            "is_group": True,
            "msg_id": "m1",
            "content": "hello stream",
        }
    ]


@pytest.mark.asyncio
async def test_send_outbound_blocks_failed_signature(monkeypatch) -> None:
    reports: list[dict] = []

    async def fake_prepare(*args, **kwargs):
        return _prepared(blocked=True)

    async def fake_report(**kwargs):
        reports.append(kwargs)

    monkeypatch.setattr(outbound_runtime.signed_delivery, "prepare_outbound_content", fake_prepare)

    await outbound_runtime.send_outbound(
        OutboundMessage(channel="qq", chat_id="g1", content="bad", metadata={"message_id": "m1"}),
        session=None,
        chat_type_cache={"g1": "group"},
        text_chunk_max_len=1200,
        send_media=_none,
        send_text_only=_none,
        send_text_streaming=_none,
        should_stream_text=lambda **kwargs: False,
        run_wechat_signed=_none,
        run_yage_signed=_none,
        report_signature_blocked=fake_report,
    )

    assert reports == [
        {
            "source_chat_id": "g1",
            "source_is_group": True,
            "source_msg_id": "m1",
        }
    ]


@pytest.mark.asyncio
async def test_send_outbound_chunks_plain_text(monkeypatch) -> None:
    texts: list[str] = []

    async def fake_prepare(*args, **kwargs):
        return _prepared(content="a" * 450)

    async def fake_text(**kwargs):
        texts.append(kwargs["content"])

    monkeypatch.setattr(outbound_runtime.signed_delivery, "prepare_outbound_content", fake_prepare)

    await outbound_runtime.send_outbound(
        OutboundMessage(channel="qq", chat_id="user1", content="hello"),
        session=None,
        chat_type_cache={},
        text_chunk_max_len=200,
        send_media=_none,
        send_text_only=fake_text,
        send_text_streaming=_none,
        should_stream_text=lambda **kwargs: False,
        run_wechat_signed=_none,
        run_yage_signed=_none,
        report_signature_blocked=_none,
    )

    assert [len(t) for t in texts] == [200, 200, 50]
