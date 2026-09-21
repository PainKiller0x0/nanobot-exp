"""Regression tests for provider transport errors leaking into chat text."""

from nanobot.agent.runner import _sanitize_provider_delta, _strip_provider_error_tail


def test_strips_gemini_error_tail_from_final_content() -> None:
    text = "那是身体和大脑都在高负载报警了。累到极点的时候，哪怕是泡脚和正Gemini request failed: Gemini API error code: 1155"

    assert _strip_provider_error_tail(text) == "那是身体和大脑都在高负载报警了。累到极点的时候，哪怕是泡脚和正"


def test_drops_plain_gemini_error_delta() -> None:
    assert _sanitize_provider_delta("Gemini request failed: Gemini API error code: 1155") == ""


def test_keeps_normal_gemini_mentions() -> None:
    assert _strip_provider_error_tail("Gemini 这次回复正常") == "Gemini 这次回复正常"
