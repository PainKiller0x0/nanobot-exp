from nanobot.exp.qq.fast_paths import match_personal_ops_command


def test_short_memory_query_uses_qq_ops_fast_path() -> None:
    assert match_personal_ops_command("内存怎么样") == "system"


def test_system_status_still_uses_qq_ops_fast_path() -> None:
    assert match_personal_ops_command("系统状态") == "system"
