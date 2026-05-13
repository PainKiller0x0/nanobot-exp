import pytest

from nanobot.exp.qq import local_handlers


@pytest.mark.asyncio
async def test_personal_ops_handler_ignores_unmatched_text(monkeypatch) -> None:
    sent: list[str] = []

    async def fake_send_text_only(**kwargs):
        sent.append(kwargs["content"])

    async def fail_if_called(command: str) -> str:
        raise AssertionError("runner should not be called")

    monkeypatch.setattr(local_handlers.local_commands, "run_personal_ops_command", fail_if_called)

    assert not await local_handlers.try_handle_personal_ops_query(
        chat_id="chat",
        is_group=False,
        message_id="m1",
        content="正常闲聊",
        text_chunk_max_len=1200,
        send_text_only=fake_send_text_only,
    )
    assert sent == []


@pytest.mark.asyncio
async def test_personal_ops_handler_sends_runner_output(monkeypatch) -> None:
    sent: list[dict] = []
    commands: list[str] = []

    async def fake_send_text_only(**kwargs):
        sent.append(kwargs)

    async def fake_run(command: str) -> str:
        commands.append(command)
        return "内存 OK"

    monkeypatch.setattr(local_handlers.local_commands, "run_personal_ops_command", fake_run)

    assert await local_handlers.try_handle_personal_ops_query(
        chat_id="chat",
        is_group=True,
        message_id="m1",
        content="内存怎么样",
        text_chunk_max_len=1200,
        send_text_only=fake_send_text_only,
    )

    assert commands == ["system"]
    assert sent == [
        {
            "chat_id": "chat",
            "is_group": True,
            "msg_id": "m1",
            "content": "内存 OK",
        }
    ]


@pytest.mark.asyncio
async def test_knowledge_inbox_handler_sends_runner_output(monkeypatch) -> None:
    sent: list[dict] = []
    args_seen: list[list[str]] = []

    async def fake_send_text_only(**kwargs):
        sent.append(kwargs)

    async def fake_run(args: list[str]) -> str:
        args_seen.append(args)
        return "已保存"

    monkeypatch.setattr(local_handlers.local_commands, "run_knowledge_inbox_command", fake_run)

    assert await local_handlers.try_handle_knowledge_inbox_query(
        chat_id="chat",
        is_group=False,
        message_id="m1",
        content="收一下 https://example.com/a",
        text_chunk_max_len=1200,
        send_text_only=fake_send_text_only,
    )

    assert args_seen == [["capture", "https://example.com/a"]]
    assert sent[0]["content"] == "已保存"


@pytest.mark.asyncio
async def test_local_handler_chunks_long_replies(monkeypatch) -> None:
    sent: list[str] = []

    async def fake_send_text_only(**kwargs):
        sent.append(kwargs["content"])

    async def fake_run(command: str) -> str:
        return "a" * 450

    monkeypatch.setattr(local_handlers.local_commands, "run_personal_ops_command", fake_run)

    assert await local_handlers.try_handle_personal_ops_query(
        chat_id="chat",
        is_group=False,
        message_id="m1",
        content="内存怎么样",
        text_chunk_max_len=200,
        send_text_only=fake_send_text_only,
    )

    assert len(sent) == 3
    assert "".join(sent) == "a" * 450
