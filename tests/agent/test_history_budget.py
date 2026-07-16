from nanobot.exp.agent.history_budget import (
    is_light_chat_reason,
    light_replay_max_messages,
    light_system_prompt_enabled,
    replay_budget_for_message,
    should_omit_tool_ads,
    should_skip_history_replay,
    should_use_compact_system_prompt,
)


def test_short_standalone_turn_uses_light_budget() -> None:
    budget, reason = replay_budget_for_message(
        "天气好热啊，怎么办？",
        default_budget=16_000,
        light_budget=3_000,
    )

    assert budget == 3_000
    assert reason == "short standalone turn"


def test_contextual_turn_keeps_full_budget() -> None:
    budget, reason = replay_budget_for_message(
        "你刚才说的那个方案继续改一下",
        default_budget=16_000,
        light_budget=3_000,
    )

    assert budget == 16_000
    assert reason.startswith("task marker:")


def test_task_turn_keeps_full_budget() -> None:
    budget, reason = replay_budget_for_message(
        "GitHub action 又报错了，帮我排查",
        default_budget=16_000,
        light_budget=3_000,
    )

    assert budget == 16_000
    assert reason.startswith("task marker:")


def test_work_venting_with_gai_does_not_force_full_budget() -> None:
    budget, reason = replay_budget_for_message(
        "我答应我老大了这周末改出来，甚至算是立了军令状了",
        default_budget=16_000,
        light_budget=3_000,
    )

    assert budget == 3_000
    assert reason == "short standalone turn"


def test_common_life_words_do_not_force_full_budget() -> None:
    examples = [
        "A\u548cB\u540e\u9762\u90fd\u662f\u6211\u7684\u5c0f\u4f19\u4f34\uff0c\u73b0\u5728\u8981\u4eceA\u548cB\u91cc\u9762\u9009\u4e00\u4e2a\u8c03\u8d70",
        "\u4eca\u665a\u5403\u5b8c\u5bb5\u591c\uff0c\u526f\u4e1a\u4e0d\u662f\u5f88\u60f3\u7ee7\u7eed\u5199\u6587\u6863\u4e86\u548b\u529e\uff1f\u70e6\u6b7b\u4e86",
        "\u4e0d\u5bf9\u4e0d\u5bf9\uff0c\u8fd9\u5468\u7684\u76ee\u6807\u53ea\u662f\u5b8c\u6210\u4e86\u4e00\u534a\u554a",
    ]
    for content in examples:
        budget, reason = replay_budget_for_message(
            content,
            default_budget=16_000,
            light_budget=3_000,
        )
        assert budget == 3_000
        assert reason == "short standalone turn"


def test_explicit_modify_command_keeps_full_budget() -> None:
    budget, reason = replay_budget_for_message(
        "帮我改一下配色",
        default_budget=16_000,
        light_budget=3_000,
    )

    assert budget == 16_000
    assert reason == "task marker: 改一下"


def test_url_turn_keeps_full_budget() -> None:
    budget, reason = replay_budget_for_message(
        "看看这个 https://example.com/a",
        default_budget=16_000,
        light_budget=3_000,
    )

    assert budget == 16_000
    assert reason == "url turn"


def test_status_tool_like_turn_keeps_full_budget() -> None:
    budget, reason = replay_budget_for_message(
        "内存怎么样",
        default_budget=16_000,
        light_budget=3_000,
    )

    assert budget == 16_000
    assert reason == "task marker: 内存"


def test_news_tool_like_turn_keeps_full_budget() -> None:
    budget, reason = replay_budget_for_message(
        "帮我看下今天新闻",
        default_budget=16_000,
        light_budget=3_000,
    )

    assert budget == 16_000
    assert reason == "task marker: 看下"


def test_light_system_prompt_feature_flag(monkeypatch) -> None:
    monkeypatch.delenv("NANOBOT_LIGHT_SYSTEM_PROMPT", raising=False)
    assert light_system_prompt_enabled() is True

    monkeypatch.setenv("NANOBOT_LIGHT_SYSTEM_PROMPT", "0")
    assert light_system_prompt_enabled() is False

    monkeypatch.setenv("NANOBOT_LIGHT_SYSTEM_PROMPT", "off")
    assert light_system_prompt_enabled() is False


def test_light_replay_max_messages_defaults_to_ten(monkeypatch) -> None:
    monkeypatch.delenv("NANOBOT_LIGHT_REPLAY_MESSAGES", raising=False)
    assert light_replay_max_messages(120) == 10


def test_light_replay_max_messages_is_configurable(monkeypatch) -> None:
    monkeypatch.setenv("NANOBOT_LIGHT_REPLAY_MESSAGES", "14")
    assert light_replay_max_messages(120) == 14
    assert light_replay_max_messages(8) == 8


def test_mentioning_daily_report_as_life_update_stays_light() -> None:
    budget, reason = replay_budget_for_message(
        "准备下班了，写一下日报就撤了",
        default_budget=16_000,
        light_budget=3_000,
    )

    assert budget == 3_000
    assert reason == "short standalone turn"


def test_explicit_daily_report_request_keeps_history() -> None:
    budget, reason = replay_budget_for_message(
        "帮我写一下今天的日报",
        default_budget=16_000,
        light_budget=3_000,
    )

    assert budget == 16_000
    assert reason == "task marker: 日报请求"


def test_short_referential_chat_keeps_small_history_without_tools() -> None:
    budget, reason = replay_budget_for_message(
        "\u989d\uff0c\u5979\u53d1\u7684\u8bdd\u9898\u4e0d\u662f\u7761\u7720\u7684\u8bdd\u9898\u5417\uff0c\u600e\u4e48\u8d8a\u626f\u8d8a\u8fdc\u4e86\u3002\u3002\u3002",
        default_budget=16_000,
        light_budget=1_200,
    )

    assert budget == 1_200
    assert reason == "short standalone turn"
    assert should_skip_history_replay(reason) is False
    assert should_use_compact_system_prompt(reason) is True
    assert should_omit_tool_ads(reason) is True
    assert is_light_chat_reason(reason) is True


def test_multiline_life_update_stays_on_light_chat_path() -> None:
    budget, reason = replay_budget_for_message(
        "\u65e9\u4e0a\u4f1a\u8bae\n\u4e2d\u5348\u8981\u4ea4\u4e1c\u897f\n\u4e0b\u73ed\u540e\u60f3\u4f11\u606f",
        default_budget=16_000,
        light_budget=1_200,
    )

    assert budget == 1_200
    assert reason == "structured chat turn"
    assert should_use_compact_system_prompt(reason) is True
    assert should_omit_tool_ads(reason) is True


def test_explicit_operational_request_keeps_full_budget() -> None:
    budget, reason = replay_budget_for_message(
        "\u5e2e\u6211\u68c0\u67e5\u670d\u52a1\u65e5\u5fd7",
        default_budget=16_000,
        light_budget=1_200,
    )

    assert budget == 16_000
    assert reason.startswith("task marker:")


def test_lightweight_reason_policy_helpers() -> None:
    assert should_skip_history_replay("short standalone turn") is False
    assert should_skip_history_replay("empty short turn") is True
    assert should_skip_history_replay("context marker: \u521a\u624d") is False
    assert should_use_compact_system_prompt("short standalone turn") is True
    assert should_use_compact_system_prompt("empty short turn") is True
    assert should_use_compact_system_prompt("context marker: \u521a\u624d") is False
    assert should_omit_tool_ads("short standalone turn") is True
    assert should_omit_tool_ads("task marker: \u65e5\u62a5\u8bf7\u6c42") is True
    assert should_omit_tool_ads("task marker: \u5185\u5b58") is False

def test_open_voice_reply_stays_on_light_chat_path() -> None:
    budget, reason = replay_budget_for_message(
        "打开语音回复",
        default_budget=16_000,
        light_budget=3_000,
    )

    assert budget == 3_000
    assert reason == "short standalone turn"
    assert should_omit_tool_ads(reason) is True
