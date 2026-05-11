"""Built-in slash command handlers."""

from __future__ import annotations

import asyncio
import os
import sys

from nanobot import __version__
from nanobot.bus.events import OutboundMessage
from nanobot.command.router import CommandContext, CommandRouter
from nanobot.utils.helpers import build_status_content
from nanobot.utils.restart import set_restart_notice_to_env


async def cmd_stop(ctx: CommandContext) -> OutboundMessage:
    """Cancel all active tasks and subagents for the session."""
    loop = ctx.loop
    msg = ctx.msg
    total = await loop._cancel_active_tasks(msg.session_key)
    content = f"Stopped {total} task(s)." if total else "No active task to stop."
    return OutboundMessage(
        channel=msg.channel, chat_id=msg.chat_id, content=content, metadata=dict(msg.metadata or {})
    )


async def cmd_restart(ctx: CommandContext) -> OutboundMessage:
    """Restart the process in-place via os.execv."""
    msg = ctx.msg
    set_restart_notice_to_env(
        channel=msg.channel,
        chat_id=msg.chat_id,
        metadata=dict(msg.metadata or {}),
    )

    async def _do_restart():
        await asyncio.sleep(1)
        os.execv(sys.executable, [sys.executable, "-m", "nanobot"] + sys.argv[1:])

    asyncio.create_task(_do_restart())
    return OutboundMessage(
        channel=msg.channel,
        chat_id=msg.chat_id,
        content="Restarting...",
        metadata=dict(msg.metadata or {}),
    )


async def cmd_status(ctx: CommandContext) -> OutboundMessage:
    """Build an outbound status message for a session."""
    loop = ctx.loop
    session = ctx.session or loop.sessions.get_or_create(ctx.key)
    ctx_est = 0
    try:
        ctx_est, _ = loop.consolidator.estimate_session_prompt_tokens(session)
    except Exception:
        pass
    if ctx_est <= 0:
        ctx_est = loop._last_usage.get("prompt_tokens", 0)

    # Fetch web search provider usage (best-effort, never blocks the response)
    search_usage_text: str | None = None
    try:
        from nanobot.utils.searchusage import fetch_search_usage

        web_cfg = getattr(loop, "web_config", None)
        search_cfg = getattr(web_cfg, "search", None) if web_cfg else None
        if search_cfg is not None:
            provider = getattr(search_cfg, "provider", "duckduckgo")
            api_key = getattr(search_cfg, "api_key", "") or None
            usage = await fetch_search_usage(provider=provider, api_key=api_key)
            search_usage_text = usage.format()
    except Exception:
        pass  # Never let usage fetch break /status
    active_tasks = loop._active_tasks.get(ctx.key, [])
    task_count = sum(1 for t in active_tasks if not t.done())
    try:
        task_count += loop.subagents.get_running_count_by_session(ctx.key)
    except Exception:
        pass
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=build_status_content(
            version=__version__,
            model=loop.model,
            start_time=loop._start_time,
            last_usage=loop._last_usage,
            context_window_tokens=loop.context_window_tokens,
            session_msg_count=len(session.get_history(max_messages=0)),
            context_tokens_estimate=ctx_est,
            search_usage_text=search_usage_text,
            active_task_count=task_count,
            max_completion_tokens=getattr(
                getattr(loop.provider, "generation", None), "max_tokens", 8192
            ),
        ),
        metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
    )


async def cmd_new(ctx: CommandContext) -> OutboundMessage:
    """Stop active task and start a fresh session."""
    loop = ctx.loop
    await loop._cancel_active_tasks(ctx.key)
    session = ctx.session or loop.sessions.get_or_create(ctx.key)
    snapshot = session.messages[session.last_consolidated :]
    session.clear()
    loop.sessions.save(session)
    loop.sessions.invalidate(session.key)
    if snapshot:
        loop._schedule_background(loop.consolidator.archive(snapshot))
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content="New session started.",
        metadata=dict(ctx.msg.metadata or {}),
    )


async def cmd_dream(ctx: CommandContext) -> OutboundMessage:
    """Manually trigger a Dream consolidation run."""
    import time

    loop = ctx.loop
    msg = ctx.msg

    async def _run_dream():
        t0 = time.monotonic()
        try:
            did_work = await loop.dream.run()
            elapsed = time.monotonic() - t0
            if did_work:
                content = f"Dream completed in {elapsed:.1f}s."
            else:
                content = "Dream: nothing to process."
        except Exception as e:
            elapsed = time.monotonic() - t0
            content = f"Dream failed after {elapsed:.1f}s: {e}"
        await loop.bus.publish_outbound(
            OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=content,
            )
        )

    asyncio.create_task(_run_dream())
    return OutboundMessage(
        channel=msg.channel,
        chat_id=msg.chat_id,
        content="Dreaming...",
    )


def _extract_changed_files(diff: str) -> list[str]:
    """Extract changed file paths from a unified diff."""
    files: list[str] = []
    seen: set[str] = set()
    for line in diff.splitlines():
        if not line.startswith("diff --git "):
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        path = parts[3]
        if path.startswith("b/"):
            path = path[2:]
        if path in seen:
            continue
        seen.add(path)
        files.append(path)
    return files


def _format_changed_files(diff: str) -> str:
    files = _extract_changed_files(diff)
    if not files:
        return "No tracked memory files changed."
    return ", ".join(f"`{path}`" for path in files)


def _format_dream_log_content(commit, diff: str, *, requested_sha: str | None = None) -> str:
    files_line = _format_changed_files(diff)
    lines = [
        "## Dream Update",
        "",
        "Here is the selected Dream memory change."
        if requested_sha
        else "Here is the latest Dream memory change.",
        "",
        f"- Commit: `{commit.sha}`",
        f"- Time: {commit.timestamp}",
        f"- Changed files: {files_line}",
    ]
    if diff:
        lines.extend(
            [
                "",
                f"Use `/dream-restore {commit.sha}` to undo this change.",
                "",
                "```diff",
                diff.rstrip(),
                "```",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "Dream recorded this version, but there is no file diff to display.",
            ]
        )
    return "\n".join(lines)


def _format_dream_restore_list(commits: list) -> str:
    lines = [
        "## Dream Restore",
        "",
        "Choose a Dream memory version to restore. Latest first:",
        "",
    ]
    for c in commits:
        lines.append(f"- `{c.sha}` {c.timestamp} - {c.message.splitlines()[0]}")
    lines.extend(
        [
            "",
            "Preview a version with `/dream-log <sha>` before restoring it.",
            "Restore a version with `/dream-restore <sha>`.",
        ]
    )
    return "\n".join(lines)


async def cmd_dream_log(ctx: CommandContext) -> OutboundMessage:
    """Show what the last Dream changed.

    Default: diff of the latest commit (HEAD~1 vs HEAD).
    With /dream-log <sha>: diff of that specific commit.
    """
    store = ctx.loop.consolidator.store
    git = store.git

    if not git.is_initialized():
        if store.get_last_dream_cursor() == 0:
            msg = "Dream has not run yet. Run `/dream`, or wait for the next scheduled Dream cycle."
        else:
            msg = "Dream history is not available because memory versioning is not initialized."
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content=msg,
            metadata={"render_as": "text"},
        )

    args = ctx.args.strip()

    if args:
        # Show diff of a specific commit
        sha = args.split()[0]
        result = git.show_commit_diff(sha)
        if not result:
            content = (
                f"Couldn't find Dream change `{sha}`.\n\n"
                "Use `/dream-restore` to list recent versions, "
                "or `/dream-log` to inspect the latest one."
            )
        else:
            commit, diff = result
            content = _format_dream_log_content(commit, diff, requested_sha=sha)
    else:
        # Default: show the latest commit's diff
        commits = git.log(max_entries=1)
        result = git.show_commit_diff(commits[0].sha) if commits else None
        if result:
            commit, diff = result
            content = _format_dream_log_content(commit, diff)
        else:
            content = "Dream memory has no saved versions yet."

    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=content,
        metadata={"render_as": "text"},
    )


async def cmd_dream_restore(ctx: CommandContext) -> OutboundMessage:
    """Restore memory files from a previous dream commit.

    Usage:
        /dream-restore          — list recent commits
        /dream-restore <sha>    — revert a specific commit
    """
    store = ctx.loop.consolidator.store
    git = store.git
    if not git.is_initialized():
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content="Dream history is not available because memory versioning is not initialized.",
        )

    args = ctx.args.strip()
    if not args:
        # Show recent commits for the user to pick
        commits = git.log(max_entries=10)
        if not commits:
            content = "Dream memory has no saved versions to restore yet."
        else:
            content = _format_dream_restore_list(commits)
    else:
        sha = args.split()[0]
        result = git.show_commit_diff(sha)
        changed_files = _format_changed_files(result[1]) if result else "the tracked memory files"
        new_sha = git.revert(sha)
        if new_sha:
            content = (
                f"Restored Dream memory to the state before `{sha}`.\n\n"
                f"- New safety commit: `{new_sha}`\n"
                f"- Restored files: {changed_files}\n\n"
                f"Use `/dream-log {new_sha}` to inspect the restore diff."
            )
        else:
            content = (
                f"Couldn't restore Dream change `{sha}`.\n\n"
                "It may not exist, or it may be the first saved version with no earlier state to restore."
            )
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=content,
        metadata={"render_as": "text"},
    )


_HISTORY_DEFAULT_COUNT = 10
_HISTORY_MAX_COUNT = 50
_HISTORY_MAX_CONTENT_CHARS = 200


def _format_history_message(msg: dict) -> str | None:
    """Format a single history message for display. Returns None to skip."""
    role = msg.get("role")
    if role not in ("user", "assistant"):
        return None
    content = msg.get("content") or ""
    if isinstance(content, list):
        parts = [
            b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
        ]
        content = " ".join(parts)
    content = str(content).strip()
    if not content:
        return None
    if len(content) > _HISTORY_MAX_CONTENT_CHARS:
        content = content[:_HISTORY_MAX_CONTENT_CHARS] + "…"
    label = "👤 You" if role == "user" else "🤖 Bot"
    return f"{label}: {content}"


async def cmd_history(ctx: CommandContext) -> OutboundMessage:
    """Show the last N messages of the current session (default 10, max 50).

    Usage: /history [count]
    """
    count = _HISTORY_DEFAULT_COUNT
    if ctx.args.strip():
        try:
            count = max(1, min(int(ctx.args.strip()), _HISTORY_MAX_COUNT))
        except ValueError:
            return OutboundMessage(
                channel=ctx.msg.channel,
                chat_id=ctx.msg.chat_id,
                content="Usage: /history [count] — e.g. /history 5 (default: 10, max: 50)",
                metadata=dict(ctx.msg.metadata or {}),
            )

    session = ctx.session or ctx.loop.sessions.get_or_create(ctx.key)
    history = session.get_history(max_messages=0)
    visible = [_format_history_message(m) for m in history]
    visible = [m for m in visible if m is not None]
    recent = visible[-count:]

    if not recent:
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content="No conversation history yet.",
            metadata=dict(ctx.msg.metadata or {}),
        )

    header = f"Last {len(recent)} message(s):\n"
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=header + "\n".join(recent),
        metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
    )


async def cmd_help(ctx: CommandContext) -> OutboundMessage:
    """Return available slash commands."""
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=build_help_text(),
        metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
    )


def build_help_text() -> str:
    """Build the user-facing help panel shared across channels."""
    lines = [
        "\U0001f9ed Nanobot \u4f7f\u7528\u9762\u677f\uff08\u672a\u8c03\u7528 LLM\uff09",
        "",
        "\u4f60\u53ef\u4ee5\u76f4\u63a5\u8fd9\u6837\u95ee\uff1a",
        "- \u5185\u5b58\u600e\u4e48\u6837 \u2014 \u67e5\u770b\u670d\u52a1\u5668\u548c nanobot \u5185\u5b58\uff0c\u4e0d\u8d70\u6a21\u578b",
        "- \u670d\u52a1\u72b6\u6001 \u2014 \u68c0\u67e5 sidecar / \u80fd\u529b\u5065\u5eb7",
        "- \u4eca\u5929\u5148\u770b\u4ec0\u4e48 \u2014 \u4eca\u65e5\u6587\u7ae0\u3001LOF\u3001\u4efb\u52a1\u5f02\u5e38\u6458\u8981",
        "- \u6a21\u578b\u82b1\u8d39 \u2014 \u67e5\u770b OBP \u6d88\u8017\u548c\u6765\u6e90\u7edf\u8ba1",
        "- LOF \u6709\u673a\u4f1a\u5417 \u2014 \u67e5\u770b LOF/QDII \u5b9e\u65f6\u770b\u677f\u548c\u62a5\u544a",
        "- \u4eca\u5929\u70ed\u70b9 / \u65b0\u95fb\u7b80\u62a5 \u2014 \u67e5\u770b\u8fc7\u6ee4\u540e\u7684\u70ed\u70b9\u65b0\u95fb",
        "- \u6536\u4e00\u4e0b <\u94fe\u63a5> \u2014 \u6293\u53d6\u7f51\u9875\u8fdb\u77e5\u8bc6\u6536\u4ef6\u7bb1",
        "- \u8fd9\u4e2a\u503c\u5f97\u770b\u5417 <\u94fe\u63a5> \u2014 \u751f\u6210\u8f7b\u91cf\u51b3\u7b56\u5305",
        "- \u8bb0\u4f4f <\u5185\u5bb9> \u2014 \u5199\u5165\u672c\u5730\u8bb0\u5fc6",
        "- \u8bb0\u5fc6\u72b6\u6001 / \u641c\u8bb0\u5fc6 <\u5173\u952e\u8bcd> \u2014 \u67e5\u770b\u6216\u68c0\u7d22\u8bb0\u5fc6",
        "- \u4f60\u6700\u8fd1\u8fdb\u5316\u4e86\u5417 \u2014 \u67e5\u770b\u8fdb\u5316\u65e5\u5fd7",
        "",
        "\u5feb\u6377\u547d\u4ee4\uff1a",
        "/new \u2014 \u5f00\u542f\u65b0\u4f1a\u8bdd",
        "/stop \u2014 \u505c\u6b62\u5f53\u524d\u4efb\u52a1",
        "/restart \u2014 \u91cd\u542f nanobot",
        "/status \u2014 \u67e5\u770b\u8fd0\u884c\u72b6\u6001",
        "/history [n] \u2014 \u67e5\u770b\u6700\u8fd1 n \u6761\u5bf9\u8bdd",
        "/dream \u2014 \u624b\u52a8\u89e6\u53d1\u8bb0\u5fc6\u6574\u7406",
        "/dream-log \u2014 \u67e5\u770b\u6700\u8fd1\u8bb0\u5fc6\u53d8\u66f4",
        "/dream-restore \u2014 \u56de\u6eda\u8bb0\u5fc6\u7248\u672c",
        "/help \u2014 \u663e\u793a\u8fd9\u4e2a\u9762\u677f",
        "",
        "\u7f51\u9875\u5165\u53e3\uff1ahttp://150.158.121.88:8093/sidecars",
    ]
    return "\n".join(lines)


_HELP_ALIASES = (
    "help",
    "menu",
    "nanobot help",
    "\u5e2e\u52a9",
    "\u83dc\u5355",
    "\u6307\u4ee4",
    "\u6307\u4ee4\u5217\u8868",
    "\u4f7f\u7528\u8bf4\u660e",
    "\u600e\u4e48\u7528",
    "\u4f60\u4f1a\u4ec0\u4e48",
    "\u4f60\u80fd\u505a\u4ec0\u4e48",
    "\u4f60\u80fd\u5e72\u4ec0\u4e48",
    "\u6211\u80fd\u8ba9\u4f60\u505a\u4ec0\u4e48",
    "\u80fd\u529b\u5217\u8868",
    "\u80fd\u529b\u83dc\u5355",
    "\u529f\u80fd\u5217\u8868",
    "\u529f\u80fd\u83dc\u5355",
    "\u6280\u80fd\u5217\u8868",
    "\u6280\u80fd\u83dc\u5355",
)


def register_builtin_commands(router: CommandRouter) -> None:
    """Register the default set of slash commands."""
    router.priority("/stop", cmd_stop)
    router.priority("/restart", cmd_restart)
    router.priority("/status", cmd_status)
    router.exact("/new", cmd_new)
    router.exact("/status", cmd_status)
    router.exact("/history", cmd_history)
    router.prefix("/history ", cmd_history)
    router.exact("/dream", cmd_dream)
    router.exact("/dream-log", cmd_dream_log)
    router.prefix("/dream-log ", cmd_dream_log)
    router.exact("/dream-restore", cmd_dream_restore)
    router.prefix("/dream-restore ", cmd_dream_restore)
    router.exact("/help", cmd_help)
    for alias in _HELP_ALIASES:
        router.exact(alias, cmd_help)
