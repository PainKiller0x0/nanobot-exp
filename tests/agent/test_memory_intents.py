from nanobot.agent import memory_intents


def test_extract_memory_to_save_matches_common_phrases() -> None:
    assert memory_intents.extract_memory_to_save("\u8bb0\u4f4f Rust sidecar") == "Rust sidecar"
    assert memory_intents.extract_memory_to_save("\u4ee5\u540e\u8981\u8bb0\u5f97\uff1a\u7f51\u9875\u5c3d\u91cf\u7eaf\u4e2d\u6587") == "\u7f51\u9875\u5c3d\u91cf\u7eaf\u4e2d\u6587"
    assert memory_intents.extract_memory_to_save("\u5e2e\u6211\u5199\u603b\u7ed3") is None


def test_extract_memory_search_matches_search_and_remember_question() -> None:
    assert memory_intents.extract_memory_search("\u67e5\u8bb0\u5fc6 Rust") == "Rust"
    assert memory_intents.extract_memory_search("\u4f60\u8fd8\u8bb0\u5f97\u7f51\u9875\u504f\u597d\u5417\uff1f") == "\u7f51\u9875\u504f\u597d"
    assert memory_intents.extract_memory_search("\u8bb0\u5fc6\u72b6\u6001") is None
    assert memory_intents.extract_memory_search("\u4f60\u8bb0\u5f97\u4ec0\u4e48\u5417") is None


def test_status_and_category_helpers() -> None:
    assert memory_intents.is_memory_status_query("\u672c\u5730\u8bb0\u5fc6\u72b6\u6001")
    assert not memory_intents.is_memory_status_query("\u67e5\u8bb0\u5fc6 Rust")
    assert memory_intents.guess_category("\u6211\u559c\u6b22 Rust") == "preference"
    assert memory_intents.guess_category("\u4eca\u5929\u90e8\u7f72\u5b8c\u6210") == "note"


def test_clean_content_compacts_whitespace_and_caps_length() -> None:
    assert memory_intents.clean_content("  a\n\t b  ") == "a b"
    assert len(memory_intents.clean_content("x" * 5000)) == 4000
