from __future__ import annotations

from copy import deepcopy
from typing import Any

from nanobot.exp.agent import homeassistant_climate
from nanobot.exp.agent.homeassistant_climate import (
    API_BASE,
    ENTITY_ID,
    HomeAssistantClimateControlTool,
)


class FakeResponse:
    status_code = 200

    def __init__(self, payload: Any):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return deepcopy(self._payload)


class FakeClient:
    def __init__(self, *, ignore_post: bool = False):
        self.state = {
            "entity_id": ENTITY_ID,
            "state": "off",
            "attributes": {
                "friendly_name": "米家空调伴侣2 空调",
                "temperature": 20,
                "hvac_modes": ["auto", "cool", "dry", "heat", "fan_only", "off"],
                "fan_mode": "高",
                "fan_modes": ["自动", "低", "中", "高"],
                "swing_mode": "vertical",
                "swing_modes": ["off", "vertical"],
            },
        }
        self.ignore_post = ignore_post
        self.get_calls: list[tuple[str, dict[str, str]]] = []
        self.post_calls: list[tuple[str, dict[str, str], dict[str, Any]]] = []

    async def __aenter__(self) -> FakeClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def get(self, url: str, *, headers: dict[str, str]) -> FakeResponse:
        self.get_calls.append((url, headers))
        return FakeResponse(self.state)

    async def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any],
    ) -> FakeResponse:
        self.post_calls.append((url, headers, deepcopy(json)))
        if not self.ignore_post:
            field = next(key for key in ("hvac_mode", "fan_mode", "swing_mode") if key in json)
            value = json[field]
            self.state["attributes"][field] = value
            if field == "hvac_mode":
                self.state["state"] = value
        return FakeResponse([])


def _prepare(monkeypatch, tmp_path, *, ignore_post: bool = False) -> FakeClient:
    token_path = tmp_path / "token"
    token_path.write_text("not-a-real-token", encoding="utf-8")
    token_path.chmod(0o600)
    monkeypatch.setattr(homeassistant_climate, "TOKEN_PATH", token_path)
    monkeypatch.setattr(
        HomeAssistantClimateControlTool,
        "_read_token",
        staticmethod(lambda: "not-a-real-token"),
    )
    client = FakeClient(ignore_post=ignore_post)
    monkeypatch.setattr(
        homeassistant_climate.httpx,
        "AsyncClient",
        lambda **_kwargs: client,
    )
    return client


def test_schema_has_no_target_or_arbitrary_service_parameter() -> None:
    schema = HomeAssistantClimateControlTool().parameters

    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == {"action", "value"}
    assert "entity_id" not in schema["properties"]
    assert "service" not in schema["properties"]


async def test_read_state_returns_capabilities_without_mutating_device(monkeypatch, tmp_path) -> None:
    client = _prepare(monkeypatch, tmp_path)

    result = await HomeAssistantClimateControlTool().execute(action="read_state")

    assert not result.is_error
    assert "off" in result
    assert "fan_only" in result
    assert "自动" in result
    assert "vertical" in result
    assert client.get_calls[0][0] == f"{API_BASE}/api/states/{ENTITY_ID}"
    assert client.post_calls == []


async def test_hvac_mode_uses_fixed_entity_and_verifies_state(monkeypatch, tmp_path) -> None:
    client = _prepare(monkeypatch, tmp_path)

    result = await HomeAssistantClimateControlTool().execute(
        action="set_hvac_mode", value="制冷"
    )

    assert not result.is_error
    assert "已确认" in result
    assert client.post_calls[0][0].endswith("/api/services/climate/set_hvac_mode")
    assert client.post_calls[0][2] == {"entity_id": ENTITY_ID, "hvac_mode": "cool"}
    assert all(ENTITY_ID in call[0] for call in client.get_calls)


async def test_fan_and_swing_actions_map_to_only_allowlisted_services(monkeypatch, tmp_path) -> None:
    client = _prepare(monkeypatch, tmp_path)
    tool = HomeAssistantClimateControlTool()

    fan_result = await tool.execute(action="set_fan_mode", value="低风")
    swing_result = await tool.execute(action="set_swing_mode", value="关闭")

    assert not fan_result.is_error
    assert not swing_result.is_error
    assert [call[0].rsplit("/", 1)[-1] for call in client.post_calls] == [
        "set_fan_mode",
        "set_swing_mode",
    ]
    assert client.post_calls[0][2] == {"entity_id": ENTITY_ID, "fan_mode": "低"}
    assert client.post_calls[1][2] == {"entity_id": ENTITY_ID, "swing_mode": "off"}


async def test_unsupported_option_is_refused_without_service_call(monkeypatch, tmp_path) -> None:
    client = _prepare(monkeypatch, tmp_path)

    result = await HomeAssistantClimateControlTool().execute(
        action="set_swing_mode", value="左右扫风"
    )

    assert result.is_error
    assert "不支持" in result
    assert client.post_calls == []


async def test_failed_readback_is_never_reported_as_success(monkeypatch, tmp_path) -> None:
    client = _prepare(monkeypatch, tmp_path, ignore_post=True)

    result = await HomeAssistantClimateControlTool().execute(
        action="set_fan_mode", value="低"
    )

    assert result.is_error
    assert "未能确认" in result
    assert "已确认" not in result
    assert len(client.post_calls) == 1


def test_endpoint_allowlist_accepts_only_fixed_home_assistant_routes() -> None:
    tool = HomeAssistantClimateControlTool()
    tool._validate_endpoint(f"{API_BASE}/api/states/{ENTITY_ID}")
    tool._validate_endpoint(f"{API_BASE}/api/services/climate/set_swing_mode")

    for url in (
        "http://192.168.31.111/api/states/" + ENTITY_ID,
        f"{API_BASE}/api/services/light/turn_on",
        f"{API_BASE}/api/states/{ENTITY_ID}?redirect=https://example.com",
    ):
        try:
            tool._validate_endpoint(url)
        except ValueError as exc:
            assert "HA endpoint blocked" in str(exc)
        else:
            raise AssertionError(f"Unexpected endpoint accepted: {url}")
