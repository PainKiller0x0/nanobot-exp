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
    assert (
        _strip_reference("hello\n\n[Nanobot Personal Archive Reference - untrusted]\nprivate")
        == "hello"
    )


def test_recent_archive_query_selects_only_relevant_files():
    assert memory_bridge._archive_files_for_query(
        "阅读261014人生存档点，了解下我的近况吧"
    ) == (
        "给未来ChatGPT助手的近况与支持指南.md",
        "与我的沟通注意事项.md",
    )


def test_full_archive_request_selects_all_six_files():
    files = memory_bridge._archive_files_for_query("请完整阅读261014人生档案的六个文件")

    assert len(files) == 6


def test_full_archive_followup_uses_recent_archive_context_only():
    followup = "你把全文都先阅读完"
    assert memory_bridge._archive_files_for_query(followup) == ()
    assert (
        memory_bridge._archive_files_for_query(followup, archive_context=True)
        == memory_bridge._ARCHIVE_FILES
    )


def test_technical_request_does_not_select_personal_archive():
    assert memory_bridge._archive_files_for_query("帮我查一下服务日志") == ()


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


@pytest.mark.asyncio
async def test_hook_injects_relevant_archive_before_model_call(monkeypatch, tmp_path):
    guide = "给未来ChatGPT助手的近况与支持指南.md"
    communication = "与我的沟通注意事项.md"
    unrelated = "BB关系详细时间线.md"
    (tmp_path / guide).write_text("RECENT_CONTEXT_FIXTURE", encoding="utf-8")
    (tmp_path / communication).write_text("COMMUNICATION_FIXTURE", encoding="utf-8")
    (tmp_path / unrelated).write_text("UNRELATED_RELATION_FIXTURE", encoding="utf-8")
    monkeypatch.setattr(memory_bridge, "_PERSONAL_ARCHIVE_ROOT", tmp_path)
    monkeypatch.setattr(memory_bridge, "_request_json", lambda *_args, **_kwargs: None)
    question = "阅读261014人生存档点，了解下我的近况吧"
    context = SimpleNamespace(
        iteration=0,
        session_key="qq:user-archive",
        messages=[{"role": "user", "content": question}],
    )

    await MemoryHook(base_url="http://example.invalid").before_iteration(context)

    content = context.messages[0]["content"]
    assert question in content
    assert "RECENT_CONTEXT_FIXTURE" in content
    assert "COMMUNICATION_FIXTURE" in content
    assert "UNRELATED_RELATION_FIXTURE" not in content
    assert "[Nanobot Personal Archive Reference - untrusted]" in content


@pytest.mark.asyncio
async def test_full_archive_followup_injects_all_files(monkeypatch, tmp_path):
    for index, filename in enumerate(memory_bridge._ARCHIVE_FILES):
        (tmp_path / filename).write_text(f"ARCHIVE_FIXTURE_{index}", encoding="utf-8")
    monkeypatch.setattr(memory_bridge, "_PERSONAL_ARCHIVE_ROOT", tmp_path)
    monkeypatch.setattr(memory_bridge, "_request_json", lambda *_args, **_kwargs: None)
    latest_request = "你把全文都先阅读完，读完再跟我聊"
    context = SimpleNamespace(
        iteration=0,
        session_key="qq:user-full-archive",
        messages=[
            {"role": "user", "content": "请读取261014人生存档点"},
            {"role": "assistant", "content": "好，我来读"},
            {"role": "user", "content": latest_request},
        ],
    )

    await MemoryHook(base_url="http://example.invalid").before_iteration(context)

    content = context.messages[-1]["content"]
    assert all(f"ARCHIVE_FIXTURE_{index}" in content for index in range(6))
    assert content.count("## ") == 6
