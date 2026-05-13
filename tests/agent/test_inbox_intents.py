from nanobot.agent.inbox_intents import extract_inbox_intent, extract_url


def test_extract_url_strips_trailing_punctuation() -> None:
    assert extract_url("看这个 https://example.com/a。") == "https://example.com/a"
    assert extract_url("no url") is None


def test_bare_url_becomes_capture_intent() -> None:
    assert extract_inbox_intent("https://example.com/a") == {
        "action": "capture",
        "url": "https://example.com/a",
    }


def test_capture_prefix_becomes_capture_intent() -> None:
    assert extract_inbox_intent("收一下 https://example.com/a") == {
        "action": "capture",
        "url": "https://example.com/a",
    }


def test_decide_marker_preserves_question() -> None:
    text = "这个值得看吗 https://example.com/a"

    assert extract_inbox_intent(text) == {
        "action": "decide",
        "url": "https://example.com/a",
        "question": text,
    }


def test_list_and_brief_queries_need_no_url() -> None:
    assert extract_inbox_intent("知识收件箱") == {"action": "list"}
    assert extract_inbox_intent("收件箱简报") == {"action": "brief"}


def test_unrelated_message_falls_through() -> None:
    assert extract_inbox_intent("帮我写一段总结") is None
    assert extract_inbox_intent("你看看这个") is None
