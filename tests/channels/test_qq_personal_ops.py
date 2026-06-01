from nanobot.exp.qq.fast_paths import match_personal_ops_command


def test_short_memory_query_uses_qq_ops_fast_path() -> None:
    assert match_personal_ops_command("内存怎么样") == "system"
    assert match_personal_ops_command("帮我看看内存占用") == "system"


def test_system_status_still_uses_qq_ops_fast_path() -> None:
    assert match_personal_ops_command("系统状态") == "system"
    assert match_personal_ops_command("看下系统状态") == "system"
    assert match_personal_ops_command("帮我查服务健康") == "system"


def test_cost_query_uses_personal_copilot_fast_path() -> None:
    assert match_personal_ops_command("成本怎么样") == "cost"


def test_night_summary_uses_personal_copilot_fast_path() -> None:
    assert match_personal_ops_command("睡前总结") == "night"


def test_link_decision_not_stolen_by_personal_ops_fast_path() -> None:
    assert match_personal_ops_command("这个值得看吗 https://example.com/a") is None


def test_ops_fast_path_does_not_steal_normal_chat_mentions() -> None:
    normal_chat = [
        "你看我最近给他发的，他居然给我发系统状态了",
        "这个系统状态这个词我想发给你讨论一下",
        "我现在状态不太好，想聊聊",
        "你能不能帮助我分析一下这个合作问题",
        "我提到内存这个词，不代表我要查服务器",
        "为什么任务状态会影响我的心情",
        "这个服务状态让我很焦虑",
    ]
    for text in normal_chat:
        assert match_personal_ops_command(text) is None
