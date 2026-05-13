from __future__ import annotations

from nanobot.exp.qq import rss_sidecar


def test_argv_params_latest() -> None:
    parsed = rss_sidecar._argv_params(  # type: ignore[attr-defined]
        ["latest", "--days", "7", "--limit", "50", "--subscription-id", "2", "--refresh"]
    )

    assert parsed == (
        "/api/latest",
        {
            "days": "7",
            "limit": "50",
            "subscription_id": "2",
            "refresh": "true",
        },
    )


def test_argv_params_ask_keeps_question() -> None:
    parsed = rss_sidecar._argv_params(  # type: ignore[attr-defined]
        ["ask", "--question", "Alpha 是什么", "--entry-id", "42"]
    )

    assert parsed == (
        "/api/ask",
        {
            "question": "Alpha 是什么",
            "entry_id": "42",
        },
    )


def test_argv_params_ignores_unknown_command() -> None:
    assert rss_sidecar._argv_params(["timeline"]) is None  # type: ignore[attr-defined]
