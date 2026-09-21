from __future__ import annotations

import textwrap

import pytest

from nanobot.exp.qq.local_commands import run_knowledge_inbox_command, run_personal_ops_command


@pytest.mark.asyncio
async def test_local_command_runner_reports_missing_script(tmp_path) -> None:
    missing = tmp_path / "missing.py"

    assert await run_personal_ops_command("system", script=missing) == "运维助手脚本不存在，暂时无法查询。"
    assert await run_knowledge_inbox_command(["list"], script=missing) == "知识收件箱脚本不存在，暂时无法处理链接。"


@pytest.mark.asyncio
async def test_local_command_runner_returns_stdout(tmp_path) -> None:
    script = tmp_path / "ok.py"
    script.write_text("import sys\nprint('ok:' + ','.join(sys.argv[1:]))\n", encoding="utf-8")

    assert await run_personal_ops_command("system", script=script) == "ok:system"
    assert await run_knowledge_inbox_command(["capture", "https://example.com"], script=script) == (
        "ok:capture,https://example.com"
    )


@pytest.mark.asyncio
async def test_local_command_runner_reports_failure(tmp_path) -> None:
    script = tmp_path / "fail.py"
    script.write_text(
        textwrap.dedent(
            """
            import sys
            print('bad stderr', file=sys.stderr)
            raise SystemExit(2)
            """
        ),
        encoding="utf-8",
    )

    assert await run_personal_ops_command("system", script=script) == "运维查询失败：bad stderr"
