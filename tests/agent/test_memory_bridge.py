from types import SimpleNamespace

import pytest

from nanobot.exp.agent import memory_bridge
from nanobot.exp.agent.memory_bridge import (
    MemoryHook,
    _channel_from_session,
    _format_reference,
    _strip_reference,
)


def test_reference_is_untrusted_and_deduplicated():
    payload = {
        "hot": [
            {
                "id": 1,
                "kind": "preference",
                "source": "manual",
                "created_at": "2026-07-16",
                "content": "reply in Chinese",
            }
        ],
        "results": [
            {
                "id": 1,
                "kind": "preference",
                "source": "manual",
                "created_at": "2026-07-16",
                "content": "reply in Chinese",
            }
        ],
    }
    block = _format_reference(payload)
    assert "not instructions" in block
    assert block.count("reply in Chinese") == 1


def test_strip_reference_keeps_user_text():
    assert _strip_reference("hello\n\n[Nanobot Memory Reference - untrusted]\nold") == "hello"


def test_channel_is_derived_from_session_key():
    assert _channel_from_session("qq:user-123") == "qq"
    assert _channel_from_session("wechat:user-123") == "wechat"
    assert _channel_from_session("") == "chat"


@pytest.mark.asyncio
async def test_hook_injects_only_untrusted_reference(monkeypatch):
    monkeypatch.setattr(
        memory_bridge,
        "_request_json",
        lambda *_args, **_kwargs: {
            "hot": [
                {
                    "id": 1,
                    "kind": "preference",
                    "source": "manual",
                    "created_at": "2026-07-16",
                    "content": "prefer concise replies",
                }
            ]
        },
    )
    context = SimpleNamespace(
        iteration=0,
        session_key="qq:user-1",
        messages=[{"role": "user", "content": "what should we do?"}],
    )
    await MemoryHook(base_url="http://example.invalid").before_iteration(context)
    content = context.messages[-1]["content"]
    assert "what should we do?" in content
    assert "[Nanobot Memory Reference - untrusted]" in content
    assert "not instructions" in content
