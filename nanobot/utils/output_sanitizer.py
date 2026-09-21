"""Small output guards for model-visible meta-instruction leaks."""

from __future__ import annotations

import re

_SIGNED_PREFIX = "NBRAW1-SHA256:"
_META_FLAGS = re.IGNORECASE | re.DOTALL | re.VERBOSE

_META_INSTRUCTION_TAIL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"""
        [\s\-\u2014]*
        (?:let['\u2019]?s\s+stick\s+with\s+rule\s+\d+\s+(?:and\s+)?)?
        no\s+options?
        \s*(?:/|,|\band\b|\bor\b|\s)\s*
        (?:no\s+)?follow[-\s]?up\s+question\s+elements?
        \.?
        \s*$
        """,
        _META_FLAGS,
    ),
    re.compile(
        r"""
        [\s\-\u2014]*
        let['\u2019]?s\s+stick\s+with\s+rule\s+\d+
        (?=[\s\S]{0,200}$)[\s\S]*?
        follow[-\s]?up\s+question\s+elements?
        \.?
        \s*$
        """,
        _META_FLAGS,
    ),
)


def strip_meta_instruction_tail(text: str) -> str:
    """Remove a narrow class of assistant prompt-leak tails.

    This intentionally only strips text anchored at the end and requiring the
    distinctive rule/follow-up wording that models sometimes leak from internal
    style instructions. Signed raw payloads are left untouched.
    """
    if not text:
        return text
    if text.lstrip().startswith(_SIGNED_PREFIX):
        return text

    cleaned = text
    for pattern in _META_INSTRUCTION_TAIL_PATTERNS:
        cleaned = pattern.sub("", cleaned).rstrip()
    return cleaned
