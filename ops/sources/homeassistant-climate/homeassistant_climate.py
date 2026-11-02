from __future__ import annotations

import asyncio
import os
import stat
from pathlib import Path
from typing import Any

import httpx

from nanobot.agent.tools.base import Tool, ToolResult

API_BASE = "http://192.168.31.110"
ENTITY_ID = "climate.lumi_cn_917507975_mcn02"
TOKEN_PATH = Path("/root/.nanobot/secrets/homeassistant-token")

_ACTIONS = {
    "set_hvac_mode": ("hvac_mode", "hvac_modes", "set_hvac_mode"),
    "set_fan_mode": ("fan_mode", "fan_modes", "set_fan_mode"),
    "set_swing_mode": ("swing_mode", "swing_modes", "set_swing_mode"),
}
_VALUE_ALIASES = {
    "set_hvac_mode": {
        "自动": "auto", "auto": "auto",
        "制冷": "cool", "cool": "cool",
        "除湿": "dry", "抽湿": "dry", "dry": "dry",
        "制热": "heat", "heat": "heat",
        "送风": "fan_only", "仅送风": "fan_only", "fan_only": "fan_only",
        "关闭": "off", "关机": "off", "off": "off",
    },
    "set_fan_mode": {
        "自动": "自动", "低": "低", "低风": "低", "低速": "低", "低风速": "低",
        "中": "中", "中风": "中", "中速": "中", "中风速": "中",
        "高": "高", "高风": "高", "高速": "高", "高风速": "高",
    },
    "set_swing_mode": {
        "开": "vertical", "开启": "vertical", "打开": "vertical", "上下扫风": "vertical",
        "上下摆风": "vertical", "垂直扫风": "vertical", "vertical": "vertical",
        "关": "off", "关闭": "off", "停止": "off", "关闭扫风": "off", "off": "off",
    },
}
_MODE_LABELS = {
    "auto": "自动",
    "cool": "制冷",
    "dry": "除湿",
    "heat": "制热",
    "fan_only": "送风",
    "off": "关闭",
}


class HomeAssistantClimateControlTool(Tool):
    """Control only the configured Shenzhen climate entity and verify its state."""

    @property
    def name(self) -> str:
        return "home_assistant_shenzhen_climate_control"

    @property
    def description(self) -> str:
        return (
            "只查询或控制深圳泊寓客厅的固定空调。action 可用 read_state、set_hvac_mode、"
            "set_fan_mode、set_swing_mode。模式值：自动/制冷/除湿/制热/送风/关闭；"
            "风力：自动/低/中/高；扫风：上下扫风/关闭。设置后必须以工具回读结果为准。"
            "不接受实体、服务、温度、倒计时或其他设备参数。"
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["read_state", *_ACTIONS],
                    "description": "查询状态，或设置模式、风力、扫风。",
                },
                "value": {
                    "type": "string",
                    "description": "设置目标值；read_state 时省略。",
                },
            },
            "required": ["action"],
            "additionalProperties": False,
        }

    @property
    def exclusive(self) -> bool:
        return True

    async def execute(self, action: str, value: str | None = None) -> ToolResult:
        if action not in {"read_state", *_ACTIONS}:
            return ToolResult.error("不支持的空调操作；未发送请求。")
        if action == "read_state" and value not in (None, ""):
            return ToolResult.error("read_state 不接受设置值；未发送请求。")
        if action != "read_state" and (not isinstance(value, str) or not value.strip()):
            return ToolResult.error("设置操作缺少目标值；未发送请求。")

        try:
            token = self._read_token()
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(8.0, connect=3.0),
                follow_redirects=False,
                trust_env=False,
            ) as client:
                state = await self._read_state(client, token)
                if action == "read_state":
                    return ToolResult(self._format_state(state))

                field, options_field, service = _ACTIONS[action]
                requested = self._canonical_value(action, value or "")
                options = state["attributes"].get(options_field)
                if not isinstance(options, list) or requested not in options:
                    return ToolResult.error(
                        f"设备当前不支持该{self._action_label(action)}选项；未发送控制请求。"
                    )

                current = state.get("state") if action == "set_hvac_mode" else state["attributes"].get(field)
                if current == requested:
                    return ToolResult(self._verified_message(action, requested, state))

                service_url = f"{API_BASE}/api/services/climate/{service}"
                self._validate_endpoint(service_url)
                response = await client.post(
                    service_url,
                    headers=self._headers(token),
                    json={"entity_id": ENTITY_ID, field: requested},
                )
                response.raise_for_status()

                for attempt in range(5):
                    state = await self._read_state(client, token)
                    observed = (
                        state.get("state")
                        if action == "set_hvac_mode"
                        else state["attributes"].get(field)
                    )
                    if observed == requested:
                        return ToolResult(self._verified_message(action, requested, state))
                    if attempt < 4:
                        await asyncio.sleep(0.5)

                observed_text = observed if observed is not None else "未知"
                return ToolResult.error(
                    f"控制请求已发送，但 HA 回读为“{observed_text}”，未能确认"
                    f"{self._action_label(action)}已设为“{requested}”；不能报告成功。"
                )
        except httpx.HTTPStatusError as exc:
            return ToolResult.error(
                f"Home Assistant 返回 HTTP {exc.response.status_code}；控制未获确认。"
            )
        except (httpx.RequestError, OSError, ValueError, TypeError, KeyError) as exc:
            if isinstance(exc, ValueError) and str(exc).startswith("HA endpoint blocked:"):
                return ToolResult.error(str(exc))
            return ToolResult.error("Home Assistant 请求失败或响应无效；控制未获确认。")

    @staticmethod
    def _read_token() -> str:
        info = TOKEN_PATH.stat()
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077:
            raise ValueError("HA token file must be a private regular file")
        token = TOKEN_PATH.read_text(encoding="utf-8").strip()
        if not token:
            raise ValueError("HA token file is empty")
        return token

    @staticmethod
    def _headers(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    @staticmethod
    def _validate_endpoint(url: str) -> None:
        state_url = f"{API_BASE}/api/states/{ENTITY_ID}"
        service_urls = {
            f"{API_BASE}/api/services/climate/{service}"
            for _, _, service in _ACTIONS.values()
        }
        if url != state_url and url not in service_urls:
            raise ValueError("HA endpoint blocked: not in fixed endpoint allowlist")

    async def _read_state(self, client: httpx.AsyncClient, token: str) -> dict[str, Any]:
        url = f"{API_BASE}/api/states/{ENTITY_ID}"
        self._validate_endpoint(url)
        response = await client.get(url, headers=self._headers(token))
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("entity_id") != ENTITY_ID:
            raise ValueError("Unexpected Home Assistant entity response")
        attributes = payload.get("attributes")
        if not isinstance(attributes, dict):
            raise ValueError("Home Assistant entity attributes are unavailable")
        payload["attributes"] = attributes
        return payload

    @staticmethod
    def _canonical_value(action: str, value: str) -> str:
        stripped = value.strip()
        aliases = _VALUE_ALIASES[action]
        return aliases.get(stripped, aliases.get(stripped.lower(), stripped))

    @staticmethod
    def _action_label(action: str) -> str:
        return {
            "set_hvac_mode": "模式",
            "set_fan_mode": "风力",
            "set_swing_mode": "扫风",
        }[action]

    @staticmethod
    def _verified_message(action: str, value: str, state: dict[str, Any]) -> str:
        label = HomeAssistantClimateControlTool._action_label(action)
        shown = _MODE_LABELS.get(value, value) if action == "set_hvac_mode" else value
        if action == "set_hvac_mode":
            readback = f"状态={state.get('state', 'unknown')}"
        else:
            field = _ACTIONS[action][0]
            readback = f"{field}={state['attributes'].get(field, 'unknown')}，状态={state.get('state', 'unknown')}"
        return f"已确认深圳空调{label}为“{shown}”（HA 回读：{readback}）。"

    @staticmethod
    def _format_state(state: dict[str, Any]) -> str:
        attributes = state["attributes"]
        mode = state.get("state", "unknown")
        temperature = attributes.get("temperature")
        fan = attributes.get("fan_mode", "未知")
        swing = attributes.get("swing_mode", "未知")
        modes = attributes.get("hvac_modes", [])
        fans = attributes.get("fan_modes", [])
        swings = attributes.get("swing_modes", [])
        mode_text = _MODE_LABELS.get(mode, mode)
        temp_text = f"{temperature}°C" if temperature is not None else "未知"
        return (
            f"深圳泊寓客厅空调：状态/模式={mode_text}（{mode}），设定温度={temp_text}，"
            f"风力={fan}，扫风={swing}。可选模式={modes}；风力={fans}；扫风={swings}。"
        )


def token_file_is_private() -> bool:
    try:
        info = TOKEN_PATH.stat()
    except OSError:
        return False
    return (
        stat.S_ISREG(info.st_mode)
        and info.st_uid == 0
        and stat.S_IMODE(info.st_mode) & 0o077 == 0
        and os.access(TOKEN_PATH, os.R_OK)
    )
