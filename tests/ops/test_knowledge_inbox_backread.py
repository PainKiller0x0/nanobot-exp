import importlib.util
import sys
from pathlib import Path


def _load_inbox_module():
    path = Path(__file__).resolve().parents[2] / "ops/sources/knowledge-inbox/inbox.py"
    spec = importlib.util.spec_from_file_location("knowledge_inbox_script", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_clean_backread_markdown_removes_tracker_tail():
    inbox = _load_inbox_module()
    raw = (
        "body\n\n"
        "\u6587\u7ae0\u539f\u6587   \n"
        "<img alt=\"\" width=\"1px\" height=\"1px\" "
        "style=\"width:1px;height:1px;display:none\" "
        "src=\"http://www.jintiankansha.me/rss_static/126821/OxU8zD34PW\">"
    )

    cleaned = inbox.clean_backread_markdown(raw, "title")

    assert "body" in cleaned
    assert "<img" not in cleaned
    assert "rss_static" not in cleaned
    assert "\u6587\u7ae0\u539f\u6587" not in cleaned


def test_render_backread_full_omits_heuristic_summary():
    inbox = _load_inbox_module()

    def fake_resolve(ref, *, days=7, limit=80):
        return (
            {
                "kind": "rss",
                "id": 1,
                "ref": "rss:1",
                "title": "Example",
                "source": "\u8bb0\u5fc6\u627f\u8f7d3",
                "time": "2026-05-19 12:00",
                "url": "https://example.com/a",
            },
            [],
            None,
        )

    def fake_article(entry_id):
        return {
            "item": {
                "title": "Example",
                "subscription_name": "\u8bb0\u5fc6\u627f\u8f7d3",
                "published_at_local": "2026-05-19 12:00",
                "link": "https://example.com/a",
            },
            "markdown": "\u7b2c\u4e00\u6bb5\u6b63\u6587\u3002\n\n\u7b2c\u4e8c\u6bb5\u6b63\u6587\u3002",
        }

    inbox.resolve_backread_target = fake_resolve
    inbox.rss_article = fake_article

    rendered = inbox.render_backread("1", chars=0)

    assert "\n\u6458\u8981\uff1a" not in rendered
    assert "\n\u6b63\u6587\uff1a" in rendered
    assert "\u7b2c\u4e00\u6bb5\u6b63\u6587" in rendered
