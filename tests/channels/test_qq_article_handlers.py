import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.exp.qq import article_handlers


def _publisher(calls: list[OutboundMessage]):
    async def publish(message: OutboundMessage) -> None:
        calls.append(message)

    return publish


@pytest.mark.asyncio
async def test_yage_handler_ignores_unrelated_text() -> None:
    calls: list[OutboundMessage] = []

    async def fake_run_yage_signed(**kwargs):
        raise AssertionError("should not run yage")

    assert not await article_handlers.try_handle_yage_raw(
        chat_id="chat",
        content="鸭哥这个名字挺有意思",
        message_id="m1",
        run_yage_signed=fake_run_yage_signed,
        publish_outbound=_publisher(calls),
    )
    assert calls == []


@pytest.mark.asyncio
async def test_yage_handler_sends_signed_article() -> None:
    calls: list[OutboundMessage] = []
    run_args: list[dict] = []

    async def fake_run_yage_signed(**kwargs):
        run_args.append(kwargs)
        return "signed article"

    assert await article_handlers.try_handle_yage_raw(
        chat_id="chat",
        content="发我最新鸭哥文章",
        message_id="m1",
        run_yage_signed=fake_run_yage_signed,
        publish_outbound=_publisher(calls),
    )

    assert calls[0].content == "signed article"
    assert calls[0].metadata == {"message_id": "m1"}
    assert run_args[0]["force_latest"] is True


@pytest.mark.asyncio
async def test_yage_handler_reports_empty_selector() -> None:
    calls: list[OutboundMessage] = []

    async def fake_run_yage_signed(**kwargs):
        return ""

    assert await article_handlers.try_handle_yage_raw(
        chat_id="chat",
        content="鸭哥 4/10 那篇呢？",
        message_id="m1",
        run_yage_signed=fake_run_yage_signed,
        publish_outbound=_publisher(calls),
    )

    assert "date=" in calls[0].content


@pytest.mark.asyncio
async def test_wechat_handler_ignores_disallowed_user() -> None:
    calls: list[OutboundMessage] = []

    async def fake_sidecar(args):
        raise AssertionError("should not call sidecar")

    assert not await article_handlers.try_handle_wechat_grounded(
        user_id="user",
        chat_id="chat",
        content="微信公众号最新文章",
        message_id="m1",
        is_allowed=lambda user_id: False,
        run_sidecar_json=fake_sidecar,
        publish_outbound=_publisher(calls),
    )
    assert calls == []


@pytest.mark.asyncio
async def test_wechat_title_query_uses_latest_sidecar_result() -> None:
    calls: list[OutboundMessage] = []
    requested: list[list[str]] = []

    async def fake_sidecar(args):
        requested.append(args)
        return {
            "status": "ok",
            "title": "今日文章",
            "entry_id": 12,
            "published_at": "2026-05-13 10:00",
            "link": "https://example.test/a",
        }

    assert await article_handlers.try_handle_wechat_grounded(
        user_id="user",
        chat_id="chat",
        content="微信公众号最新文章",
        message_id="m1",
        is_allowed=lambda user_id: True,
        run_sidecar_json=fake_sidecar,
        publish_outbound=_publisher(calls),
    )

    assert requested == [["latest", "--days", "7", "--limit", "50"]]
    assert "最新文章：今日文章" in calls[0].content
    assert "entry_id: 12" in calls[0].content


@pytest.mark.asyncio
async def test_wechat_question_query_uses_ask_sidecar_result() -> None:
    calls: list[OutboundMessage] = []
    requested: list[list[str]] = []

    async def fake_sidecar(args):
        requested.append(args)
        return {
            "status": "ok",
            "answer": "原文答案",
            "entry_id": 3,
            "published_at": "2026-05-13 09:00",
            "link": "https://example.test/q",
        }

    assert await article_handlers.try_handle_wechat_grounded(
        user_id="user",
        chat_id="chat",
        content="微信公众号文章提到：Alpha 是什么",
        message_id="m1",
        is_allowed=lambda user_id: True,
        run_sidecar_json=fake_sidecar,
        publish_outbound=_publisher(calls),
    )

    assert requested[0][:2] == ["ask", "--question"]
    assert "原文答案" in calls[0].content
