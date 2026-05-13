from nanobot.exp.qq.fast_paths import match_personal_ops_command


def test_short_memory_query_uses_qq_ops_fast_path() -> None:
    assert match_personal_ops_command("内存怎么样") == "system"


def test_system_status_still_uses_qq_ops_fast_path() -> None:
    assert match_personal_ops_command("系统状态") == "system"


def test_cost_query_uses_personal_copilot_fast_path() -> None:
    assert match_personal_ops_command("成本怎么样") == "cost"


def test_night_summary_uses_personal_copilot_fast_path() -> None:
    assert match_personal_ops_command("睡前总结") == "night"


def test_link_decision_not_stolen_by_personal_ops_fast_path() -> None:
    assert match_personal_ops_command("这个值得看吗 https://example.com/a") is None
