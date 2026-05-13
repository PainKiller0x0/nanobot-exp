"""Local Reflexio memory direct replies."""

from __future__ import annotations

from nanobot.agent import memory_client, memory_formatters, memory_intents

extract_memory_to_save = memory_intents.extract_memory_to_save
extract_memory_search = memory_intents.extract_memory_search
is_memory_status_query = memory_intents.is_memory_status_query


def remember_memory(content: str, user_id: str | None) -> str:
    content = memory_intents.clean_content(content)
    if not content:
        return memory_formatters.format_empty_memory()
    data = memory_client.save_memory(
        content,
        user_id=user_id,
        category=memory_intents.guess_category(content),
    )
    return memory_formatters.format_memory_saved(content, data)


def format_memory_status() -> str:
    stats, recent = memory_client.memory_status()
    return memory_formatters.format_memory_status(stats, recent)


def search_memory(query: str) -> str:
    query = memory_intents.clean_content(query)
    results = memory_client.search_memories(query, limit=8)
    return memory_formatters.format_memory_search(query, results)
