import sys

from nanobot.agent.inbox_tool import clip_text, resolve_tool, run_tool


def test_resolve_tool_prefers_existing_configured_path(tmp_path) -> None:
    tool = tmp_path / "inbox.py"
    tool.write_text("print('ok')", encoding="utf-8")

    assert resolve_tool(env={"NANOBOT_KNOWLEDGE_INBOX_TOOL": str(tool)}) == tool


def test_resolve_tool_falls_back_to_existing_default(tmp_path) -> None:
    configured = tmp_path / "missing.py"
    default = tmp_path / "default.py"
    default.write_text("print('default')", encoding="utf-8")

    assert (
        resolve_tool(
            env={"NANOBOT_KNOWLEDGE_INBOX_TOOL": str(configured)},
            default_tool=default,
            fallback_tool=tmp_path / "fallback.py",
        )
        == default
    )


def test_clip_text_truncates_long_output() -> None:
    text = clip_text("x" * 80, limit=40)

    assert len(text) <= 40
    assert "已截断" in text


def test_run_tool_passes_user_and_returns_stdout(tmp_path) -> None:
    tool = tmp_path / "tool.py"
    tool.write_text(
        "import os, sys\n"
        "print(os.environ.get('NANOBOT_INBOX_USER'))\n"
        "print(' '.join(sys.argv[1:]))\n",
        encoding="utf-8",
    )

    out = run_tool(
        ["capture", "https://example.com/a"],
        user_id="u1",
        env={"NANOBOT_KNOWLEDGE_INBOX_TOOL": str(tool)},
        python_executable=sys.executable,
    )

    assert "u1" in out
    assert "capture https://example.com/a" in out


def test_run_tool_formats_failures(tmp_path) -> None:
    tool = tmp_path / "tool.py"
    tool.write_text("import sys\nprint('bad', file=sys.stderr)\nsys.exit(2)\n", encoding="utf-8")

    out = run_tool(
        ["list"],
        env={"NANOBOT_KNOWLEDGE_INBOX_TOOL": str(tool)},
        python_executable=sys.executable,
    )

    assert out.startswith("知识收件箱失败：bad")
