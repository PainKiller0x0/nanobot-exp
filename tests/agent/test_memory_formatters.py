from nanobot.agent import memory_formatters


def test_format_memory_saved_success_and_failure() -> None:
    ok = memory_formatters.format_memory_saved("\u6211\u559c\u6b22 Rust", {"success": True, "id": 7})
    assert "\u8bb0\u4f4f\u4e86" in ok
    assert "#7" in ok

    bad = memory_formatters.format_memory_saved("x", {"success": False, "error": "down"})
    assert bad == "\u672c\u5730\u8bb0\u5fc6\u5199\u5165\u5931\u8d25\uff1adown"


def test_format_memory_status_includes_recent_items() -> None:
    text = memory_formatters.format_memory_status(
        {"total_memories": 2, "latest_memory_at": "2026-05-03", "total_interactions": 9, "total_facts": 0},
        [{"content": "\u7f51\u9875\u5c3d\u91cf\u7eaf\u4e2d\u6587", "category": "preference"}],
    )

    assert "\u672c\u5730\u8bb0\u5fc6\uff1a2 \u6761" in text
    assert "\u7f51\u9875\u5c3d\u91cf\u7eaf\u4e2d\u6587" in text


def test_format_memory_status_handles_empty_recent() -> None:
    text = memory_formatters.format_memory_status({}, [])

    assert "\u6700\u8fd1\u8bb0\u4f4f\uff1a\u6682\u65e0" in text


def test_format_memory_search_handles_results_and_empty() -> None:
    found = memory_formatters.format_memory_search(
        "Rust",
        [{"id": 3, "content": "\u4f18\u5148 Rust sidecar", "category": "preference", "created_at": "2026-05-03"}],
    )
    assert "#3 \u4f18\u5148 Rust sidecar" in found

    empty = memory_formatters.format_memory_search("Rust", [])
    assert "\u6ca1\u641c\u5230" in empty
