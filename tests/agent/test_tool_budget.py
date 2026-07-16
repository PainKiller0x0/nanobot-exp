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
    assert reason.startswith("task marker:")


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


def test_vague_look_word_does_not_advertise_tools() -> None:
    tools, reason = tool_definitions_for_turn(
        TOOLS,
        [{"role": "user", "content": "\u4f60\u770b\u6211\u662f\u4e0d\u662f\u53c8\u628a\u8bdd\u8bf4\u91cd\u4e86"}],
    )

    assert tools is None
    assert reason == "short standalone turn"


def test_explicit_operational_request_advertises_tools() -> None:
    tools, reason = tool_definitions_for_turn(
        TOOLS,
        [{"role": "user", "content": "\u5e2e\u6211\u68c0\u67e5\u4e00\u4e0b\u670d\u52a1\u65e5\u5fd7"}],
    )

    assert tools == TOOLS
    assert reason == "tool marker"


def test_direct_memory_status_question_advertises_tools() -> None:
    tools, reason = tool_definitions_for_turn(
        TOOLS,
        [{"role": "user", "content": "\u5185\u5b58\u600e\u4e48\u6837"}],
    )

    assert tools == TOOLS
    assert reason == "tool marker"

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


def test_common_life_words_omit_tools() -> None:
    content = (
        "\u4eca\u665a\u5403\u5b8c\u5bb5\u591c\uff0c"
        "\u526f\u4e1a\u4e0d\u662f\u5f88\u60f3\u7ee7\u7eed"
        "\u5199\u6587\u6863\u4e86\u548b\u529e\uff1f\u70e6\u6b7b\u4e86"
    )
    tools, reason = tool_definitions_for_turn(
        TOOLS,
        [{"role": "user", "content": content}],
    )

    assert tools is None
    assert reason == "short standalone turn"

def test_no_registered_tools_keeps_empty_tool_list_marker() -> None:
    tools, reason = tool_definitions_for_turn(
        [],
        [{"role": "user", "content": "do task"}],
    )

    assert tools == []
    assert reason == "no tools registered"
