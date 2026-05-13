from nanobot.agent import memory_client


def test_save_memory_posts_reflexio_payload(monkeypatch) -> None:
    calls = []

    def fake_post(path, payload, default):
        calls.append((path, payload, default))
        return {"success": True, "id": 9}

    monkeypatch.setattr(memory_client, "post_json", fake_post)

    result = memory_client.save_memory("我喜欢 Rust", user_id="u1", category="preference")

    assert result == {"success": True, "id": 9}
    assert calls == [
        (
            "/reflexio/api/memories",
            {
                "user_id": "u1",
                "category": "preference",
                "content": "我喜欢 Rust",
                "source": "nanobot-direct-reply",
            },
            {},
        )
    ]


def test_memory_status_returns_stats_and_list(monkeypatch) -> None:
    def fake_get(path, default):
        if path == "/reflexio/api/stats":
            return {"total_memories": 2}
        if path == "/reflexio/api/memories?limit=5":
            return [{"content": "hello"}]
        return default

    monkeypatch.setattr(memory_client, "get_json", fake_get)

    assert memory_client.memory_status() == ({"total_memories": 2}, [{"content": "hello"}])


def test_memory_status_normalizes_bad_recent_payload(monkeypatch) -> None:
    monkeypatch.setattr(memory_client, "get_json", lambda path, default: {"bad": True})

    assert memory_client.memory_status() == ({"bad": True}, [])


def test_search_memories_returns_results(monkeypatch) -> None:
    def fake_post(path, payload, default):
        assert path == "/reflexio/api/memory/search"
        assert payload == {"query": "Rust", "limit": 8}
        return {"results": [{"id": 1, "content": "Rust sidecar"}]}

    monkeypatch.setattr(memory_client, "post_json", fake_post)

    assert memory_client.search_memories("Rust") == [{"id": 1, "content": "Rust sidecar"}]


def test_search_memories_normalizes_bad_payload(monkeypatch) -> None:
    monkeypatch.setattr(memory_client, "post_json", lambda *args, **kwargs: {"results": "bad"})

    assert memory_client.search_memories("Rust") == []
