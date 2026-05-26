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


def test_current_user_hint_overrides_merged_history_text() -> None:
    tools, reason = tool_definitions_for_turn(
        TOOLS,
        [
            {
                "role": "user",
                "content": "这是一段很长的旧历史，里面有 GitHub、代码、日志、报错。" * 100
                + "\n\n现在很蛋疼，我不太想开工干副业。。。",
            }
        ],
        current_user_text="现在很蛋疼，我不太想开工干副业。。。",
    )

    assert tools is None
    assert reason == "short standalone turn"

def test_daily_report_life_update_omits_tools() -> None:
    tools, reason = tool_definitions_for_turn(
        TOOLS,
        [{"role": "user", "content": "准备下班了，写一下日报就撤了"}],
    )

    assert tools is None
    assert reason == "short standalone turn"


def test_daily_report_writing_request_still_omits_tools() -> None:
    tools, reason = tool_definitions_for_turn(
        TOOLS,
        [{"role": "user", "content": "帮我写一下今天的日报"}],
    )

    assert tools is None
    assert reason == "task marker: 日报请求"



def test_no_registered_tools_keeps_empty_tool_list_marker() -> None:
    tools, reason = tool_definitions_for_turn(
        [],
        [{"role": "user", "content": "do task"}],
    )

    assert tools == []
    assert reason == "no tools registered"
