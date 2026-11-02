"""User-selected final-only QQ delivery; no external calls."""



from types import SimpleNamespace

import pytest
from openai.types.chat import ChatCompletionChunk

pytest.importorskip("botpy")

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.manager import ChannelManager
from nanobot.channels.qq.runtime import QQChannel, QQConfig
from nanobot.config.schema import Config
from nanobot.providers.openai_compat_provider import OpenAICompatProvider


@pytest.mark.asyncio
async def test_qq_waits_for_canonical_and_sends_no_draft_after_one_generation():
    fixture = {"streamed": "Discarded draft.", "canonical": "Final answer."}
    sent, calls = [], []
    bus = MessageBus()
    channel = QQChannel(QQConfig(stream_enabled=False, msg_format="markdown", allow_from=["user1"]), bus)
    channel._client = object()
    channel._tts_enabled["user1"] = False

    async def text(**kwargs):
        sent.append(kwargs["content"])

    async def forbidden(**kwargs):
        raise AssertionError("Final-only QQ must never create stream frames")

    channel._send_text_only = text
    channel._send_stream_frame = forbidden
    await channel._handle_message(sender_id="user1", chat_id="user1", content="Hello",
                                  metadata={"message_id": "incoming-msg"}, is_dm=True)
    incoming = await bus.consume_inbound()
    assert not channel.supports_streaming
    assert "_wants_stream" not in incoming.metadata

    async def create(**kwargs):
        calls.append(kwargs)

        async def chunks():
            for delta, finish in [({"content": fixture["streamed"]}, None),
                                  ({"x_gemini_canonical_text": fixture["canonical"]}, "stop")]:
                assert sent == [], "No draft may escape before the final provider result"
                yield ChatCompletionChunk.model_validate({
                    "id": "one-generation", "object": "chat.completion.chunk", "created": 1,
                    "model": "gemini-test", "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
                })

        return chunks()

    provider = OpenAICompatProvider(api_key="isolated-test", api_base="http://127.0.0.1:1/v1")

    async def client():
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    provider._ensure_client = client
    result = await provider.chat_stream([{"role": "user", "content": "Replay only"}], model="gemini-test")
    assert len(calls) == 1
    assert result.content == fixture["canonical"]
    await channel.send(OutboundMessage(channel="qq", chat_id="user1", content=result.content,
                                       metadata=incoming.metadata))
    assert sent == [fixture["canonical"]]


def test_final_only_qq_overrides_hide_progress_without_changing_other_channels():
    config = Config.model_validate({"channels": {
        "send_progress": True, "send_tool_hints": True, "show_reasoning": True,
        "qq": {"enabled": True, "allow_from": ["user1"], "stream_enabled": False,
               "send_progress": False, "send_tool_hints": False, "show_reasoning": False},
    }})
    manager = ChannelManager(config, MessageBus())
    qq = manager.channels["qq"]
    assert not qq.supports_streaming
    assert not manager._should_send_progress("qq")
    assert not manager._should_send_progress("qq", tool_hint=True)
    assert not qq.show_reasoning
    assert config.channels.send_progress and config.channels.send_tool_hints and config.channels.show_reasoning

