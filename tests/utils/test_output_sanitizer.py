from __future__ import annotations

from nanobot.utils.output_sanitizer import strip_meta_instruction_tail


def test_strip_exact_meta_instruction_tail() -> None:
    text = "Have fun today!\nLet's stick with rule 1 and no options/follow-up question elements."
    assert strip_meta_instruction_tail(text) == "Have fun today!"


def test_strip_no_options_follow_up_tail_only_at_end() -> None:
    text = "Have fun today! no options/follow-up question elements."
    assert strip_meta_instruction_tail(text) == "Have fun today!"


def test_keep_normal_english_content() -> None:
    text = "Let's stick with rule 1 in this board game and discuss follow-up questions tomorrow."
    assert strip_meta_instruction_tail(text) == text


def test_keep_signed_raw_payload_untouched() -> None:
    text = "NBRAW1-SHA256:" + "a" * 64 + "\n\nbody\nLet's stick with rule 1 and no options/follow-up question elements."
    assert strip_meta_instruction_tail(text) == text
