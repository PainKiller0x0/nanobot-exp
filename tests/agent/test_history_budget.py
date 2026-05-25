from nanobot.exp.agent.history_budget import (
    light_system_prompt_enabled,
    replay_budget_for_message,
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
    assert reason.startswith("context marker:")


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

