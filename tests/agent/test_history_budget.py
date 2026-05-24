from nanobot.exp.agent.history_budget import replay_budget_for_message


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


def test_url_turn_keeps_full_budget() -> None:
    budget, reason = replay_budget_for_message(
        "看看这个 https://example.com/a",
        default_budget=16_000,
        light_budget=3_000,
    )

    assert budget == 16_000
    assert reason == "url turn"
