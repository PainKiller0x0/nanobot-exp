from __future__ import annotations

from datetime import datetime

from nanobot.exp.qq.article_requests import (
    cn_num_to_int,
    extract_wechat_question,
    is_wechat_title_query,
    is_yage_request,
    parse_yage_selector,
)


def test_article_request_helpers() -> None:
    assert extract_wechat_question("微信公众号文章提到：Alpha 是什么") == "Alpha 是什么"
    assert extract_wechat_question("普通闲聊 微信 真不错") is None
    assert is_wechat_title_query("微信公众号最新文章")
    assert not is_wechat_title_query("微信这个产品不错")

    now = datetime(2026, 5, 13, 10, 0, 0)
    assert parse_yage_selector("发我鸭哥昨天的文章", now=now) == (None, "2026-05-12")
    assert parse_yage_selector("发我鸭哥 4/10 的要闻", now=now) == (None, "2026-04-10")
    assert parse_yage_selector("发我鸭哥第二新文章", now=now) == (2, None)
    assert parse_yage_selector("发我最新鸭哥文章", now=now) == (1, None)
    assert cn_num_to_int("十") == 10
    assert cn_num_to_int("十二") == 12

    assert is_yage_request("发我最新鸭哥文章")
    assert is_yage_request("鸭哥 4/10 那篇呢？")
    assert not is_yage_request("鸭哥这个名字挺有意思")
