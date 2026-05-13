from __future__ import annotations

from types import SimpleNamespace

import pytest

from nanobot.exp.qq import stream_runtime


def _cfg() -> SimpleNamespace:
    return SimpleNamespace(
        stream_enabled=True,
        msg_format="markdown",
        stream_chunk_chars=20,
        stream_interval_sec=0,
        stream_first_flush_chars=3,
        stream_delta_flush_chars=8,
        stream_delta_flush_interval_sec=999,
    )


@pytest.mark.asyncio
async def test_send_text_streaming_sends_append_frames_and_final_reset() -> None:
    calls = []

    async def fake_frame(**kwargs):
        calls.append(kwargs)
        return "stream-1"

    await stream_runtime.send_text_streaming(
        config=_cfg(),
        send_stream_frame=fake_frame,
        chat_id="user1",
        is_group=False,
        msg_id="msg1",
        content="a" * 45,
    )

    assert [c["state"] for c in calls] == [1, 1, 1, 10]
    assert calls[-1]["reset"] is True
    assert calls[-1]["content"] == "a" * 45
    assert calls[-1]["stream_id"] == "stream-1"


@pytest.mark.asyncio
async def test_send_delta_flushes_first_frame_and_final_reset() -> None:
    frames = []
    texts = []
    states: dict[str, dict] = {}

    async def fake_frame(**kwargs):
        frames.append(kwargs)
        return "qq-stream"

    async def fake_text(**kwargs):
        texts.append(kwargs)

    await stream_runtime.send_delta(
        config=_cfg(),
        stream_states=states,
        chat_type_cache={},
        send_stream_frame=fake_frame,
        send_text_only=fake_text,
        chat_id="user1",
        delta="hello",
        metadata={"message_id": "msg1", "_stream_id": "s1"},
    )
    await stream_runtime.send_delta(
        config=_cfg(),
        stream_states=states,
        chat_type_cache={},
        send_stream_frame=fake_frame,
        send_text_only=fake_text,
        chat_id="user1",
        delta=" world",
        metadata={"message_id": "msg1", "_stream_id": "s1", "_stream_end": True},
    )

    assert texts == []
    assert [c["state"] for c in frames] == [1, 1, 10]
    assert frames[0]["content"] == "hello"
    assert frames[-1]["content"] == "hello world"
    assert frames[-1]["reset"] is True
    assert states == {}


@pytest.mark.asyncio
async def test_send_delta_without_message_id_drops_state_on_end() -> None:
    frames = []
    texts = []
    states: dict[str, dict] = {}

    async def fake_frame(**kwargs):
        frames.append(kwargs)
        return None

    async def fake_text(**kwargs):
        texts.append(kwargs)

    await stream_runtime.send_delta(
        config=_cfg(),
        stream_states=states,
        chat_type_cache={},
        send_stream_frame=fake_frame,
        send_text_only=fake_text,
        chat_id="user1",
        delta="hello",
        metadata={"_stream_id": "s1", "_stream_end": True},
    )

    assert frames == []
    assert texts == []
    assert states == {}
