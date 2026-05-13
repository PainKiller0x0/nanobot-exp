"""Tests for QQ text transport helpers."""

import asyncio

import pytest

from nanobot.exp.qq import text_transport


def test_build_text_payload_strips_silent_marker_and_uses_markdown() -> None:
    payload = text_transport.build_text_payload(
        content="hello (NOOUTPUTKEEP_SILENT)",
        msg_id="m1",
        msg_seq=2,
        use_markdown=True,
    )

    assert payload == {
        "msg_type": 2,
        "msg_id": "m1",
        "msg_seq": 2,
        "markdown": {"content": "hello"},
    }


def test_build_text_payload_returns_none_for_empty() -> None:
    assert text_transport.build_text_payload(
        content="(NOOUTPUTKEEP_SILENT)",
        msg_id=None,
        msg_seq=1,
        use_markdown=False,
    ) is None


def test_build_stream_payload_includes_stream_id_when_present() -> None:
    payload = text_transport.build_stream_payload(
        content="hello",
        msg_id="m1",
        msg_seq=3,
        state=1,
        index=2,
        reset=False,
        stream_id="sid",
    )

    assert payload["stream"] == {"state": 1, "index": 2, "reset": False, "id": "sid"}
    assert payload["markdown"] == {"content": "hello"}


class _FakeApi:
    def __init__(self) -> None:
        self.group_calls: list[dict] = []
        self.c2c_calls: list[dict] = []
        self._http = type("Http", (), {"timeout": None})()

    async def post_group_message(self, **kwargs):
        self.group_calls.append(kwargs)
        return {"ok": True}

    async def post_c2c_message(self, **kwargs):
        self.c2c_calls.append(kwargs)
        return {"ok": True}


class _FakeClient:
    def __init__(self) -> None:
        self.api = _FakeApi()


@pytest.mark.asyncio
async def test_post_text_payload_routes_group_and_sets_timeout() -> None:
    client = _FakeClient()

    result = await text_transport.post_text_payload(
        client,
        chat_id="g1",
        is_group=True,
        msg_id="m1",
        payload={"msg_seq": 2, "content": "hello"},
        timeout_sec=4.5,
        retry_on_empty_response=False,
        retry_attempts=0,
        retry_delay_sec=0,
    )

    assert result == {"ok": True}
    assert client.api._http.timeout == 4.5
    assert client.api.group_calls == [
        {"group_openid": "g1", "msg_seq": 2, "content": "hello"}
    ]


@pytest.mark.asyncio
async def test_post_text_payload_retries_empty_passive_reply() -> None:
    class RetryApi(_FakeApi):
        def __init__(self) -> None:
            super().__init__()
            self.count = 0

        async def post_c2c_message(self, **kwargs):
            self.count += 1
            self.c2c_calls.append(kwargs)
            if self.count == 1:
                return None
            return {"ok": True}

    client = _FakeClient()
    client.api = RetryApi()

    result = await text_transport.post_text_payload(
        client,
        chat_id="u1",
        is_group=False,
        msg_id="m1",
        payload={"msg_seq": 2, "content": "hello"},
        timeout_sec=0,
        retry_on_empty_response=True,
        retry_attempts=1,
        retry_delay_sec=0,
    )

    assert result == {"ok": True}
    assert len(client.api.c2c_calls) == 2


@pytest.mark.asyncio
async def test_post_text_payload_raises_after_retry_exhausted() -> None:
    class EmptyApi(_FakeApi):
        async def post_c2c_message(self, **kwargs):
            return None

    client = _FakeClient()
    client.api = EmptyApi()

    with pytest.raises(asyncio.TimeoutError):
        await text_transport.post_text_payload(
            client,
            chat_id="u1",
            is_group=False,
            msg_id="m1",
            payload={"msg_seq": 2, "content": "hello"},
            timeout_sec=0,
            retry_on_empty_response=True,
            retry_attempts=0,
            retry_delay_sec=0,
        )
