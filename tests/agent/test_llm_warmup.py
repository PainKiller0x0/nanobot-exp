import asyncio
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from nanobot.agent import warmup
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.warmup import select_warmup_sessions, split_session_key


def test_make_loop_uses_provider_snapshot_and_v04_tool_registry(monkeypatch) -> None:
    provider = object()
    snapshot = SimpleNamespace(
        provider=provider,
        model="resolved-model",
        context_window_tokens=12345,
        signature=("sig",),
    )
    captured = {}

    monkeypatch.setattr(
        "nanobot.providers.factory.build_provider_snapshot",
        lambda config: snapshot,
    )
    monkeypatch.setattr(
        "nanobot.providers.factory.load_provider_snapshot",
        lambda *args, **kwargs: snapshot,
    )

    def fake_from_config(config, bus=None, *, tool_registry, **kwargs):
        captured["config"] = config
        captured["bus"] = bus
        captured["tool_registry"] = tool_registry
        captured["kwargs"] = kwargs
        return "loop"

    monkeypatch.setattr(warmup.AgentLoop, "from_config", staticmethod(fake_from_config))
    config = SimpleNamespace(workspace_path=Path("/tmp/nanobot-warmup-test"))

    assert warmup.make_loop(config) == "loop"
    assert captured["config"] is config
    assert isinstance(captured["tool_registry"], ToolRegistry)
    assert captured["kwargs"]["provider"] is provider
    assert captured["kwargs"]["model"] == "resolved-model"
    assert captured["kwargs"]["context_window_tokens"] == 12345
    assert captured["kwargs"]["provider_signature"] == ("sig",)
    assert "session_manager" not in captured["kwargs"]


def test_history_for_uses_v04_read_only_history_signature(monkeypatch) -> None:
    requested = {}
    history = [{"role": "user", "content": "previous"}]

    class SessionStub:
        def get_history(self, max_messages=0, *, max_tokens=0, **kwargs):
            requested.update(max_messages=max_messages, max_tokens=max_tokens, **kwargs)
            return history

    monkeypatch.setattr(warmup, "light_replay_max_messages", lambda default: 20)
    loop = SimpleNamespace(_replay_token_budget=lambda: 9000)

    assert warmup._history_for(loop, SessionStub()) == history
    assert requested == {"max_messages": 20, "max_tokens": 9000}


def test_warm_session_builds_v04_context_and_calls_provider_once() -> None:
    captured = {}
    updated_at = datetime(2026, 11, 2, 9, 0)

    class SessionStub:
        def __init__(self):
            self.key = "qq:room:thread"
            self.messages = [{"role": "user", "content": "hello"}]
            self.metadata = {
                "_last_summary": {
                    "text": "known context",
                    "last_active": updated_at.isoformat(),
                }
            }
            self.updated_at = updated_at

        def get_history(self, max_messages=0, *, max_tokens=0, **kwargs):
            captured["history_args"] = (max_messages, max_tokens, kwargs)
            return self.messages

    class ProviderStub:
        generation = SimpleNamespace(temperature=0.2, reasoning_effort="low")

        async def chat_with_retry(self, **kwargs):
            captured["provider_kwargs"] = kwargs
            return SimpleNamespace(
                usage={"input": 12},
                finish_reason="stop",
                content="OK",
            )

    class ContextStub:
        def build_messages(self, **kwargs):
            captured["context_kwargs"] = kwargs
            return [{"role": "user", "content": "warmup"}]

    class ToolsStub:
        def get_definitions(self):
            return []

    loop = SimpleNamespace(
        _replay_token_budget=lambda: 9000,
        context=ContextStub(),
        tools=ToolsStub(),
        model="resolved-model",
        provider_retry_mode="standard",
        provider=ProviderStub(),
    )

    result = asyncio.run(warmup.warm_session(
        loop,
        SessionStub(),
        timeout_s=3,
        max_tokens=4,
        prompt="ping",
    ))

    assert result["session"] == "qq:room:thread"
    assert result["content_preview"] == "OK"
    assert captured["context_kwargs"]["channel"] == "qq"
    assert captured["context_kwargs"]["current_message"] == "ping"
    assert captured["context_kwargs"]["session_summary"]["text"] == "known context"
    assert "chat_id" not in captured["context_kwargs"]
    assert captured["provider_kwargs"]["max_tokens"] == 4
    assert captured["provider_kwargs"]["reasoning_effort"] == "low"


def test_run_warmup_closes_loop_and_reads_existing_session(monkeypatch) -> None:
    session = SimpleNamespace(messages=[{"role": "user", "content": "hello"}])
    calls = {"closed": 0, "lookup": []}

    class SessionsStub:
        def list_sessions(self):
            return [{"key": "qq:room"}]

        def get_existing(self, key):
            calls["lookup"].append(key)
            return session

    class LoopStub:
        sessions = SessionsStub()

        async def aclose(self):
            calls["closed"] += 1

    monkeypatch.setattr("nanobot.cli.commands._load_runtime_config", lambda *_args: object())
    monkeypatch.setattr(warmup, "warm_tokenizer", lambda: None)

    @contextmanager
    def acquired(_path):
        yield True

    monkeypatch.setattr(warmup, "_single_process_lock", acquired)
    monkeypatch.setattr(warmup, "make_loop", lambda _config: LoopStub())

    async def fake_warm_session(*_args, **_kwargs):
        return {"session": "qq:room", "elapsed_ms": 1, "usage": {}, "finish_reason": "stop"}

    monkeypatch.setattr(warmup, "warm_session", fake_warm_session)
    args = SimpleNamespace(
        lock_file="/tmp/test.lock", quiet=True, config=None, workspace=None,
        session=None, limit=1, prefer=["qq:"], timeout=2, max_tokens=4, prompt="ping",
    )

    assert asyncio.run(warmup.run_warmup(args)) == 0
    assert calls == {"closed": 1, "lookup": ["qq:room"]}


def test_run_warmup_closes_loop_when_no_session_exists(monkeypatch) -> None:
    calls = {"closed": 0}

    class SessionsStub:
        def list_sessions(self):
            return []

    class LoopStub:
        sessions = SessionsStub()

        async def aclose(self):
            calls["closed"] += 1

    monkeypatch.setattr("nanobot.cli.commands._load_runtime_config", lambda *_args: object())
    monkeypatch.setattr(warmup, "warm_tokenizer", lambda: None)

    @contextmanager
    def acquired(_path):
        yield True

    monkeypatch.setattr(warmup, "_single_process_lock", acquired)
    monkeypatch.setattr(warmup, "make_loop", lambda _config: LoopStub())
    args = SimpleNamespace(
        lock_file="/tmp/test.lock", quiet=True, config=None, workspace=None,
        session=None, limit=1, prefer=["qq:"], timeout=2, max_tokens=4, prompt="ping",
    )

    assert asyncio.run(warmup.run_warmup(args)) == 0
    assert calls["closed"] == 1


def test_select_warmup_sessions_prefers_interactive_recent_sessions() -> None:
    infos = [
        {"key": "cron:abc", "updated_at": "2026-05-02T22:00:00"},
        {"key": "weixin:wx-user", "updated_at": "2026-05-02T21:59:00"},
        {"key": "qq:qq-user", "updated_at": "2026-05-02T21:58:00"},
        {"key": "cli:direct", "updated_at": "2026-05-02T21:57:00"},
    ]

    assert select_warmup_sessions(infos, limit=2) == ["qq:qq-user", "weixin:wx-user"]


def test_select_warmup_sessions_falls_back_to_other_human_sessions() -> None:
    infos = [
        {"key": "matrix:room", "updated_at": "2026-05-02T22:00:00"},
        {"key": "cron:abc", "updated_at": "2026-05-02T21:59:00"},
    ]

    assert select_warmup_sessions(infos, limit=1) == ["matrix:room"]


def test_split_session_key_keeps_colons_in_chat_id() -> None:
    assert split_session_key("slack:room:thread") == ("slack", "room:thread")
