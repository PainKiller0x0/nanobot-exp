"""Tests for the nanobot-exp QQ media IO helper seam."""

from types import SimpleNamespace

import pytest

from nanobot.exp.qq import media_io


def test_build_download_target_sanitizes_hint_and_keeps_url_extension(tmp_path) -> None:
    target = media_io.build_download_target(
        tmp_path,
        "https://example.com/files/photo.png?token=1",
        "../../evil",
        now_ms=123,
    )

    assert target == tmp_path / "evil.png"


def test_build_download_target_deduplicates_existing_file(tmp_path) -> None:
    (tmp_path / "report.pdf").write_text("old", encoding="utf-8")

    target = media_io.build_download_target(
        tmp_path,
        "https://example.com/files/report.pdf",
        "report.pdf",
        now_ms=456,
    )

    assert target == tmp_path / "report_456.pdf"


@pytest.mark.asyncio
async def test_read_media_bytes_reads_local_file(tmp_path) -> None:
    file_path = tmp_path / "hello.txt"
    file_path.write_bytes(b"hello")

    data, filename = await media_io.read_media_bytes(None, str(file_path))

    assert data == b"hello"
    assert filename == "hello.txt"


@pytest.mark.asyncio
async def test_handle_attachments_formats_download_results() -> None:
    calls: list[tuple[str, str]] = []

    async def fake_download(url: str, filename_hint: str = "") -> str | None:
        calls.append((url, filename_hint))
        return "/tmp/saved.png"

    attachment = SimpleNamespace(
        url="https://example.com/a.png",
        filename="a.png",
        content_type="image/png",
    )

    media_paths, recv_lines, meta = await media_io.handle_attachments([attachment], fake_download)

    assert calls == [("https://example.com/a.png", "a.png")]
    assert media_paths == ["/tmp/saved.png"]
    assert recv_lines == ["- a.png\n  saved: /tmp/saved.png"]
    assert meta == [
        {
            "url": "https://example.com/a.png",
            "filename": "a.png",
            "content_type": "image/png",
            "saved_path": "/tmp/saved.png",
        }
    ]


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def json(self) -> dict:
        return self.payload


class _FakeSession:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls: list[tuple[str, dict]] = []

    def post(self, url: str, *, json: dict):
        self.calls.append((url, json))
        return _FakeResponse(self.payload)


@pytest.mark.asyncio
async def test_download_to_media_dir_chunked_calls_qq_sidecar(tmp_path) -> None:
    session = _FakeSession({"success": True})

    result = await media_io.download_to_media_dir_chunked(
        session,  # type: ignore[arg-type]
        tmp_path,
        "https://example.com/report.pdf",
        filename_hint="report.pdf",
        max_bytes=1024 * 1024,
    )

    assert result == str(tmp_path / "report.pdf")
    assert session.calls == [
        (
            "http://172.17.0.1:8092/download",
            {
                "url": "https://example.com/report.pdf",
                "target_path": str(tmp_path / "report.pdf"),
                "max_bytes": 1024 * 1024,
            },
        )
    ]
