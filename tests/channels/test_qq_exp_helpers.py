from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from nanobot.exp.qq.fast_paths import match_knowledge_inbox_command, match_personal_ops_command
from nanobot.exp.qq.gateway_greeting import build_restart_greeting, greeting_for_hour
from nanobot.exp.qq.signatures import (
    extract_signed_digest,
    extract_wechat_ack_marker,
    should_ack_yage_url,
    strip_silent_marker,
)
from nanobot.exp.qq.streaming import (
    delta_flush_policy,
    should_stream_text,
    split_stream_chunks,
    supports_streaming,
)


def test_fast_path_memory_is_deterministic() -> None:
    assert match_personal_ops_command("内存怎么样") == "system"
    assert match_personal_ops_command("我想知道你能做什么") == "menu"
    assert match_personal_ops_command("帮助") == "menu"


def test_gateway_greeting_is_one_shot(tmp_path) -> None:
    flag = tmp_path / "restart.flag"
    flag.write_text("1", encoding="utf-8")

    assert greeting_for_hour(9) == "早安 ☀️"
    assert build_restart_greeting(now=datetime(2026, 5, 13, 21, 0), flag_path=flag) == "gateway 已上线 · 晚上好 🌙"
    assert not flag.exists()
    assert build_restart_greeting(now=datetime(2026, 5, 13, 21, 0), flag_path=flag) is None


def test_knowledge_inbox_does_not_steal_wechat_discussion() -> None:
    url = "https://mp.weixin.qq.com/s/abc"
    assert match_knowledge_inbox_command(f"这篇微信文章怎么看 {url}") is None
    assert match_knowledge_inbox_command(url) == ["capture", url]


def test_signature_helpers_strip_and_ack() -> None:
    assert strip_silent_marker("hello (NOOUTPUTKEEP_SILENT)") == "hello"
    body, ack = extract_wechat_ack_marker("正文\n<!-- NBACK_WECHAT sub:3 entry:99 -->")
    assert body == "正文"
    assert ack == (3, 99)
    assert extract_signed_digest("NBRAW1-SHA256:" + "a" * 64 + "\nbody") == "a" * 64
    assert should_ack_yage_url(
        "https://yage-ai.kit.com/posts/2026-05-01-x", "https://yage-ai.kit.com/posts/2026-05-02-y"
    )
    assert not should_ack_yage_url(
        "https://yage-ai.kit.com/posts/2026-05-02-y", "https://yage-ai.kit.com/posts/2026-05-01-x"
    )


def test_streaming_policy_and_chunking() -> None:
    cfg = SimpleNamespace(
        stream_enabled=True,
        msg_format="markdown",
        stream_requires_msg_id=True,
        stream_min_chars=5,
        stream_max_chars=20,
        stream_chunk_chars=6,
        stream_first_flush_chars=3,
        stream_delta_flush_chars=8,
        stream_delta_flush_interval_sec=0.2,
    )
    assert supports_streaming(cfg)
    assert should_stream_text(cfg, msg_id="m1", is_signed_payload=False, content="hello world")
    assert not should_stream_text(cfg, msg_id=None, is_signed_payload=False, content="hello world")
    assert delta_flush_policy(cfg, first_frame_sent=False) == (3, 0.2)
    assert delta_flush_policy(cfg, first_frame_sent=True) == (20, 0.2)
    assert split_stream_chunks(cfg, "a" * 45) == ["a" * 20 + "\n", "a" * 20 + "\n", "a" * 5 + "\n"]
