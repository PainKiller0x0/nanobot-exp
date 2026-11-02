"""Safety checks for Home Assistant MCP state-changing calls."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from mcp import types as mcp_types

from nanobot.agent.tools.mcp import MCPToolWrapper, _parse_home_assistant_context
from nanobot.agent.tools.registry import is_tool_error_result


LAMP_NAME = "米家显示器挂灯2  灯"
LAMP_AREA = "深圳泊寓 客厅"
AC_NAME = "\u7c73\u5bb6\u7a7a\u8c03\u4f34\u4fa3\u0032  \u7a7a\u8c03"
AC_AREA = LAMP_AREA


def _context(*entities: tuple[str, str, str]) -> str:
    blocks = ["Live Context: device snapshot"]
    for name, area, state in entities:
        blocks.append(f"- names: {name}\n  domain: light\n  state: '{state}'\n  areas: {area}")
    return "\n".join(blocks)


def _climate_context(state: str) -> str:
    return (
        "Live Context: device snapshot\n"
        f"- names: {AC_NAME}\n  domain: climate\n  state: '{state}'\n  areas: {AC_AREA}"
    )


def _result(text: str, *, is_error: bool = False):
    return SimpleNamespace(
        content=[mcp_types.TextContent(type="text", text=text)],
        isError=is_error,
    )


def _wrapper(session, name: str = "intent__HassTurnOn") -> MCPToolWrapper:
    tool_def = SimpleNamespace(
        name=name,
        description="Home Assistant control tool",
        inputSchema={"type": "object", "properties": {}},
    )
    return MCPToolWrapper(session, "home_assistant", tool_def)


def test_parse_home_assistant_context_extracts_state_and_normalizes_spaces():
    entities = _parse_home_assistant_context(_context((LAMP_NAME, LAMP_AREA, "off")))

    assert entities == [
        {
            "name": LAMP_NAME,
            "domain": "light",
            "state": "off",
            "area": LAMP_AREA,
        }
    ]


@pytest.mark.asyncio
async def test_turn_on_resolves_short_name_and_area_then_verifies_state():
    session = AsyncMock()
    session.call_tool = AsyncMock(
        side_effect=[
            _result(_context((LAMP_NAME, LAMP_AREA, "off"))),
            _result("Action accepted"),
            _result(_context((LAMP_NAME, LAMP_AREA, "on"))),
        ]
    )
    tool = _wrapper(session)

    result = await tool.execute(
        name="米家显示器挂灯2",
        area="深圳泊寓",
        domain=["light"],
    )

    assert "Verified Home Assistant state: on." in result
    calls = session.call_tool.await_args_list
    assert calls[0].args == ("homeassistant__GetLiveContext",)
    assert calls[0].kwargs["arguments"] == {"domain": ["light"]}
    assert calls[1].args == ("intent__HassTurnOn",)
    assert calls[1].kwargs["arguments"] == {
        "name": LAMP_NAME,
        "area": LAMP_AREA,
        "domain": ["light"],
    }
    assert calls[2].args == ("homeassistant__GetLiveContext",)
    assert calls[2].kwargs["arguments"] == {
        "name": LAMP_NAME,
        "area": LAMP_AREA,
        "domain": ["light"],
    }


@pytest.mark.asyncio
async def test_climate_turn_on_accepts_active_hvac_mode_as_on():
    session = AsyncMock()
    session.call_tool = AsyncMock(
        side_effect=[
            _result(_climate_context("off")),
            _result("Action accepted"),
            _result(_climate_context("cool")),
        ]
    )
    tool = _wrapper(session)

    result = await tool.execute(name=AC_NAME, area=AC_AREA, domain=["climate"])

    assert "Verified Home Assistant state: cool." in result


@pytest.mark.asyncio
async def test_climate_temperature_tool_resolves_target_without_domain_argument():
    session = AsyncMock()
    session.call_tool = AsyncMock(
        side_effect=[
            _result(_climate_context("off")),
            _result("Temperature command accepted"),
        ]
    )
    tool = _wrapper(session, name="climate__HassClimateSetTemperature")

    result = await tool.execute(name=AC_NAME, area=AC_AREA, temperature=26)

    assert result == "Temperature command accepted"
    assert session.call_tool.await_args_list[0].kwargs["arguments"] == {"domain": ["climate"]}
    assert session.call_tool.await_args_list[1].args == ("climate__HassClimateSetTemperature",)
    assert session.call_tool.await_args_list[1].kwargs["arguments"] == {
        "name": AC_NAME, "area": AC_AREA, "temperature": 26
    }


@pytest.mark.asyncio
async def test_climate_turn_on_does_not_accept_off_as_active():
    session = AsyncMock()
    session.call_tool = AsyncMock(
        side_effect=[
            _result(_climate_context("off")),
            _result("Action accepted"),
            _result(_climate_context("off")),
            _result(_climate_context("off")),
            _result(_climate_context("off")),
        ]
    )
    tool = _wrapper(session)

    with patch("nanobot.agent.tools.mcp.asyncio.sleep", new_callable=AsyncMock):
        result = await tool.execute(name=AC_NAME, area=AC_AREA, domain=["climate"])

    assert is_tool_error_result(result)
    assert "state read-back is off" in result


@pytest.mark.asyncio
async def test_turn_off_verifies_off_state():
    session = AsyncMock()
    session.call_tool = AsyncMock(
        side_effect=[
            _result(_context((LAMP_NAME, LAMP_AREA, "on"))),
            _result("Action accepted"),
            _result(_context((LAMP_NAME, LAMP_AREA, "off"))),
        ]
    )
    tool = _wrapper(session, name="intent__HassTurnOff")

    result = await tool.execute(name="米家显示器挂灯2", area="深圳泊寓")

    assert "Verified Home Assistant state: off." in result
    assert session.call_tool.await_args_list[1].args == ("intent__HassTurnOff",)


@pytest.mark.asyncio
async def test_turn_on_returns_error_when_readback_stays_off():
    session = AsyncMock()
    session.call_tool = AsyncMock(
        side_effect=[
            _result(_context((LAMP_NAME, LAMP_AREA, "off"))),
            _result("Action accepted"),
            _result(_context((LAMP_NAME, LAMP_AREA, "off"))),
            _result(_context((LAMP_NAME, LAMP_AREA, "off"))),
            _result(_context((LAMP_NAME, LAMP_AREA, "off"))),
        ]
    )
    tool = _wrapper(session)

    with patch("nanobot.agent.tools.mcp.asyncio.sleep", new_callable=AsyncMock):
        result = await tool.execute(name="米家显示器挂灯2", area="深圳泊寓")

    assert is_tool_error_result(result)
    assert "state read-back is off" in result
    assert session.call_tool.await_args_list[1].args == ("intent__HassTurnOn",)
    assert session.call_tool.await_count == 5


@pytest.mark.asyncio
async def test_ambiguous_target_is_rejected_before_control_call():
    session = AsyncMock()
    session.call_tool = AsyncMock(
        return_value=_result(
            _context(
                (LAMP_NAME, LAMP_AREA, "off"),
                ("米家显示器挂灯2 背光", LAMP_AREA, "off"),
            )
        )
    )
    tool = _wrapper(session)

    result = await tool.execute(
        name="米家显示器挂灯2",
        area="深圳泊寓",
        domain=["light"],
    )

    assert is_tool_error_result(result)
    assert "target is ambiguous" in result
    assert session.call_tool.await_count == 1
