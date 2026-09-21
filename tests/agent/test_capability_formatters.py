from nanobot.agent import capability_formatters


def test_format_capability_menu_groups_enabled_items() -> None:
    text = capability_formatters.format_capability_menu([
        {
            "id": "memory",
            "name": "\u8bb0\u5fc6",
            "category": "\u4e2a\u4eba",
            "enabled": True,
            "description": "\u672c\u5730\u8bb0\u5fc6\u67e5\u8be2",
            "trigger_phrases": ["\u8bb0\u5fc6\u72b6\u6001"],
        },
        {"id": "off", "enabled": False},
    ])

    assert "\u5df2\u767b\u8bb0\uff1a2 \u4e2a\uff1b\u5df2\u542f\u7528\uff1a1 \u4e2a" in text
    assert "\u3010\u4e2a\u4eba\u3011" in text
    assert "\u95ee\uff1a\u8bb0\u5fc6\u72b6\u6001" in text


def test_format_capability_status_lists_bad_items() -> None:
    text = capability_formatters.format_capability_status(
        {
            "summary": {"total": 2, "enabled": 2, "healthy": 1},
            "items": [{"name": "\u574f\u80fd\u529b", "ok": False}],
        },
        {
            "summary": {"total": 3, "healthy": 2},
            "items": [{"name": "\u574f\u670d\u52a1", "ok": False}],
        },
    )

    assert "\u80fd\u529b\uff1a1 / 2 \u53ef\u7528" in text
    assert "\u574f\u80fd\u529b" in text
    assert "\u574f\u670d\u52a1" in text


def test_format_evolution_brief_shows_recent_metric() -> None:
    text = capability_formatters.format_evolution_brief(
        {
            "summary": {"total": 1, "recent_7d": 1},
            "items": [
                {
                    "date": "2026-05-13",
                    "title": "QQ streaming",
                    "impact": "faster first output",
                    "metrics": [{"label": "latency", "after": "better"}],
                }
            ],
        }
    )

    assert "QQ streaming" in text
    assert "latency" in text


def test_format_today_brief_prioritizes_action_items() -> None:
    text = capability_formatters.format_today_brief(
        {
            "system": {"memory": {"used_mb": 400, "total_mb": 1966}},
            "sidecars": {"summary": {"healthy": 8, "total": 9}, "items": [{"name": "rss", "ok": False}]},
            "caps": {"summary": {"healthy": 12, "total": 13}},
            "notify": {"job_details": [{"name": "job-a", "status": {"last_status": "error"}}]},
            "articles": {"items": [{"title": "\u4eca\u5929\u6587\u7ae0"}]},
            "lof": {
                "last_board": {
                    "rows": [{"code": "161129", "name": "oil", "rt_premium_pct": 6.2}]
                }
            },
        }
    )

    assert "\u5185\u5b58 400 / 1966 MB" in text
    assert "\u670d\u52a1\u5f02\u5e38\uff1arss" in text
    assert "\u4efb\u52a1\u5f02\u5e38\uff1ajob-a" in text
    assert "161129" in text
    assert "\u4eca\u5929\u6587\u7ae0" in text
