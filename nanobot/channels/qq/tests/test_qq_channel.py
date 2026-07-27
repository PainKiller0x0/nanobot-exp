import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

# Check optional QQ dependencies before running tests
try:
    from nanobot.channels import qq
    QQ_AVAILABLE = getattr(qq, "QQ_AVAILABLE", False)
except ImportError:
    QQ_AVAILABLE = False

if not QQ_AVAILABLE:
    pytest.skip("QQ dependencies not installed (qq-botpy)", allow_module_level=True)

import aiohttp

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.qq.runtime import QQChannel, QQConfig


class _FakeHttp:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def request(self, route, json):
        self.calls.append(json)
        return {"id": f"raw-{len(self.calls)}"}


class _FakeApi:
    def __init__(self) -> None:
        self.c2c_calls: list[dict] = []
        self.group_calls: list[dict] = []
        self._http = _FakeHttp()

    async def post_c2c_message(self, **kwargs) -> dict[str, str]:
        self.c2c_calls.append(kwargs)
        return {"id": f"c2c-{len(self.c2c_calls)}"}

    async def post_group_message(self, **kwargs) -> dict[str, str]:
        self.group_calls.append(kwargs)
        return {"id": f"group-{len(self.group_calls)}"}


class _FakeClient:
    def __init__(self) -> None:
        self.api = _FakeApi()


@pytest.mark.asyncio
async def test_on_group_message_routes_to_group_chat_id() -> None:
    channel = QQChannel(QQConfig(app_id="app", secret="secret", allow_from=["user1"]), MessageBus())

    data = SimpleNamespace(
        id="msg1",
        content="hello",
        group_openid="group123",
        author=SimpleNamespace(member_openid="user1"),
        attachments=[],
    )

    await channel._on_message(data, is_group=True)

    msg = await channel.bus.consume_inbound()
    assert msg.sender_id == "user1"
    assert msg.chat_id == "group123"


@pytest.mark.asyncio
async def test_on_c2c_message_passes_is_dm_true_to_base_handler() -> None:
    channel = QQChannel(QQConfig(app_id="app", secret="secret", allow_from=["user1"]), MessageBus())
    channel._handle_message = AsyncMock()

    data = SimpleNamespace(
        id="msg-c2c",
        content="hello",
        author=SimpleNamespace(user_openid="user1"),
        attachments=[],
    )

    await channel._on_message(data, is_group=False)

    channel._handle_message.assert_awaited_once()
    kwargs = channel._handle_message.await_args.kwargs
    assert kwargs["sender_id"] == "user1"
    assert kwargs["chat_id"] == "user1"
    assert kwargs["content"] == "hello"
    assert kwargs["is_dm"] is True


@pytest.mark.asyncio
async def test_on_group_message_passes_is_dm_false_to_base_handler() -> None:
    channel = QQChannel(QQConfig(app_id="app", secret="secret", allow_from=["user1"]), MessageBus())
    channel._handle_message = AsyncMock()

    data = SimpleNamespace(
        id="msg-group",
        content="hello",
        group_openid="group123",
        author=SimpleNamespace(member_openid="user1"),
        attachments=[],
    )

    await channel._on_message(data, is_group=True)

    channel._handle_message.assert_awaited_once()
    kwargs = channel._handle_message.await_args.kwargs
    assert kwargs["sender_id"] == "user1"
    assert kwargs["chat_id"] == "group123"
    assert kwargs["content"] == "hello"
    assert kwargs["is_dm"] is False


@pytest.mark.asyncio
async def test_send_group_message_uses_plain_text_group_api_with_msg_seq() -> None:
    channel = QQChannel(QQConfig(app_id="app", secret="secret", allow_from=["*"]), MessageBus())
    channel._client = _FakeClient()
    channel._chat_type_cache["group123"] = "group"

    await channel.send(
        OutboundMessage(
            channel="qq",
            chat_id="group123",
            content="hello",
            metadata={"message_id": "msg1"},
        )
    )

    assert len(channel._client.api.group_calls) == 1
    call = channel._client.api.group_calls[0]
    assert call == {
        "group_openid": "group123",
        "msg_type": 0,
        "content": "hello",
        "msg_id": "msg1",
        "msg_seq": 2,
    }
    assert not channel._client.api.c2c_calls


@pytest.mark.asyncio
async def test_send_c2c_message_uses_plain_text_c2c_api_with_msg_seq() -> None:
    channel = QQChannel(QQConfig(app_id="app", secret="secret", allow_from=["*"]), MessageBus())
    channel._client = _FakeClient()

    await channel.send(
        OutboundMessage(
            channel="qq",
            chat_id="user123",
            content="hello",
            metadata={"message_id": "msg1"},
        )
    )

    assert len(channel._client.api.c2c_calls) == 1
    call = channel._client.api.c2c_calls[0]
    assert call == {
        "openid": "user123",
        "msg_type": 0,
        "content": "hello",
        "msg_id": "msg1",
        "msg_seq": 2,
    }
    assert not channel._client.api.group_calls


@pytest.mark.asyncio
async def test_send_c2c_empty_response_retries_same_msg_seq_when_enabled() -> None:
    class _FlakyApi(_FakeApi):
        async def post_c2c_message(self, **kwargs):
            self.c2c_calls.append(kwargs)
            if len(self.c2c_calls) == 1:
                return None
            return {"id": "ok"}

    channel = QQChannel(
        QQConfig(
            app_id="app",
            secret="secret",
            allow_from=["*"],
            send_retry_on_empty_response=True,
            send_retry_attempts=1,
            send_retry_delay_sec=0,
        ),
        MessageBus(),
    )
    channel._client = _FakeClient()
    channel._client.api = _FlakyApi()

    await channel.send(
        OutboundMessage(
            channel="qq",
            chat_id="user123",
            content="hello",
            metadata={"message_id": "msg1"},
        )
    )

    assert len(channel._client.api.c2c_calls) == 2
    assert channel._client.api.c2c_calls[0]["msg_seq"] == 2
    assert channel._client.api.c2c_calls[1]["msg_seq"] == 2


@pytest.mark.asyncio
async def test_send_c2c_empty_response_without_msg_id_does_not_retry() -> None:
    class _EmptyApi(_FakeApi):
        async def post_c2c_message(self, **kwargs):
            self.c2c_calls.append(kwargs)
            return None

    channel = QQChannel(
        QQConfig(
            app_id="app",
            secret="secret",
            allow_from=["*"],
            send_retry_on_empty_response=True,
            send_retry_attempts=1,
            send_retry_delay_sec=0,
        ),
        MessageBus(),
    )
    channel._client = _FakeClient()
    channel._client.api = _EmptyApi()

    await channel.send(OutboundMessage(channel="qq", chat_id="user123", content="hello"))

    assert len(channel._client.api.c2c_calls) == 1


@pytest.mark.asyncio
async def test_send_group_message_uses_markdown_when_configured() -> None:
    channel = QQChannel(
        QQConfig(app_id="app", secret="secret", allow_from=["*"], msg_format="markdown"),
        MessageBus(),
    )
    channel._client = _FakeClient()
    channel._chat_type_cache["group123"] = "group"

    await channel.send(
        OutboundMessage(
            channel="qq",
            chat_id="group123",
            content="**hello**",
            metadata={"message_id": "msg1"},
        )
    )

    assert len(channel._client.api.group_calls) == 1
    call = channel._client.api.group_calls[0]
    assert call == {
        "group_openid": "group123",
        "msg_type": 2,
        "markdown": {"content": "**hello**"},
        "msg_id": "msg1",
        "msg_seq": 2,
    }


@pytest.mark.asyncio
async def test_send_c2c_markdown_stream_when_enabled() -> None:
    channel = QQChannel(
        QQConfig(
            app_id="app",
            secret="secret",
            allow_from=["*"],
            msg_format="markdown",
            stream_enabled=True,
            stream_min_chars=1,
            stream_chunk_chars=8,
            stream_interval_sec=0,
        ),
        MessageBus(),
    )
    channel._client = _FakeClient()

    content = "line one\\nline two\\nline three"
    await channel.send(
        OutboundMessage(
            channel="qq",
            chat_id="user123",
            content=content,
            metadata={"message_id": "msg1"},
        )
    )

    calls = channel._client.api._http.calls
    assert len(calls) >= 2
    assert all(call["msg_type"] == 2 for call in calls)
    assert all("stream" in call for call in calls)
    assert calls[0]["stream"] == {"state": 1, "index": 0, "reset": False}
    assert calls[1]["stream"]["id"] == "raw-1"
    assert calls[-1]["stream"] == {"state": 10, "id": f"raw-{len(calls) - 1}", "index": len(calls) - 1, "reset": False}
    assert calls[-1]["markdown"] == {"content": ""}
    assert not channel._client.api.c2c_calls
    assert not channel._client.api.group_calls


@pytest.mark.asyncio
async def test_qq_supports_streaming_when_stream_enabled() -> None:
    channel = QQChannel(
        QQConfig(
            app_id="app",
            secret="secret",
            allow_from=["*"],
            msg_format="markdown",
            stream_enabled=True,
        ),
        MessageBus(),
    )
    data = SimpleNamespace(
        id="msg-stream",
        content="hello stream",
        author=SimpleNamespace(user_openid="user123"),
        attachments=[],
    )

    await channel._on_message(data, is_group=False)

    msg = await channel.bus.consume_inbound()
    assert msg.metadata["_wants_stream"] is True
    assert msg.metadata["message_id"] == "msg-stream"


@pytest.mark.asyncio
async def test_send_delta_waits_for_first_frame_min_chars() -> None:
    channel = QQChannel(
        QQConfig(
            app_id="app",
            secret="secret",
            allow_from=["*"],
            msg_format="markdown",
            stream_enabled=True,
            stream_min_chars=1,
            stream_first_flush_chars=10,
            stream_defer_first_frame_until_end=False,
            stream_delta_flush_chars=20,
            stream_delta_flush_interval_sec=0,
        ),
        MessageBus(),
    )
    channel._client = _FakeClient()

    metadata = {"_stream_id": "s-first", "_stream_delta": True, "message_id": "msg1"}
    await channel.send_delta("user123", "hi", metadata)
    assert channel._client.api._http.calls == []

    await channel.send_delta("user123", " there friend.", metadata)
    calls = channel._client.api._http.calls
    assert len(calls) == 1
    assert calls[0]["markdown"] == {"content": "hi there friend."}
    assert calls[0]["stream"] == {"state": 1, "index": 0, "reset": False}


@pytest.mark.asyncio
async def test_send_delta_streams_and_finalizes_with_raw_http() -> None:
    channel = QQChannel(
        QQConfig(
            app_id="app",
            secret="secret",
            allow_from=["*"],
            msg_format="markdown",
            stream_enabled=True,
            stream_min_chars=1,
            stream_first_flush_chars=1,
            stream_defer_first_frame_until_end=False,
            stream_delta_flush_chars=20,
            stream_delta_flush_interval_sec=999,
        ),
        MessageBus(),
    )
    channel._client = _FakeClient()

    metadata = {"_stream_id": "s1", "_stream_delta": True, "message_id": "msg1"}
    await channel.send_delta("user123", "hi.", metadata)
    await channel.send_delta("user123", " there", metadata)
    await channel.send_delta(
        "user123",
        "",
        {"_stream_id": "s1", "_stream_end": True, "message_id": "msg1"},
    )

    calls = channel._client.api._http.calls
    assert len(calls) == 3
    assert calls[0]["markdown"] == {"content": "hi."}
    assert calls[0]["stream"] == {"state": 1, "index": 0, "reset": False}
    assert calls[1]["markdown"] == {"content": " there"}
    assert calls[1]["stream"]["id"] == "raw-1"
    assert calls[2]["markdown"] == {"content": "hi. there"}
    assert calls[2]["stream"] == {"state": 10, "id": "raw-2", "index": 2, "reset": True}
    assert "s1" not in channel._stream_states
    assert not channel._client.api.c2c_calls


@pytest.mark.asyncio
async def test_read_media_bytes_local_path() -> None:
    channel = QQChannel(QQConfig(app_id="app", secret="secret"), MessageBus())

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(b"\x89PNG\r\n")
        tmp_path = f.name

    data, filename = await channel._read_media_bytes(tmp_path)
    assert data == b"\x89PNG\r\n"
    assert filename == Path(tmp_path).name


@pytest.mark.asyncio
async def test_read_media_bytes_file_uri() -> None:
    channel = QQChannel(QQConfig(app_id="app", secret="secret"), MessageBus())

    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
        f.write(b"JFIF")
        tmp_path = f.name

    data, filename = await channel._read_media_bytes(f"file://{tmp_path}")
    assert data == b"JFIF"
    assert filename == Path(tmp_path).name


@pytest.mark.asyncio
async def test_read_media_bytes_missing_file() -> None:
    channel = QQChannel(QQConfig(app_id="app", secret="secret"), MessageBus())

    data, filename = await channel._read_media_bytes("/nonexistent/path/image.png")
    assert data is None
    assert filename is None


# -------------------------------------------------------
# Tests for _send_media exception handling
# -------------------------------------------------------

def _make_channel_with_local_file(suffix: str = ".png", content: bytes = b"\x89PNG\r\n"):
    """Create a QQChannel with a fake client and a temp file for media."""
    channel = QQChannel(
        QQConfig(app_id="app", secret="secret", allow_from=["*"]),
        MessageBus(),
    )
    channel._client = _FakeClient()
    channel._chat_type_cache["user1"] = "c2c"

    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    tmp.write(content)
    tmp.close()
    return channel, tmp.name


@pytest.mark.asyncio
async def test_send_media_network_error_propagates() -> None:
    """aiohttp.ClientError (network/transport) should re-raise, not return False."""
    channel, tmp_path = _make_channel_with_local_file()

    # Make the base64 upload raise a network error
    channel._client.api._http = SimpleNamespace()
    channel._client.api._http.request = AsyncMock(
        side_effect=aiohttp.ServerDisconnectedError("connection lost"),
    )

    with pytest.raises(aiohttp.ServerDisconnectedError):
        await channel._send_media(
            chat_id="user1",
            media_ref=tmp_path,
            msg_id="msg1",
            is_group=False,
        )


@pytest.mark.asyncio
async def test_send_media_client_connector_error_propagates() -> None:
    """aiohttp.ClientConnectorError (DNS/connection refused) should re-raise."""
    channel, tmp_path = _make_channel_with_local_file()

    from aiohttp.client_reqrep import ConnectionKey
    conn_key = ConnectionKey("api.qq.com", 443, True, None, None, None, None)
    connector_error = aiohttp.ClientConnectorError(
        connection_key=conn_key,
        os_error=OSError("Connection refused"),
    )

    channel._client.api._http = SimpleNamespace()
    channel._client.api._http.request = AsyncMock(
        side_effect=connector_error,
    )

    with pytest.raises(aiohttp.ClientConnectorError):
        await channel._send_media(
            chat_id="user1",
            media_ref=tmp_path,
            msg_id="msg1",
            is_group=False,
        )


@pytest.mark.asyncio
async def test_send_media_oserror_propagates() -> None:
    """OSError (low-level I/O) should re-raise for retry."""
    channel, tmp_path = _make_channel_with_local_file()

    channel._client.api._http = SimpleNamespace()
    channel._client.api._http.request = AsyncMock(
        side_effect=OSError("Network is unreachable"),
    )

    with pytest.raises(OSError):
        await channel._send_media(
            chat_id="user1",
            media_ref=tmp_path,
            msg_id="msg1",
            is_group=False,
        )


@pytest.mark.asyncio
async def test_send_media_api_error_returns_false() -> None:
    """API-level errors (botpy RuntimeError subclasses) should return False, not raise."""
    channel, tmp_path = _make_channel_with_local_file()

    # Simulate a botpy API error (e.g. ServerError is a RuntimeError subclass)
    from botpy.errors import ServerError

    channel._client.api._http = SimpleNamespace()
    channel._client.api._http.request = AsyncMock(
        side_effect=ServerError("internal server error"),
    )

    result = await channel._send_media(
        chat_id="user1",
        media_ref=tmp_path,
        msg_id="msg1",
        is_group=False,
    )
    assert result is False


@pytest.mark.asyncio
async def test_send_media_generic_runtime_error_returns_false() -> None:
    """Generic RuntimeError (not network) should return False."""
    channel, tmp_path = _make_channel_with_local_file()

    channel._client.api._http = SimpleNamespace()
    channel._client.api._http.request = AsyncMock(
        side_effect=RuntimeError("some API error"),
    )

    result = await channel._send_media(
        chat_id="user1",
        media_ref=tmp_path,
        msg_id="msg1",
        is_group=False,
    )
    assert result is False


@pytest.mark.asyncio
async def test_send_media_value_error_returns_false() -> None:
    """ValueError (bad API response data) should return False."""
    channel, tmp_path = _make_channel_with_local_file()

    channel._client.api._http = SimpleNamespace()
    channel._client.api._http.request = AsyncMock(
        side_effect=ValueError("bad response data"),
    )

    result = await channel._send_media(
        chat_id="user1",
        media_ref=tmp_path,
        msg_id="msg1",
        is_group=False,
    )
    assert result is False


@pytest.mark.asyncio
async def test_send_media_timeout_error_propagates() -> None:
    """asyncio.TimeoutError inherits from Exception but not ClientError/OSError.
    However, aiohttp.ServerTimeoutError IS a ClientError subclass, so that propagates.
    For a plain TimeoutError (which is also OSError in Python 3.11+), it should propagate."""
    channel, tmp_path = _make_channel_with_local_file()

    channel._client.api._http = SimpleNamespace()
    channel._client.api._http.request = AsyncMock(
        side_effect=aiohttp.ServerTimeoutError("request timed out"),
    )

    with pytest.raises(aiohttp.ServerTimeoutError):
        await channel._send_media(
            chat_id="user1",
            media_ref=tmp_path,
            msg_id="msg1",
            is_group=False,
        )


@pytest.mark.asyncio
async def test_send_fallback_text_on_api_error() -> None:
    """When _send_media returns False (API error), send() should emit fallback text."""
    channel, tmp_path = _make_channel_with_local_file()

    from botpy.errors import ServerError

    channel._client.api._http = SimpleNamespace()
    channel._client.api._http.request = AsyncMock(
        side_effect=ServerError("internal server error"),
    )

    await channel.send(
        OutboundMessage(
            channel="qq",
            chat_id="user1",
            content="",
            media=[tmp_path],
            metadata={"message_id": "msg1"},
        )
    )

    # Should have sent a fallback text message
    assert len(channel._client.api.c2c_calls) == 1
    fallback_content = channel._client.api.c2c_calls[0]["content"]
    assert "Attachment send failed" in fallback_content


@pytest.mark.asyncio
async def test_send_propagates_network_error_no_fallback() -> None:
    """When _send_media raises a network error, send() should NOT silently fallback."""
    channel, tmp_path = _make_channel_with_local_file()

    channel._client.api._http = SimpleNamespace()
    channel._client.api._http.request = AsyncMock(
        side_effect=aiohttp.ServerDisconnectedError("connection lost"),
    )

    with pytest.raises(aiohttp.ServerDisconnectedError):
        await channel.send(
            OutboundMessage(
                channel="qq",
                chat_id="user1",
                content="hello",
                media=[tmp_path],
                metadata={"message_id": "msg1"},
            )
        )

    # No fallback text should have been sent
    assert len(channel._client.api.c2c_calls) == 0


@pytest.mark.asyncio
async def test_open_voice_reply_is_handled_locally_without_llm(monkeypatch) -> None:
    monkeypatch.setenv("MIMO_API_KEY", "test-key")
    channel = QQChannel(QQConfig(app_id="app", secret="secret", allow_from=["user1"]), MessageBus())
    channel._send_text_only = AsyncMock()
    channel._handle_message = AsyncMock()
    data = SimpleNamespace(
        id="msg-tts",
        content="打开语音回复",
        author=SimpleNamespace(user_openid="user1"),
        attachments=[],
    )

    await channel._on_message(data, is_group=False)

    assert channel._tts_enabled["user1"] is True
    channel._handle_message.assert_not_awaited()
    channel._send_text_only.assert_awaited_once()
    assert channel._send_text_only.await_args.kwargs["content"].startswith("已开启语音回复模式")

@pytest.mark.asyncio
async def test_open_voice_reply_reports_missing_service_key_locally(monkeypatch) -> None:
    monkeypatch.delenv("MIMO_API_KEY", raising=False)
    channel = QQChannel(QQConfig(app_id="app", secret="secret", allow_from=["user1"]), MessageBus())
    channel._send_text_only = AsyncMock()
    channel._handle_message = AsyncMock()
    data = SimpleNamespace(
        id="msg-tts-unavailable",
        content="打开语音回复",
        author=SimpleNamespace(user_openid="user1"),
        attachments=[],
    )

    await channel._on_message(data, is_group=False)

    assert channel._tts_enabled["user1"] is False
    channel._handle_message.assert_not_awaited()
    assert "暂不可用" in channel._send_text_only.await_args.kwargs["content"]



@pytest.mark.asyncio
async def test_send_delta_accepts_upstream_stream_contract() -> None:
    channel = QQChannel(
        QQConfig(
            app_id="app",
            secret="secret",
            allow_from=["*"],
            msg_format="markdown",
            stream_enabled=True,
            stream_min_chars=1,
            stream_first_flush_chars=1,
            stream_defer_first_frame_until_end=False,
            stream_delta_flush_chars=20,
            stream_delta_flush_interval_sec=0,
        ),
        MessageBus(),
    )
    channel._client = _FakeClient()
    metadata = {"message_id": "msg-upstream"}

    await channel.send_delta("user123", "hello.", metadata, stream_id="upstream-s")
    await channel.send_delta(
        "user123",
        "",
        metadata,
        stream_id="upstream-s",
        stream_end=True,
    )

    assert "upstream-s" not in channel._stream_states
    assert channel._client.api._http.calls


@pytest.mark.asyncio
async def test_send_delta_resuming_merge_next_keeps_stream_state() -> None:
    channel = QQChannel(
        QQConfig(
            app_id="app",
            secret="secret",
            allow_from=["*"],
            msg_format="markdown",
            stream_enabled=True,
            stream_min_chars=1,
            stream_first_flush_chars=1,
            stream_defer_first_frame_until_end=False,
            stream_delta_flush_chars=20,
            stream_delta_flush_interval_sec=0,
        ),
        MessageBus(),
    )
    channel._client = _FakeClient()
    metadata = {"message_id": "msg-resume"}

    await channel.send_delta("user123", "first", metadata, stream_id="resume-s")
    await channel.send_delta(
        "user123",
        " boundary",
        metadata,
        stream_id="resume-s",
        stream_end=True,
        resuming=True,
        merge_next=True,
    )
    assert "resume-s" in channel._stream_states

    await channel.send_delta("user123", " second", metadata, stream_id="resume-s")
    await channel.send_delta(
        "user123",
        "",
        metadata,
        stream_id="resume-s",
        stream_end=True,
    )

    assert "resume-s" not in channel._stream_states
