"""Offline contracts for the nanobot-exp v0.4.2 adaptation.

These checks stay inside the process: no channel login, no sidecar, and no
production config. Network calls are replaced before the code under test runs.
"""

from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.qq.runtime import QQChannel, QQConfig
from nanobot.channels.websocket.runtime import WebSocketChannel
from nanobot.channels.weixin.runtime import WeixinChannel, WeixinConfig
from nanobot.config.loader import load_config, save_config
from nanobot.config.schema import Config
from nanobot.exp.qq.signatures import verify_and_unwrap_signed_payload
from nanobot.exp.qq.streaming import should_stream_text, supports_streaming

ROOT = Path(__file__).resolve().parents[2]


def _synthetic_config() -> dict[str, object]:
    return {
        "agents": {
            "defaults": {
                "workspace": "/tmp/fakehome/workspace",
                "model": "synthetic-model",
                "provider": "custom",
                "maxTokens": 1024,
                "contextWindowTokens": 4096,
                "temperature": 0.1,
                "maxToolIterations": 1,
                "timezone": "UTC",
                "persona": "synthetic persona",
                "disabled_skills": ["synthetic-skill"],
            }
        },
        "providers": {
            "custom": {
                "apiKey": "synthetic-not-a-secret",
                "apiBase": "https://invalid.invalid/v1",
                "extraHeaders": {"X-OBP-Source": "synthetic"},
                "conversationTrial": True,
            }
        },
        "channels": {
            "qq": {
                "enabled": False,
                "app_id": "synthetic-app",
                "secret": "synthetic-not-a-secret",
                "msg_format": "markdown",
                "stream_enabled": True,
                "stream_chunk_chars": 180,
            },
            "weixin": {"enabled": False, "state_dir": "/tmp/fakehome/weixin"},
            "websocket": {
                "enabled": False,
                "host": "127.0.0.1",
                "port": 18791,
                "path": "/ws",
                "tokenIssueSecret": "synthetic-not-a-secret",
                "websocketRequiresToken": True,
            },
        },
        "gateway": {"host": "127.0.0.1", "port": 18790, "heartbeat": {"enabled": False}},
        "tools": {"mcpServers": {}},
        "api": {"host": "127.0.0.1", "port": 8900},
    }


def test_custom_fields_round_trip_and_retired_api_is_explicit(tmp_path: Path) -> None:
    raw = _synthetic_config()
    raw["agents"]["defaults"]["unifiedSession"] = True  # type: ignore[index]
    path = tmp_path / "config.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    loaded = load_config(path)
    assert loaded.agents.defaults.persona == "synthetic persona"
    assert loaded.providers.custom.conversation_trial is True
    assert not hasattr(loaded, "api") or "api" not in loaded.model_dump(by_alias=True)
    dumped = loaded.model_dump(mode="json", by_alias=True)
    assert "api" not in dumped
    assert "unifiedSession" not in dumped["agents"]["defaults"]
    assert dumped["agents"]["defaults"]["persona"] == "synthetic persona"
    assert dumped["providers"]["custom"]["conversationTrial"] is True
    assert dumped["channels"]["qq"]["stream_enabled"] is True
    assert dumped["channels"]["weixin"]["enabled"] is False
    assert dumped["channels"]["websocket"]["enabled"] is False

    save_config(loaded, path)
    again = json.loads(path.read_text(encoding="utf-8"))
    assert again["agents"]["defaults"]["persona"] == "synthetic persona"
    assert again["providers"]["custom"]["conversationTrial"] is True
    assert again["channels"]["qq"]["stream_chunk_chars"] == 180
    assert "api" not in again
    assert "unifiedSession" not in again["agents"]["defaults"]


def test_absent_custom_fields_are_not_invented(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({"agents": {"defaults": {"timezone": "UTC", "model": "synthetic-model"}}}),
        encoding="utf-8",
    )
    loaded = load_config(path)
    assert loaded.agents.defaults.persona is None
    assert loaded.providers.custom.conversation_trial is None
    save_config(loaded, path)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert "persona" not in saved["agents"]["defaults"]
    assert "conversationTrial" not in saved["providers"]["custom"]


def test_custom_field_type_errors_are_explicit() -> None:
    with pytest.raises(ValidationError):
        Config.model_validate({"agents": {"defaults": {"timezone": "UTC", "persona": 1}}})
    with pytest.raises(ValidationError):
        Config.model_validate({"providers": {"custom": {"conversationTrial": "yes"}}})


def test_source_import_provenance_and_gateway_launcher() -> None:
    import nanobot
    import nanobot.channels.qq.runtime as qq_runtime
    import nanobot.cli.docker_bootstrap as bootstrap

    assert nanobot.__version__ == "0.4.2"
    qq_path = Path(qq_runtime.__file__).resolve()
    assert qq_path == ROOT / "nanobot" / "channels" / "qq" / "runtime.py"
    assert Path(bootstrap.__file__).resolve().is_relative_to(ROOT / "nanobot")
    entry = (ROOT / "entrypoint.sh").read_text(encoding="utf-8")
    assert 'exec nanobot "$@"' in entry
    assert '[ "$1" = "gateway" ]' in entry
    assert '[ "$1" = "serve" ]' not in entry
    commands = (ROOT / "nanobot" / "cli" / "commands.py").read_text(encoding="utf-8")
    tree = ast.parse(commands)
    command_names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    }
    assert "_retired_serve" in command_names
    assert "serve" not in command_names
    assert 'name="gateway"' in commands


def test_qq_streaming_contract_without_transport() -> None:
    config = QQConfig(
        enabled=False,
        app_id="synthetic-app",
        secret="synthetic-not-a-secret",
        msg_format="markdown",
        stream_enabled=True,
        stream_requires_msg_id=True,
        stream_min_chars=1,
        stream_max_chars=5000,
    )
    assert supports_streaming(config) is True
    assert should_stream_text(
        config, msg_id="synthetic", is_signed_payload=False, content="hello",
    ) is True
    assert should_stream_text(
        config, msg_id=None, is_signed_payload=False, content="hello",
    ) is False
    assert should_stream_text(
        config, msg_id="synthetic", is_signed_payload=True, content="hello",
    ) is False
    channel = QQChannel(config, MessageBus())
    assert channel._running is False
    inspect.signature(channel.send).bind(
        OutboundMessage(channel="qq", chat_id="synthetic", content="offline")
    )


def test_weixin_and_websocket_construct_without_start() -> None:
    weixin = WeixinChannel(
        WeixinConfig(enabled=False, state_dir="/tmp/fakehome/weixin"),
        MessageBus(),
    )
    assert weixin._poll_task is None
    assert weixin._client is None
    gateway = MagicMock()
    gateway.session_manager = None
    gateway.endpoint.webui_connections = set()
    gateway.transcripts.sessions = None
    socket_channel = WebSocketChannel(
        {
            "enabled": False,
            "host": "127.0.0.1",
            "port": 18791,
            "path": "/ws",
            "tokenIssueSecret": "synthetic-not-a-secret",
        },
        MessageBus(),
        gateway=gateway,
    )
    assert socket_channel._server is None
    assert socket_channel._server_task is None
    required = inspect.signature(WebSocketChannel.__init__).parameters
    assert "gateway" in required and required["gateway"].kind is inspect.Parameter.KEYWORD_ONLY


def test_sidecar_verify_error_and_success_stay_local(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class _Denied:
        def __call__(self, request, timeout=0):
            calls.append(request.full_url)
            raise OSError("network denied")

    monkeypatch.setattr("nanobot.exp.qq.signatures.urllib.request.urlopen", _Denied())
    assert verify_and_unwrap_signed_payload("NBRAW1-SHA256:synthetic") is None
    assert calls == ["http://172.17.0.1:8092/verify"]

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"success": false, "error": "rejected"}'

    monkeypatch.setattr("nanobot.exp.qq.signatures.urllib.request.urlopen", lambda *a, **k: _Response())
    assert verify_and_unwrap_signed_payload("NBRAW1-SHA256:synthetic") is None

    class _Ok(_Response):
        def read(self):
            return b'{"success": true, "body": "synthetic body"}'

    monkeypatch.setattr("nanobot.exp.qq.signatures.urllib.request.urlopen", lambda *a, **k: _Ok())
    assert verify_and_unwrap_signed_payload("NBRAW1-SHA256:synthetic") == "synthetic body"


@pytest.mark.asyncio
async def test_qq_sidecar_download_failure_does_not_open_a_real_socket(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    channel = QQChannel(
        QQConfig(enabled=False, app_id="synthetic-app", secret="synthetic-not-a-secret"),
        MessageBus(),
    )
    channel._media_root = tmp_path

    class _Resp:
        def __init__(self, payload):
            self.payload = payload
            self.status = 503
            self.headers: dict[str, str] = {}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def json(self):
            return self.payload

    class _Http:
        def __init__(self):
            self.posts: list[str] = []
            self.gets: list[str] = []

        def post(self, url, json=None):
            self.posts.append(url)
            return _Resp({"success": False, "error": "sidecar down"})

        def get(self, url, **kwargs):
            self.gets.append(url)
            return _Resp(None)

    http = _Http()
    channel._http = http
    monkeypatch.setattr(
        "nanobot.channels.qq.runtime.validate_url_target",
        lambda url: (True, None),
    )
    saved = await channel._download_to_media_dir_chunked(
        "https://invalid.invalid/file.bin", filename_hint="note.txt",
    )
    assert saved is None
    assert http.posts == ["http://172.17.0.1:8092/download"]
    assert http.gets == ["https://invalid.invalid/file.bin"]
