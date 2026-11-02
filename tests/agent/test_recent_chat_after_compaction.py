"""Recent chat survives a summary checkpoint without changing durable history."""

import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.context import ContextBuilder
from nanobot.agent.autocompact import AutoCompact
from nanobot.agent.loop import AgentLoop, TurnKind
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMResponse
from nanobot.providers.openai_compat_provider import OpenAICompatProvider
from nanobot.session.manager import Session, SessionManager
from nanobot.utils.helpers import estimate_message_tokens


def _session(*, compact=True):
    session = Session(key="qq:offline-test")
    for index in range(16):
        session.add_message("user", f"user-{index}")
        session.add_message("assistant", f"answer-{index}")
    if compact:
        session.commit_summary_checkpoint("Existing summary", insert_at=len(session.messages))
    return session


async def _assemble(session, current, tmp_path, monkeypatch, *, tokens=10_000, subagent=False):
    monkeypatch.setenv("NANOBOT_LIGHT_REPLAY_MESSAGES", "20")
    monkeypatch.setenv("NANOBOT_LIGHT_REPLAY_TOKENS", str(tokens))
    before = deepcopy(session.messages), session.last_archived, deepcopy(session.metadata)
    ctx = SimpleNamespace(
        session=session, require_session=lambda: session, runtime=SimpleNamespace(),
        session_key=session.key, kind=TurnKind.SYSTEM if subagent else TurnKind.USER,
        on_runtime_admitted=None, ephemeral=False,
        commit_session=False,
        msg=SimpleNamespace(content=current, media=[], sender_id="subagent", metadata={}),
        delivery=SimpleNamespace(runtime_admitted=AsyncMock()),
        pending_summary=session.metadata.get("_last_summary"),
        runtime_context_blocks=[],
    )

    async def prepare_prompt(operation, *args, **kwargs):
        return operation(*args, **kwargs)

    loop = SimpleNamespace(
        runner=SimpleNamespace(prepare_prompt=prepare_prompt),
        _replay_token_budget=lambda runtime: 16_000,
        _request_context_for_turn=AsyncMock(return_value=None),
        _resolve_runtime_context_for_turn=AsyncMock(return_value=[]),
        _persist_user_message_early=lambda *args, **kwargs: False,
        _persist_subagent_followup=lambda *args, **kwargs: False,
        auto_compact=AutoCompact(
            SimpleNamespace(), None, session_lock=lambda _key: asyncio.Lock()
        ),
    )
    loop._build_transcript_input = lambda ctx: AgentLoop._build_transcript_input(loop, ctx)
    await AgentLoop._build_turn(loop, ctx)
    context = ContextBuilder(tmp_path)
    def system_prompt(**kwargs):
        summary = kwargs.get("session_summary")
        return "Offline system" + ("\n" + summary["text"] if summary else "")

    monkeypatch.setattr(context, "build_system_prompt", system_prompt)
    messages = context.build_transcript(ctx.transcript_input, channel="qq")
    provider = OpenAICompatProvider(api_key="offline-test", api_base="http://127.0.0.1:1/v1")
    kwargs = provider._build_kwargs(messages, None, "gemini-3.8-flash", 4096, 0.7, None, None)
    actual = deepcopy(kwargs["messages"][1:])
    expected = deepcopy([*ctx.history, {"role": "user", "content": messages[-1]["content"]}])
    for message in [*actual, *expected]:
        if message.get("tool_calls"):
            message["content"] = message.get("content") or None
            for call in message["tool_calls"]:
                call["function"]["arguments"] = json.loads(call["function"]["arguments"])
    merged = []
    for message in expected:
        if merged and message["role"] in {"user", "assistant"} and (
            merged[-1]["role"] == message["role"]
            and not message.get("tool_calls") and not merged[-1].get("tool_calls")
        ):
            merged[-1]["content"] = (merged[-1]["content"] + "\n\n" + message["content"]).strip()
        else:
            merged.append(message)
    assert actual == merged
    assert current in kwargs["messages"][-1]["content"]
    summary = session.metadata.get("_last_summary")
    if summary and not subagent:
        assert summary["text"] in kwargs["messages"][0]["content"]
    assert (session.messages, session.last_archived, session.metadata) == before
    return ctx.history


@pytest.mark.asyncio
@pytest.mark.parametrize("current", ["hello", "你刚才说的那件事呢？", "今天挺累的\n想歇会\n不用安排"])
async def test_compacted_light_chat_replays_recent_dialogue(current, tmp_path, monkeypatch):
    history = await _assemble(_session(), current, tmp_path, monkeypatch)
    assert history
    assert len(history) == 20
    assert history[-1] == {"role": "assistant", "content": "answer-15"}
    assert history[0]["role"] == "user"
    assert all("Existing summary" not in m["content"] for m in history)


@pytest.mark.asyncio
async def test_uncompacted_light_chat_is_unchanged(tmp_path, monkeypatch):
    session = _session(compact=False)
    expected = session.get_history(max_messages=20, max_tokens=10_000)
    assert await _assemble(session, "hello", tmp_path, monkeypatch) == expected


@pytest.mark.asyncio
async def test_task_path_keeps_archive_boundary(tmp_path, monkeypatch):
    assert await _assemble(_session(), "检查 /root/task.py", tmp_path, monkeypatch) == []


@pytest.mark.asyncio
async def test_clear_does_not_resurrect_old_messages(tmp_path, monkeypatch):
    session = _session()
    session.clear()
    assert await _assemble(session, "hello", tmp_path, monkeypatch) == []


@pytest.mark.asyncio
async def test_compacted_tail_keeps_token_budget(tmp_path, monkeypatch):
    session = _session(compact=False)
    for index in range(16):
        session.add_message("user", f"question-{index}: " + "text " * 25)
        session.add_message("assistant", f"response-{index}: " + "reply " * 25)
    session.commit_summary_checkpoint("Existing summary", insert_at=len(session.messages))
    history = await _assemble(session, "hello", tmp_path, monkeypatch, tokens=512)
    assert history
    assert sum(estimate_message_tokens(m) for m in history) <= 512
    assert len(history) < 20


@pytest.mark.asyncio
async def test_checkpoint_commands_are_not_replayed(tmp_path, monkeypatch):
    session = _session(compact=False)
    session.add_message("user", "private command", _command=True)
    session.add_message("assistant", "command output", _command=True)
    session.commit_summary_checkpoint("Existing summary", insert_at=len(session.messages))
    history = await _assemble(session, "hello", tmp_path, monkeypatch)
    assert history
    assert len(history) == 20
    assert not any("command" in m["content"] for m in history)


@pytest.mark.asyncio
async def test_summary_and_tail_survive_save_reload(tmp_path, monkeypatch):
    manager = SessionManager(tmp_path / "workspace", sessions_root=tmp_path / "sessions")
    session = _session()
    manager.save(session)
    manager.invalidate(session.key)
    loaded = manager.get_or_create(session.key)
    history = await _assemble(loaded, "hello", tmp_path, monkeypatch)
    assert len(history) == 20
    manager.save(loaded)
    manager.invalidate(loaded.key)
    reloaded = manager.get_or_create(loaded.key)
    assert reloaded.messages == loaded.messages
    assert reloaded.last_archived == loaded.last_archived
    assert reloaded.metadata["_last_summary"] == loaded.metadata["_last_summary"]


@pytest.mark.asyncio
@pytest.mark.parametrize("subagent", [False, True])
async def test_non_chat_partial_archive_remains_unchanged(subagent, tmp_path, monkeypatch):
    session = _session(compact=False)
    session.commit_summary_checkpoint("Existing summary", insert_at=12)
    expected = session.get_history(max_tokens=16_000, extend_to_user=subagent)
    history = await _assemble(session, "检查 /root/task.py", tmp_path, monkeypatch, subagent=subagent)
    assert history == expected and history


@pytest.mark.asyncio
async def test_archived_oversized_turn_does_not_defeat_budget(tmp_path, monkeypatch):
    session = Session(key="qq:offline-test")
    session.add_message("user", "large " * 2_000)
    session.add_message("assistant", "short answer")
    session.commit_summary_checkpoint("Existing summary", insert_at=len(session.messages))
    history = await _assemble(session, "hello", tmp_path, monkeypatch, tokens=512)
    assert sum(estimate_message_tokens(m) for m in history) <= 512


@pytest.mark.asyncio
@pytest.mark.parametrize("complete", [False, True])
async def test_archived_tools_stay_in_summary_not_live_protocol(complete, tmp_path, monkeypatch):
    session = _session(compact=False)
    session.add_message("user", "read previous document")
    session.add_message("assistant", "", tool_calls=[{
        "id": "old-call", "type": "function",
        "function": {"name": "read_file", "arguments": '{"path":"old.txt"}'},
    }])
    if complete:
        session.add_message("tool", "old tool output", tool_call_id="old-call")
        session.add_message("assistant", "Old final reply")
    session.commit_summary_checkpoint("Existing summary", insert_at=len(session.messages))
    history = await _assemble(session, "hello", tmp_path, monkeypatch)
    assert history
    assert all(m["role"] != "tool" and not m.get("tool_calls") for m in history)


@pytest.mark.asyncio
async def test_unarchived_tool_protocol_remains_intact(tmp_path, monkeypatch):
    session = _session()
    session.add_message("user", "later document")
    session.add_message("assistant", "", tool_calls=[{
        "id": "new-call", "type": "function",
        "function": {"name": "read_file", "arguments": '{"path":"new.txt"}'},
    }])
    session.add_message("tool", "new result", tool_call_id="new-call")
    session.add_message("assistant", "New final reply")
    history = await _assemble(session, "hello", tmp_path, monkeypatch)
    calls = {c["id"] for m in history for c in m.get("tool_calls", [])}
    results = {m["tool_call_id"] for m in history if m["role"] == "tool"}
    assert calls == results == {"new-call"}


@pytest.mark.asyncio
@pytest.mark.parametrize("multimodal", [False, True])
async def test_archived_attachments_and_private_metadata_are_not_replayed(multimodal, tmp_path, monkeypatch):
    session = _session(compact=False)
    content = [{"type": "text", "text": "never restore attachment"}] if multimodal else "Old caption"
    session.add_message("user", content, media=["/private/old-image.png"])
    session.add_message("assistant", "Old ordinary reply", thinking_blocks=[{"data": "private-reasoning"}])
    session.commit_summary_checkpoint("Existing summary", insert_at=len(session.messages))
    history = await _assemble(session, "hello", tmp_path, monkeypatch)
    assert history
    assert all(set(m) <= {"role", "content"} and isinstance(m["content"], str) for m in history)
    rendered = json.dumps(history)
    assert "never restore attachment" not in rendered
    assert "/private/old-image.png" not in rendered
    assert "private-reasoning" not in rendered


@pytest.mark.asyncio
@pytest.mark.parametrize("content", [
    "<｜｜DSML｜｜ calls>unfinished", " <||DSML||function_calls>unfinished",
    "<tool_call>unfinished", "[ToolCalls]unfinished",
])
async def test_archived_assistant_protocol_echo_is_not_dialogue(content, tmp_path, monkeypatch):
    session = _session(compact=False)
    session.add_message("assistant", content)
    session.commit_summary_checkpoint("Existing summary", insert_at=len(session.messages))
    history = await _assemble(session, "hello", tmp_path, monkeypatch)
    assert history and not any(m["content"].lstrip() == content.lstrip() for m in history)
    assert session.messages[-2]["content"] == content


@pytest.mark.asyncio
async def test_user_protocol_quote_is_not_removed(tmp_path, monkeypatch):
    session = _session(compact=False)
    quoted = "<｜｜DSML｜｜ calls>user bug report"
    session.add_message("user", quoted)
    session.add_message("assistant", "A normal explanation")
    session.commit_summary_checkpoint("Existing summary", insert_at=len(session.messages))
    history = await _assemble(session, "hello", tmp_path, monkeypatch)
    assert any(m["content"].endswith(quoted) for m in history)


@pytest.mark.asyncio
async def test_archived_user_time_is_source_time_not_current_time(tmp_path, monkeypatch):
    session = _session(compact=False)
    session.add_message("user", "Today felt tiring")
    session.messages[-1]["timestamp"] = "2026-10-14T08:00:00+08:00"
    session.add_message("assistant", "An ordinary reply")
    session.commit_summary_checkpoint("Existing summary", insert_at=len(session.messages))
    history = await _assemble(session, "hello", tmp_path, monkeypatch)
    assert history[-2]["content"] == "[Message Time: 2026-10-14T08:00:00+08:00]\nToday felt tiring"


@pytest.mark.asyncio
@pytest.mark.parametrize("timestamp", [None, "not-a-time"])
async def test_missing_archive_time_is_not_invented(timestamp, tmp_path, monkeypatch):
    session = _session(compact=False)
    session.add_message("user", "Old message")
    session.messages[-1]["timestamp"] = timestamp
    session.add_message("assistant", "Old reply")
    session.commit_summary_checkpoint("Existing summary", insert_at=len(session.messages))
    history = await _assemble(session, "hello", tmp_path, monkeypatch)
    assert history[-2]["content"] == "Old message"


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol_echo", [False, True])
async def test_real_turn_appends_only_new_messages(protocol_echo, tmp_path, monkeypatch):
    monkeypatch.setenv("NANOBOT_LIGHT_REPLAY_MESSAGES", "20")
    monkeypatch.setenv("NANOBOT_LIGHT_REPLAY_TOKENS", "10000")
    workspace = tmp_path / "workspace"
    manager = SessionManager(workspace, sessions_root=tmp_path / "sessions")
    session = manager.get_or_create("cli:recent-chat")
    for index in range(16):
        session.add_message("user", f"user-{index}")
        session.add_message("assistant", f"answer-{index}")
    if protocol_echo:
        session.add_message("user", "Earlier request")
        session.add_message("assistant", "<｜｜DSML｜｜ calls>old echo")
        session.add_message("user", "Another earlier request")
        session.add_message("assistant", "Another old reply")
    session.commit_summary_checkpoint("Existing summary", insert_at=len(session.messages))
    before = deepcopy(session.messages)
    archived = session.last_archived
    manager.save(session)
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation.max_tokens = 4096
    provider.chat_stream_with_retry = AsyncMock(return_value=LLMResponse(content="Offline reply"))
    loop = AgentLoop(bus=MessageBus(), provider=provider, workspace=workspace,
                     model="test-model", context_window_tokens=32_768, session_manager=manager)
    result = await loop._process_message(InboundMessage(
        channel="cli", sender_id="test-user", chat_id="recent-chat", content="继续聊前面的事情",
    ))
    session = manager.get_or_create("cli:recent-chat")
    assert result and result.content == "Offline reply"
    sent = provider.chat_stream_with_retry.await_args.kwargs["messages"]
    assert any("answer-15" in str(m.get("content")) for m in sent)
    assert session.messages[:len(before)] == before
    assert len(session.messages) == len(before) + 2
    assert session.last_archived == archived
