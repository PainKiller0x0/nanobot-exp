from nanobot.exp.agent.tool_budget import tool_definitions_for_turn

HA_TOOLS = [
    {
        "type": "function",
        "function": {"name": f"mcp_home_assistant_{name}"},
    }
    for name in (
        "homeassistant__GetLiveContext",
        "intent__HassTurnOn",
        "intent__HassTurnOff",
        "light__HassLightSet",
        "climate__HassClimateSetTemperature",
    )
]
OTHER_TOOLS = [
    {"type": "function", "function": {"name": "read_file"}},
    {"type": "function", "function": {"name": "generate_image"}},
]


def _select(text: str) -> tuple[list[dict] | None, str]:
    return tool_definitions_for_turn(
        [*OTHER_TOOLS, *HA_TOOLS],
        [{"role": "user", "content": text}],
    )


def test_ba_device_open_command_advertises_only_home_assistant_tools() -> None:
    tools, reason = _select("把深圳泊寓的米家显示器挂灯2打开")

    assert tools == HA_TOOLS
    assert reason == "home assistant control"


def test_verb_first_device_command_advertises_only_home_assistant_tools() -> None:
    tools, reason = _select("打开米家显示器挂灯2")

    assert tools == HA_TOOLS
    assert reason == "home assistant control"


def test_explicit_home_assistant_close_command_advertises_only_ha_tools() -> None:
    tools, reason = _select(
        "请通过 Home Assistant 关闭“深圳泊寓”的“米家显示器挂灯2”，"
        "打开后确认状态并告诉我结果。"
    )

    assert tools == HA_TOOLS
    assert reason == "home assistant control"


def test_explicit_climate_temperature_command_advertises_ha_tools() -> None:
    tools, reason = _select("\u8bf7\u628a\u6df1\u5733\u6cca\u5bd3\u7684\u7a7a\u8c03\u6e29\u5ea6\u8bbe\u4e3a26\u5ea6")

    assert tools == HA_TOOLS
    assert reason == "home assistant climate temperature"


def test_climate_temperature_in_past_conversation_does_not_advertise_tools() -> None:
    tools, reason = _select("\u6211\u4e4b\u524d\u628a\u7a7a\u8c03\u6e29\u5ea6\u8c03\u523026\u5ea6\u4f46\u8fd8\u662f\u51b7")

    assert tools is None
    assert reason == "contextual chat turn"


def test_casual_lamp_discussion_still_omits_tools() -> None:
    tools, reason = _select("我在考虑买一个米家显示器挂灯2")

    assert tools is None
    assert reason == "short standalone turn"


def test_non_command_lamp_statement_still_omits_tools() -> None:
    tools, _ = _select("挂灯刚才好像开了，但我没看到亮")

    assert tools is None


def test_opening_a_webpage_does_not_advertise_home_assistant_tools() -> None:
    tools, reason = _select("打开网页，我想看看这个挂灯长什么样")

    assert tools == [OTHER_TOOLS[0]]
    assert reason == "tool marker"
