import importlib.util
import re
import unittest
from pathlib import Path

_path = Path(__file__).resolve().parents[1] / "ops/sources/_shared/ops_common.py"
_spec = importlib.util.spec_from_file_location("article_ops_common", _path)
assert _spec and _spec.loader
ops = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ops)


class ArticlePushLinksTests(unittest.TestCase):
    def test_repeated_target_keeps_first_clickable_link_and_all_labels(self):
        text = "[第一段](https://example.com/ref)\n\n[第二段](https://example.com/ref)"
        self.assertEqual(
            ops.deduplicate_article_links(text),
            "[第一段](https://example.com/ref)\n\n第二段",
        )

    def test_different_targets_stay_clickable(self):
        text = "[甲](https://example.com/a) [乙](https://example.com/b)"
        self.assertEqual(ops.deduplicate_article_links(text), text)

    def test_formatter_preserves_full_text_metadata_and_original_link(self):
        url = "https://example.com/ref?ticket=" + "x" * 180
        paragraphs = [f"[这是第{i}段完整正文。]({url})" for i in range(30)]
        raw = "\n\n".join(paragraphs)
        article = {"title": "测试文章", "article_markdown": raw,
                   "subscription_name": "来源", "published_at_local": "2026-11-12 07:49:00",
                   "link": "https://example.com/original"}
        body = ops.format_article_push_body(article)
        self.assertEqual(body.count(url), 1)
        self.assertIn("[文章原文](https://example.com/original)", body)
        self.assertIn("2026-11-12 07:49:00", body)
        for i in range(30):
            self.assertIn(f"这是第{i}段完整正文。", body)
        def visible(value):
            return re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", value)
        self.assertIn(visible(raw), visible(body))
