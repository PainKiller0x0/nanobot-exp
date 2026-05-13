"""Tests for QQ inbound runtime helpers."""

from types import SimpleNamespace

from nanobot.exp.qq import inbound_runtime


def test_resolve_chat_context_c2c_updates_cache() -> None:
    cache: dict[str, str] = {}
    data = SimpleNamespace(author=SimpleNamespace(user_openid="u1"))

    assert inbound_runtime.resolve_chat_context(data, is_group=False, chat_type_cache=cache) == ("u1", "u1")
    assert cache == {"u1": "c2c"}


def test_resolve_chat_context_group_requires_group_openid() -> None:
    cache: dict[str, str] = {}
    data = SimpleNamespace(id="m1", author=SimpleNamespace(member_openid="member1"))

    assert inbound_runtime.resolve_chat_context(data, is_group=True, chat_type_cache=cache) is None
    assert cache == {}


def test_resolve_chat_context_group_updates_cache() -> None:
    cache: dict[str, str] = {}
    data = SimpleNamespace(group_openid="g1", author=SimpleNamespace(member_openid="member1"))

    assert inbound_runtime.resolve_chat_context(data, is_group=True, chat_type_cache=cache) == ("g1", "member1")
    assert cache == {"g1": "group"}


def test_compose_attachment_content_with_image() -> None:
    result = inbound_runtime.compose_attachment_content(
        "hello",
        media_paths=["/tmp/a.png"],
        recv_lines=["- a.png\n  saved: /tmp/a.png"],
    )

    assert result == "hello\n\nReceived files:\n- a.png\n  saved: /tmp/a.png"


def test_compose_attachment_content_without_text_uses_file_tag() -> None:
    result = inbound_runtime.compose_attachment_content(
        "",
        media_paths=["/tmp/a.pdf"],
        recv_lines=["- a.pdf\n  saved: /tmp/a.pdf"],
    )

    assert result == "[File]\nReceived files:\n- a.pdf\n  saved: /tmp/a.pdf"
