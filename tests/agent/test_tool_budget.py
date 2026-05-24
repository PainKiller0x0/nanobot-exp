from nanobot.exp.agent.tool_budget import tool_definitions_for_turn

TOOLS = [{"type": "function", "function": {"name": "exec", "parameters": {}}}]


def test_short_standalone_chat_omits_tools() -> None:
    tools, reason = tool_definitions_for_turn(
        TOOLS,
        [{"role": "user", "content": "天气好热，咋办"}],
    )

    assert tools is None
    assert reason == "short standalone turn"


def test_explicit_tool_marker_keeps_tools() -> None:
    tools, reason = tool_definitions_for_turn(
        TOOLS,
        [{"role": "user", "content": "帮我查一下今天有什么新闻"}],
    )

    assert tools == TOOLS
    assert reason == "tool marker"


def test_contextual_turn_keeps_tools() -> None:
    tools, reason = tool_definitions_for_turn(
        TOOLS,
        [{"role": "user", "content": "继续改刚才那个报错"}],
    )

    assert tools == TOOLS
    assert reason == "tool marker"


def test_active_tool_context_keeps_tools() -> None:
    tools, reason = tool_definitions_for_turn(
        TOOLS,
        [
            {"role": "user", "content": "查一下"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "1"}]},
            {"role": "tool", "content": "result", "tool_call_id": "1"},
        ],
    )

    assert tools == TOOLS
    assert reason == "active tool context"



def test_old_tool_context_before_latest_user_does_not_force_tools() -> None:
    tools, reason = tool_definitions_for_turn(
        TOOLS,
        [
            {"role": "user", "content": "查一下天气"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "1"}]},
            {"role": "tool", "content": "result", "tool_call_id": "1"},
            {"role": "assistant", "content": "天气结果"},
            {"role": "user", "content": "现在就把其中一个房间的先关掉了"},
        ],
    )

    assert tools is None
    assert reason == "short standalone turn"
