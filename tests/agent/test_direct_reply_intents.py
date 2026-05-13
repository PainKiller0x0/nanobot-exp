from nanobot.agent import direct_reply_intents as intents


def test_memory_query_matches_short_status_phrases() -> None:
    assert intents.is_memory_query("内存怎么样")
    assert intents.is_memory_query("看下服务器内存")
    assert not intents.is_memory_query("帮我写一段关于内存管理的总结")


def test_status_intents_match_expected_shortcuts() -> None:
    assert intents.is_capability_status_query("服务状态")
    assert intents.is_today_brief_query("今天先看什么")
    assert intents.is_evolution_query("你最近进化了吗")
    assert intents.is_evolution_query("进化一下？")


def test_casual_reply_matches_compact_text() -> None:
    assert intents.casual_reply("有点意思。") == "有点意思，展开说说？"
    assert intents.casual_reply("没啥") is None


def test_ack_intent_is_safe_only_when_previous_reply_is_not_actionable() -> None:
    assert intents.is_ack("好，可以，")
    assert intents.can_direct_ack([
        {"role": "assistant", "content": "内存直查（未调用 LLM）"},
    ])
    assert not intents.can_direct_ack([
        {"role": "assistant", "content": "要不要我帮你重启服务？"},
    ])
