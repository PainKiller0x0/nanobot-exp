from pathlib import Path
from types import SimpleNamespace

from nanobot.agent import warmup
from nanobot.agent.warmup import select_warmup_sessions, split_session_key


def test_make_loop_uses_provider_factory_snapshot(monkeypatch) -> None:
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

    def fake_from_config(config, bus=None, **kwargs):
        captured["config"] = config
        captured["bus"] = bus
        captured["kwargs"] = kwargs
        return "loop"

    monkeypatch.setattr(warmup.AgentLoop, "from_config", staticmethod(fake_from_config))
    config = SimpleNamespace(workspace_path=Path("/tmp/nanobot-warmup-test"))

    assert warmup.make_loop(config) == "loop"
    assert captured["config"] is config
    assert captured["kwargs"]["provider"] is provider
    assert captured["kwargs"]["model"] == "resolved-model"
    assert captured["kwargs"]["context_window_tokens"] == 12345
    assert captured["kwargs"]["provider_signature"] == ("sig",)


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
