from __future__ import annotations

import pytest

from nanobot.channels.qq.runtime import _is_obvious_error_reply, _unwrap_text_envelope


def test_unwraps_exact_text_envelope() -> None:
    content = "日常任务：\n\n1. 周报"
    wrapped = '{"status": "text", "content": "日常任务：\\n\\n1. 周报"}'

    assert _unwrap_text_envelope(wrapped) == content


@pytest.mark.parametrize(
    "text",
    [
        "普通回复",
        '{"status": "json", "content": "保留"}',
        '{"status": "text", "content": "保留", "extra": true}',
        '{"content": "保留"}',
        '{"status": "text", "content": 42}',
        '{"status": "text"',
    ],
)
def test_leaves_non_envelopes_unchanged(text: str) -> None:
    assert _unwrap_text_envelope(text) == text


@pytest.mark.parametrize(
    "text",
    [
        "Gemini request failed: timeout",
        " AI 调用失败：上游不可用",
        "I encountered an error doing what you asked.",
    ],
)
def test_detects_error_replies_for_tts_suppression(text: str) -> None:
    assert _is_obvious_error_reply(text)


def test_does_not_suppress_normal_reply_from_tts() -> None:
    assert not _is_obvious_error_reply("这件事我来帮你一起看看。")
