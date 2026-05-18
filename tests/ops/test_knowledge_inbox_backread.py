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
