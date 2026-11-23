"""Offline contracts for the nanobot-exp v0.4.2 adaptation.

These checks stay inside the process: no channel login, no sidecar, and no
production config. Network calls are replaced before the code under test runs.
"""

from __future__ import annotations

import ast
import inspect
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.qq.runtime import QQChannel, QQConfig
from nanobot.channels.websocket.runtime import WebSocketChannel
from nanobot.channels.weixin.runtime import WeixinChannel, WeixinConfig
from nanobot.config.errors import ConfigLoadError
from nanobot.config.loader import ConfigWriteError, dump_config, load_config, save_config
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


def test_custom_fields_and_legacy_keys_round_trip(tmp_path: Path) -> None:
    raw = _synthetic_config()
    defaults = raw["agents"]["defaults"]
    assert isinstance(defaults, dict)
    defaults["unifiedSession"] = True
    defaults["unified_session"] = False
    path = tmp_path / "config.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.warns(UserWarning, match="Retained legacy configuration"):
        loaded = load_config(path)
    assert loaded.agents.defaults.persona == "synthetic persona"
    assert loaded.providers.custom.conversation_trial is True
    # Direct model dump still omits keys the schema does not apply. That was
    # the pre-existing loss. save_config is what writes the retained copies back.
    dumped = loaded.model_dump(mode="json", by_alias=True)
    assert "api" not in dumped
    assert "unifiedSession" not in dumped["agents"]["defaults"]
    assert dumped["agents"]["defaults"]["persona"] == "synthetic persona"
    assert dumped["providers"]["custom"]["conversationTrial"] is True

    save_config(loaded, path)
    again = json.loads(path.read_text(encoding="utf-8"))
    assert again["agents"]["defaults"]["persona"] == "synthetic persona"
    assert again["providers"]["custom"]["conversationTrial"] is True
    assert again["channels"]["qq"]["stream_chunk_chars"] == 180
    assert again["api"] == raw["api"]
    assert again["agents"]["defaults"]["unifiedSession"] is True
    assert again["agents"]["defaults"]["unified_session"] is False


def test_save_rejects_dropping_legacy_keys(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    original = {
        "agents": {"defaults": {"timezone": "UTC", "unifiedSession": True}},
        "api": {"host": "127.0.0.1", "port": 8900, "note": "removed serve block"},
    }
    path.write_text(json.dumps(original), encoding="utf-8")
    before = path.read_text(encoding="utf-8")
    with pytest.raises(ConfigWriteError, match="agents.defaults.unifiedSession"):
        save_config(Config.model_validate({"agents": {"defaults": {"timezone": "UTC"}}}), path)
    assert path.read_text(encoding="utf-8") == before


def test_persona_is_stored_and_not_inserted_into_the_prompt(tmp_path: Path) -> None:
    """Bound source c4838b8 had no persona or conversationTrial field and no consumer.

    Storage keeps the values. Prompt assembly still does not read persona.
    """
    path = tmp_path / "config.json"
    path.write_text(json.dumps({
        "agents": {"defaults": {"timezone": "UTC", "persona": "SYNTHETIC_PERSONA_MARKER"}},
        "providers": {"custom": {"conversationTrial": False}},
    }), encoding="utf-8")
    loaded = load_config(path)
    assert loaded.agents.defaults.persona == "SYNTHETIC_PERSONA_MARKER"
    assert loaded.providers.custom.conversation_trial is False
    from nanobot.agent.context import ContextBuilder

    prompt = ContextBuilder(tmp_path).build_system_prompt()
    assert "SYNTHETIC_PERSONA_MARKER" not in prompt
    save_config(loaded, path)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["agents"]["defaults"]["persona"] == "SYNTHETIC_PERSONA_MARKER"
    assert saved["providers"]["custom"]["conversationTrial"] is False


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
            self.posts: list[tuple[str, object]] = []
            self.gets: list[str] = []

        def post(self, url, json=None):
            self.posts.append((url, json))
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
    assert http.posts[0][0] == "http://172.17.0.1:8092/download"
    body = http.posts[0][1]
    assert isinstance(body, dict)
    assert set(body) == {"url", "target_path", "max_bytes"}
    assert http.gets == ["https://invalid.invalid/file.bin"]


def test_sidecar_rust_contract_matches_python_client() -> None:
    """Static check of the QQ sidecar source. The binary is not started."""
    source = (ROOT / "ops/sources/qq-sidecar-rs/src/main.rs").read_text(encoding="utf-8")
    assert '.route("/download", post(download_handler))' in source
    assert '.route("/verify", post(verify_handler))' in source
    assert "struct DownloadReq" in source
    for field in ("url: String", "target_path: String", "max_bytes: usize"):
        assert field in source
    for field in ("success: bool", "body: Option<String>", "error: Option<String>"):
        assert field in source
    verify = (ROOT / "nanobot/exp/qq/signatures.py").read_text(encoding="utf-8")
    assert '"content": content' in verify
    assert "/verify" in verify


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_gateway_smoke_starts_and_stops_with_channels_disabled(tmp_path: Path) -> None:
    home = tmp_path / "home"
    workspace = tmp_path / "workspace"
    home.mkdir()
    workspace.mkdir()
    port = _free_port()
    config_path = home / "config.json"
    config_path.write_text(json.dumps({
        "agents": {"defaults": {
            "workspace": str(workspace),
            "model": "synthetic-model",
            "provider": "custom",
            "timezone": "UTC",
            "dream": {"enabled": False},
        }},
        "providers": {"custom": {
            "apiKey": "synthetic-not-a-secret",
            "apiBase": "https://invalid.invalid/v1",
        }},
        "channels": {
            "qq": {"enabled": False, "app_id": "synthetic-app", "secret": "synthetic-not-a-secret"},
            "weixin": {"enabled": False, "state_dir": str(tmp_path / "weixin")},
            "websocket": {"enabled": False, "host": "127.0.0.1", "port": port},
        },
        "gateway": {"host": "127.0.0.1", "port": port, "heartbeat": {"enabled": False}},
        "tools": {"mcpServers": {}},
    }), encoding="utf-8")
    env = {
        "HOME": str(home),
        "PATH": os.environ.get("PATH", ""),
        "NANOBOT_CONFIG": str(config_path),
        "NANOBOT_CHANNEL_ALLOWLIST": "disabled-channel",
        "PYTHONUNBUFFERED": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    if os.environ.get("PYTHONPATH"):
        env["PYTHONPATH"] = os.environ["PYTHONPATH"]
    script = (
        "import os; from pathlib import Path;"
        "from nanobot.config.loader import load_config, set_config_path;"
        "from nanobot.cli.gateway_runtime import _run_gateway;"
        "path = Path(os.environ['NANOBOT_CONFIG']); set_config_path(path);"
        "config = load_config(path);"
        "_run_gateway(config, port=config.gateway.port, webui_static_dist=False, "
        "webui_bundle_mode='skip')"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    deadline = time.monotonic() + 40
    health = ""
    try:
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                break
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2) as sock:
                    sock.sendall(b"GET /health HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n")
                    chunks = []
                    sock.settimeout(1)
                    while True:
                        try:
                            piece = sock.recv(4096)
                        except TimeoutError:
                            break
                        if not piece:
                            break
                        chunks.append(piece)
                    health = b"".join(chunks).decode("utf-8", errors="replace")
                    if "process" in health:
                        break
            except OSError:
                time.sleep(0.1)
        assert "\"ready\": true" in health or '"ready": true' in health, health
        proc.send_signal(signal.SIGTERM)
        try:
            output = proc.communicate(timeout=20)[0]
        except subprocess.TimeoutExpired:
            proc.kill()
            output = proc.communicate(timeout=5)[0]
            raise AssertionError(output[-2000:])
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate(timeout=5)
    assert proc.returncode == 0, output[-2000:]
    assert "Heartbeat: disabled" in output
    assert "Dream: disabled" in output


_PRODUCTION_FIELD_PATHS = (
    "tools.ssrf_whitelist",
    "tools.mcpServers.home_assistant.type",
    "tools.mcpServers.home_assistant.url",
    "tools.mcpServers.home_assistant.auth",
    "tools.mcpServers.home_assistant.toolTimeout",
    "tools.mcpServers.home_assistant.enabledTools",
    "tools.ssrfWhitelist",
    "agents.defaults.workspace",
    "agents.defaults.model",
    "agents.defaults.provider",
    "agents.defaults.maxTokens",
    "agents.defaults.contextWindowTokens",
    "agents.defaults.temperature",
    "agents.defaults.maxToolIterations",
    "agents.defaults.timezone",
    "agents.defaults.persona",
    "agents.defaults.disabled_skills",
    "providers.minimax.apiKey",
    "providers.minimax.apiBase",
    "providers.longcat.apiKey",
    "providers.longcat.apiBase",
    "providers.custom.apiKey",
    "providers.custom.apiBase",
    "providers.custom.extraHeaders.X-OBP-Source",
    "providers.custom.conversationTrial",
    "channels.qq.enabled",
    "channels.qq.app_id",
    "channels.qq.secret",
    "channels.qq.allow_from",
    "channels.qq.msg_format",
    "channels.qq.botpy_http_timeout_sec",
    "channels.qq.send_retry_on_empty_response",
    "channels.qq.send_retry_attempts",
    "channels.qq.send_retry_delay_sec",
    "channels.qq.stream_enabled",
    "channels.qq.stream_requires_msg_id",
    "channels.qq.stream_min_chars",
    "channels.qq.stream_max_chars",
    "channels.qq.stream_chunk_chars",
    "channels.qq.stream_interval_sec",
    "channels.qq.stream_first_flush_chars",
    "channels.qq.stream_delta_flush_chars",
    "channels.qq.stream_delta_flush_interval_sec",
    "channels.qq.stream_defer_first_frame_until_end",
    "channels.qq.send_progress",
    "channels.qq.send_tool_hints",
    "channels.qq.show_reasoning",
    "channels.weixin.enabled",
    "channels.weixin.allow_from",
    "channels.weixin.state_dir",
    "channels.websocket.enabled",
    "channels.websocket.host",
    "channels.websocket.port",
    "channels.websocket.path",
    "channels.websocket.tokenIssueSecret",
    "channels.websocket.websocketRequiresToken",
    "channels.websocket.allowFrom",
    "channels.websocket.streaming",
    "gateway.host",
    "gateway.port",
    "gateway.heartbeat.deliveryChannel",
    "gateway.heartbeat.deliveryChatId",
)


def _canon_path(path: str) -> str:
    return ".".join(part.replace("_", "").lower() for part in path.split("."))


def _synthetic_leaf(path: str) -> object:
    leaf = path.rsplit(".", 1)[-1].replace("_", "").lower()
    if leaf in {
        "enabled", "conversationtrial", "sendretryonemptyresponse", "streamenabled",
        "streamrequiresmsgid", "streamdeferfirstframeuntilend", "sendprogress",
        "sendtoolhints", "showreasoning", "websocketrequirestoken", "streaming",
    }:
        return False
    if leaf in {
        "port", "tooltimeout", "maxtokens", "contextwindowtokens", "maxtooliterations",
        "streamminchars", "streammaxchars", "streamchunkchars", "streamfirstflushchars",
        "streamdeltaflushchars", "sendretryattempts",
    }:
        return 1
    if leaf in {
        "temperature", "botpyhttptimeoutsec", "sendretrydelaysec", "streamintervalsec",
        "streamdeltaflushintervalsec",
    }:
        return 0.1
    if leaf in {"allowfrom", "disabledskills", "ssrfwhitelist", "enabledtools"}:
        return ["synthetic"]
    if leaf == "auth":
        return "oauth"
    if leaf == "msgformat":
        return "plain"
    if leaf == "type":
        return "streamableHttp"
    if leaf == "timezone":
        return "UTC"
    return "synthetic"


def _put_path(doc: dict[str, object], path: str, value: object) -> None:
    node = doc
    parts = path.split(".")
    for part in parts[:-1]:
        child = node.get(part)
        if not isinstance(child, dict):
            child = {}
            node[part] = child
        node = child
    node[parts[-1]] = value


def _leaves(value: object, path: str = "") -> set[str]:
    if isinstance(value, dict) and value:
        found: set[str] = set()
        for key, item in value.items():
            child = f"{path}.{key}" if path else key
            found.update(_leaves(item, child))
        return found
    return {path} if path else set()


def test_production_field_inventory_survives_load_and_save(tmp_path: Path) -> None:
    raw: dict[str, object] = {}
    for path in _PRODUCTION_FIELD_PATHS:
        _put_path(raw, path, _synthetic_leaf(path))
    _put_path(raw, "gateway.heartbeat.futureKnob", "keep-me")
    path = tmp_path / "config.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    loaded = load_config(path)
    assert loaded.gateway.heartbeat.delivery_channel == "synthetic"
    assert loaded.gateway.heartbeat.delivery_chat_id == "synthetic"
    saved_view = dump_config(loaded)
    assert saved_view["gateway"]["heartbeat"]["deliveryChannel"] == "synthetic"
    assert saved_view["gateway"]["heartbeat"]["futureKnob"] == "keep-me"
    assert "futureKnob" not in loaded.model_dump(mode="json", by_alias=True)["gateway"]["heartbeat"]
    save_config(loaded, path)
    again = json.loads(path.read_text(encoding="utf-8"))
    before = {_canon_path(item) for item in _leaves(raw)}
    after = {_canon_path(item) for item in _leaves(again)}
    assert before - after == set()


def test_alias_collision_is_rejected_and_equal_spellings_round_trip(tmp_path: Path) -> None:
    conflicted = tmp_path / "conflict.json"
    conflicted.write_text(json.dumps({
        "gateway": {"heartbeat": {"deliveryChannel": "qq", "delivery_channel": "weixin"}},
    }), encoding="utf-8")
    before = conflicted.read_bytes()
    with pytest.raises(ConfigLoadError, match="Conflicting aliases"):
        load_config(conflicted)
    assert conflicted.read_bytes() == before

    agreed = tmp_path / "agreed.json"
    agreed.write_text(json.dumps({
        "agents": {"defaults": {"timezone": "UTC"}},
        "gateway": {"heartbeat": {"delivery_channel": "qq", "deliveryChannel": "qq", "deliveryChatId": "chat"}},
    }), encoding="utf-8")
    loaded = load_config(agreed)
    assert loaded.gateway.heartbeat.delivery_channel == "qq"
    save_config(loaded, agreed)
    saved = json.loads(agreed.read_text(encoding="utf-8"))
    heartbeat = saved["gateway"]["heartbeat"]
    assert heartbeat["deliveryChannel"] == "qq"
    assert heartbeat["deliveryChatId"] == "chat"
    assert "delivery_channel" not in heartbeat


def test_save_rejects_unknown_nested_loss_before_writing(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    original = {"gateway": {"heartbeat": {"futureKnob": "keep-me", "enabled": False}}}
    path.write_text(json.dumps(original), encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(ConfigWriteError, match="futureKnob"):
        save_config(Config.model_validate({"gateway": {"heartbeat": {"enabled": False}}}), path)
    assert path.read_bytes() == before
