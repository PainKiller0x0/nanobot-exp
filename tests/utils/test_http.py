from nanobot.utils import http


class _Response:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self) -> bytes:
        return self.body


def test_json_client_fails_over_to_next_base(monkeypatch) -> None:
    calls = []

    def fake_urlopen(request, timeout):
        calls.append((request.full_url, timeout))
        if request.full_url.endswith("/bad/health"):
            raise OSError("offline")
        return _Response(b'{"ok": true}')

    monkeypatch.setattr(http, "urlopen", fake_urlopen)

    assert (
        http.request_json(
            ["http://bad/health", "http://good/health"],
            "GET",
            None,
            {},
            timeout=0.35,
        )
        == {"ok": True}
    )
    assert calls == [
        ("http://bad/health", 0.35),
        ("http://good/health", 0.35),
    ]


def test_json_client_encodes_post_payload(monkeypatch) -> None:
    captured = {}

    def fake_urlopen(request, timeout):
        captured["method"] = request.method
        captured["body"] = request.data
        captured["timeout"] = timeout
        return _Response(b'{"saved": true}')

    monkeypatch.setattr(http, "urlopen", fake_urlopen)

    assert (
        http.request_json(
            "http://service/items",
            "POST",
            {"内容": "Rust"},
            {},
            timeout=0.5,
        )
        == {"saved": True}
    )
    assert captured == {
        "method": "POST",
        "body": '{"内容": "Rust"}'.encode("utf-8"),
        "timeout": 0.5,
    }
