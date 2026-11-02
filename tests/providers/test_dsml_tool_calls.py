"""Regression tests for text-encoded DSML tool calls at the provider boundary."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from nanobot.agent.runner import AgentRunner, AgentRunSpec
from nanobot.agent.tools.filesystem import ListDirTool, ReadFileTool, WriteFileTool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.search import FindFilesTool
from nanobot.providers.openai_compat_provider import OpenAICompatProvider
from nanobot.utils.llm_runtime import LLMRuntime

MARK = "\uff5c\uff5cDSML\uff5c\uff5c "
ARCHIVE = "/root/.nanobot/workspace/context/personal_condition/261014"
RAW = (
    f'<{MARK}calls>\n<{MARK}invoke name="list_dir">\n'
    f'<{MARK}parameter name="path" string="true">{ARCHIVE}</{MARK}parameter>\n'
    f'</{MARK}invoke>\n<{MARK}invoke name="find_files">\n'
    f'<{MARK}parameter name="pattern" string="true">*\u65e5\u8bb0*</{MARK}parameter>\n'
    f'</{MARK}invoke>\n</{MARK}calls>'
)


class FakeSDKModel(SimpleNamespace):
    def model_dump(self):
        return vars(self)


def dsml(name, **arguments):
    params = "".join(
        f'<{MARK}parameter name="{key}" string="{str(isinstance(value, str)).lower()}">'
        f'{value if isinstance(value, str) else json.dumps(value)}</{MARK}parameter>'
        for key, value in arguments.items()
    )
    return f'<{MARK}calls><{MARK}invoke name="{name}">{params}</{MARK}invoke></{MARK}calls>'


def chunks(text, width=1):
    result = [FakeSDKModel(choices=[FakeSDKModel(
        delta=FakeSDKModel(content=text[i:i + width], tool_calls=[]), finish_reason=None,
    )]) for i in range(0, len(text), width)]
    result.append(FakeSDKModel(choices=[FakeSDKModel(
        delta=FakeSDKModel(content=None, tool_calls=[]), finish_reason="stop",
    )]))
    return result


def test_actual_dsml_becomes_two_calls_with_exact_names_and_path():
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider()
    result = provider._parse({"choices":[{"message":{"content":RAW}, "finish_reason":"stop"}]})
    assert result.content is None
    assert [c.name for c in result.tool_calls] == ["list_dir", "find_files"]
    assert result.tool_calls[0].arguments == {"path": ARCHIVE}
    assert result.tool_calls[1].arguments == {"pattern": "*\u65e5\u8bb0*"}
    assert len({c.id for c in result.tool_calls}) == 2


def test_dsml_preserves_literal_strings_and_json_types():
    literal = 'A & B <notes> "quoted"\nsecond line'
    result = OpenAICompatProvider._parse_chunks(chunks(dsml(
        "write_file", content=literal, limit=2, enabled=False, options={"a":[1, 2]},
    )))
    assert result.content is None
    assert result.tool_calls[0].arguments == {
        "content":literal, "limit":2, "enabled":False, "options":{"a":[1, 2]},
    }


def test_native_calls_take_priority_without_leaking_duplicate_dsml():
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider()
    result = provider._parse({"choices":[{"message":{"content":RAW, "tool_calls":[{
        "id":"native-call", "function":{"name":"read_file", "arguments":'{"path":"rules.md"}'},
    }]}, "finish_reason":"tool_calls"}]})
    assert result.content is None
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].id == "native-call"
    assert result.tool_calls[0].name == "read_file"


@pytest.mark.parametrize("container,bars", [("calls", "\uff5c\uff5c"), ("function_calls", "\uff5c"), ("function_calls", "|")])
def test_dsml_supports_container_marker_forms(container, bars):
    raw = dsml("list_dir", path=".").replace(MARK, bars + "DSML" + bars).replace("calls>", container + ">")
    result = OpenAICompatProvider._parse_chunks(chunks(raw))
    assert result.tool_calls[0].name == "list_dir"


@pytest.mark.parametrize("text", ["```xml\n" + RAW + "\n```", "Example only:\n" + RAW])
def test_quoted_or_documented_dsml_is_not_executed(text):
    result = OpenAICompatProvider._parse_chunks(chunks(text))
    assert not result.tool_calls
    assert result.content == text


@pytest.mark.parametrize("text", [RAW[:-5], dsml("list_dir", x=1).replace('>1<', '>bad json<')])
def test_malformed_dsml_is_not_a_successful_answer(text):
    with pytest.raises(ValueError, match="DSML"):
        OpenAICompatProvider._parse_chunks(chunks(text))


@pytest.mark.asyncio
@pytest.mark.parametrize("text", [RAW, '<tool_call>{"name":"list_dir","arguments":{"path":"."}}</tool_call>'])
@pytest.mark.parametrize("width", [1, 7, 4096])
async def test_stream_never_emits_tool_protocol_to_content_callback(text, width):
    async def stream():
        for chunk in chunks(text, width):
            yield chunk

    visible = []
    async def on_delta(text):
        visible.append(text)

    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI") as client:
        client.return_value.chat.completions.create = AsyncMock(return_value=stream())
        provider = OpenAICompatProvider(api_key="test-only", default_model="gemini-3.8-flash")
        result = await provider.chat_stream(messages=[{"role":"user","content":"read the file"}], on_content_delta=on_delta)
    assert result.tool_calls
    assert visible == []


@pytest.mark.asyncio
async def test_normal_reply_streams_before_the_next_chunk():
    visible = []
    async def stream():
        yield chunks("Hello", 4096)[0]
        assert visible == ["Hello"], "normal reply was buffered until stream completion"
        yield chunks(" world", 4096)[0]
        yield chunks("")[-1]

    async def on_delta(text):
        visible.append(text)

    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI") as client:
        client.return_value.chat.completions.create = AsyncMock(return_value=stream())
        provider = OpenAICompatProvider(api_key="test-only", default_model="gemini-3.8-flash")
        result = await provider.chat_stream(messages=[{"role":"user","content":"hello"}], on_content_delta=on_delta)
    assert result.content == "Hello world"
    assert "".join(visible) == "Hello world"


@pytest.mark.asyncio
async def test_malformed_stream_does_not_leak_markup_or_execute_partial_calls():
    async def stream():
        for chunk in chunks(RAW[:-5]):
            yield chunk

    visible = []
    async def on_delta(text):
        visible.append(text)

    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI") as client:
        client.return_value.chat.completions.create = AsyncMock(return_value=stream())
        provider = OpenAICompatProvider(api_key="test-only", default_model="gemini-3.8-flash")
        result = await provider.chat_stream(messages=[{"role":"user","content":"write diary"}], on_content_delta=on_delta)
    assert result.finish_reason == "error"
    assert not result.tool_calls
    assert visible == []
    assert "<" not in result.content


@pytest.mark.asyncio
async def test_runner_executes_dsml_read_and_write_instead_of_printing_it(tmp_path):
    (tmp_path / "diary-rules.md").write_text("Use facts and preserve emotions.\n", encoding="utf-8")
    destination = tmp_path / "diary-test.md"
    body = "Test fixture only. No real personal diary was generated.\n"
    turns = iter([
        dsml("list_dir", path=str(tmp_path)),
        dsml("find_files", glob="*diary*", path=str(tmp_path)),
        dsml("read_file", path=str(tmp_path / "diary-rules.md")),
        dsml("write_file", path=str(destination), content=body),
        "Test file saved.",
    ])
    async def complete(**kwargs):
        for message in kwargs["messages"]:
            if message.get("role") == "tool":
                assert not str(message.get("content", "")).startswith("Error:"), message
        text = next(turns)
        async def stream():
            for chunk in chunks(text):
                yield chunk
        return stream()

    registry = ToolRegistry()
    for tool in [ListDirTool, FindFilesTool, ReadFileTool, WriteFileTool]:
        registry.register(tool(workspace=tmp_path, allowed_dir=tmp_path))
    async def no_compaction(_messages, _previous_summary):
        return None

    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI") as client:
        client.return_value.chat.completions.create = AsyncMock(side_effect=complete)
        provider = OpenAICompatProvider(api_key="test-only", default_model="gemini-3.8-flash")
        result = await AgentRunner().run(AgentRunSpec(
            runtime=LLMRuntime.capture(provider, "gemini-3.8-flash", context_window_tokens=65536), initial_messages=[{"role":"user","content":"Write a test file using the diary rules."}],
            tools=registry, max_iterations=6, max_tool_result_chars=4000, workspace=tmp_path, consolidate_history=no_compaction,
        ))
    assert result.final_content == "Test file saved."
    assert set(result.tools_used) == {"list_dir", "find_files", "read_file", "write_file"}
    assert destination.read_text(encoding="utf-8") == body
