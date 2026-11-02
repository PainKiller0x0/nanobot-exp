"""The terminal canonical snapshot supersedes an emitted draft."""

import pytest
from openai.types.chat import ChatCompletionChunk

from nanobot.providers.openai_compat_provider import OpenAICompatProvider


def _chunk(content=None, canonical=None, finish=None):
    delta = {} if content is None else {"content": content}
    if canonical is not None:
        delta["x_gemini_canonical_text"] = canonical
    return {
        "id": "test", "object": "chat.completion.chunk", "created": 1,
        "model": "test", "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }


@pytest.mark.parametrize("sdk", [False, True])
@pytest.mark.parametrize("canonical", ["", "Final answer.", "Unable to complete this request."])
def test_terminal_snapshot_replaces_draft(sdk, canonical):
    chunks = [_chunk("Discarded draft."), _chunk(canonical=canonical, finish="stop")]
    if sdk:
        chunks = [ChatCompletionChunk.model_validate(chunk) for chunk in chunks]
    result = OpenAICompatProvider._parse_chunks(chunks)
    assert result.content == canonical
    assert result.finish_reason == "stop"


def test_nonterminal_snapshot_is_not_authoritative():
    result = OpenAICompatProvider._parse_chunks([
        _chunk("Actual answer.", canonical="Not final."), _chunk(finish="stop"),
    ])
    assert result.content == "Actual answer."


def test_append_only_provider_is_unchanged():
    result = OpenAICompatProvider._parse_chunks([
        _chunk("Hello"), _chunk(" world"), _chunk(finish="stop"),
    ])
    assert result.content == "Hello world"
