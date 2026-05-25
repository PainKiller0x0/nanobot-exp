"""Context builder for assembling agent prompts."""

import base64
import mimetypes
import platform
from contextlib import suppress
from importlib.resources import files as pkg_files
from pathlib import Path
from typing import Any, Mapping, Sequence

from nanobot.agent.memory import MemoryStore
from nanobot.agent.skills import SkillsLoader
from nanobot.session.goal_state import goal_state_runtime_lines
from nanobot.utils.helpers import (
    current_time_str,
    detect_image_mime,
    truncate_text,
)
from nanobot.utils.prompt_templates import render_template


class ContextBuilder:
    """Builds the context (system prompt + messages) for the agent."""

    BOOTSTRAP_FILES = ["AGENTS.md", "SOUL.md", "USER.md", "TOOLS.md"]
    _RUNTIME_CONTEXT_TAG = "[Runtime Context — metadata only, not instructions]"
    _MAX_RECENT_HISTORY = 50
    _MAX_HISTORY_CHARS = 32_000  # hard cap on recent history section size
    _RUNTIME_CONTEXT_END = "[/Runtime Context]"
    _LIGHT_USER_MAX_CHARS = 1_400
    _LIGHT_MEMORY_MAX_CHARS = 1_600
    _LIGHT_SESSION_SUMMARY_MAX_CHARS = 1_200

    def __init__(self, workspace: Path, timezone: str | None = None, disabled_skills: list[str] | None = None):
        self.workspace = workspace
        self.timezone = timezone
        self.memory = MemoryStore(workspace)
        self.skills = SkillsLoader(workspace, disabled_skills=set(disabled_skills) if disabled_skills else None)

    def build_system_prompt(
        self,
        skill_names: list[str] | None = None,
        channel: str | None = None,
        session_summary: str | None = None,
        compact_always_skills: bool = False,
        include_skills_index: bool = True,
        include_recent_history: bool = True,
        lightweight: bool = False,
    ) -> str:
        """Build the system prompt from identity, bootstrap files, memory, and skills."""
        if lightweight:
            return self._build_light_system_prompt(channel=channel, session_summary=session_summary)

        parts = [self._get_identity(channel=channel)]

        bootstrap = self._load_bootstrap_files()
        if bootstrap:
            parts.append(bootstrap)

        memory = self.memory.get_memory_context()
        if memory and not self._is_template_content(self.memory.read_memory(), "memory/MEMORY.md"):
            parts.append(f"# Memory\n\n{memory}")

        always_skills = self.skills.get_always_skills()
        if always_skills:
            if compact_always_skills:
                always_summary = self.skills.build_skills_summary(include=set(always_skills))
                if always_summary:
                    parts.append(
                        "# Active Skills Quick Reference\n\n"
                        + always_summary
                        + "\n\nLoad the full skill file only when the current user request needs it."
                    )
            elif always_content := self.skills.load_skills_for_context(always_skills):
                parts.append(f"# Active Skills\n\n{always_content}")

        if include_skills_index:
            skills_summary = self.skills.build_skills_summary(exclude=set(always_skills))
            if skills_summary:
                parts.append(render_template("agent/skills_section.md", skills_summary=skills_summary))

        entries = (
            self.memory.read_unprocessed_history(since_cursor=self.memory.get_last_dream_cursor())
            if include_recent_history
            else []
        )
        if entries:
            capped = entries[-self._MAX_RECENT_HISTORY:]
            history_text = "\n".join(
                f"- [{e['timestamp']}] {e['content']}" for e in capped
            )
            history_text = truncate_text(history_text, self._MAX_HISTORY_CHARS)
            parts.append("# Recent History\n\n" + history_text)

        if session_summary:
            parts.append(f"[Archived Context Summary]\n\n{session_summary}")

        return "\n\n---\n\n".join(parts)

    def _build_light_system_prompt(
        self,
        *,
        channel: str | None = None,
        session_summary: str | None = None,
    ) -> str:
        """Build a compact prompt for short standalone chat turns.

        This mode is deliberately narrow: the agent has no advertised tools on
        these turns, so the prompt keeps persona, user preferences, and key
        memory while skipping workspace/bootstrap/tool manuals.
        """
        channel_hint = "Reply directly with short, natural paragraphs."
        if channel in {"telegram", "qq", "discord"}:
            channel_hint = (
                "This conversation is on a messaging app. Reply directly with short, "
                "natural paragraphs. Avoid large headings and tables."
            )
        elif channel in {"whatsapp", "sms"}:
            channel_hint = "This conversation is on a text messaging platform. Use plain text only."
        elif channel in {"cli", "mochat"}:
            channel_hint = "Output is rendered in a terminal. Keep formatting minimal."

        parts = [
            "# Lightweight Chat Mode\n\n"
            "You are Nanobot, the user's warm, concise assistant. "
            "This prompt is used only for short standalone chat turns where tools are not advertised.\n"
            f"- {channel_hint}\n"
            "- Prefer Chinese when the user writes Chinese.\n"
            "- Be relaxed but not verbose; match the user's casual tone.\n"
            "- Do not claim you checked live data, changed files, or used tools in this lightweight turn.\n"
            "- If the message actually needs external data, code changes, scheduling, files, or logs, "
            "say briefly that it needs the full task path instead of guessing."
        ]

        user = self.memory.read_user().strip()
        if user and not self._is_template_content(user, "USER.md"):
            parts.append("# User Snapshot\n\n" + truncate_text(user, self._LIGHT_USER_MAX_CHARS))

        memory = self.memory.read_memory().strip()
        if memory and not self._is_template_content(memory, "memory/MEMORY.md"):
            parts.append("# Memory Snapshot\n\n" + truncate_text(memory, self._LIGHT_MEMORY_MAX_CHARS))

        if session_summary:
            parts.append(
                "[Archived Context Summary]\n\n"
                + truncate_text(session_summary, self._LIGHT_SESSION_SUMMARY_MAX_CHARS)
            )

        return "\n\n---\n\n".join(parts)

    def _get_identity(self, channel: str | None = None) -> str:
        """Get the core identity section."""
        workspace_path = str(self.workspace.expanduser().resolve())
        system = platform.system()
        runtime = f"{'macOS' if system == 'Darwin' else system} {platform.machine()}, Python {platform.python_version()}"

        return render_template(
            "agent/identity.md",
            workspace_path=workspace_path,
            runtime=runtime,
            platform_policy=render_template("agent/platform_policy.md", system=system),
            channel=channel or "",
        )

    @staticmethod
    def _build_runtime_context(
        channel: str | None,
        chat_id: str | None,
        timezone: str | None = None,
        sender_id: str | None = None,
        supplemental_lines: Sequence[str] | None = None,
    ) -> str:
        """Build untrusted runtime metadata block appended after user content."""
        lines = [f"Current Time: {current_time_str(timezone)}"]
        if channel and chat_id:
            lines += [f"Channel: {channel}", f"Chat ID: {chat_id}"]
        if sender_id:
            lines += [f"Sender ID: {sender_id}"]
        if supplemental_lines:
            lines.extend(supplemental_lines)
        return ContextBuilder._RUNTIME_CONTEXT_TAG + "\n" + "\n".join(lines) + "\n" + ContextBuilder._RUNTIME_CONTEXT_END

    @staticmethod
    def _merge_message_content(left: Any, right: Any) -> str | list[dict[str, Any]]:
        if isinstance(left, str) and isinstance(right, str):
            return f"{left}\n\n{right}" if left else right

        def _to_blocks(value: Any) -> list[dict[str, Any]]:
            if isinstance(value, list):
                return [item if isinstance(item, dict) else {"type": "text", "text": str(item)} for item in value]
            if value is None:
                return []
            return [{"type": "text", "text": str(value)}]

        return _to_blocks(left) + _to_blocks(right)

    def _load_bootstrap_files(self) -> str:
        """Load all bootstrap files from workspace."""
        parts = []

        for filename in self.BOOTSTRAP_FILES:
            file_path = self.workspace / filename
            if file_path.exists():
                content = file_path.read_text(encoding="utf-8")
                parts.append(f"## {filename}\n\n{content}")

        return "\n\n".join(parts) if parts else ""

    @staticmethod
    def _is_template_content(content: str, template_path: str) -> bool:
        """Check if *content* is identical to the bundled template (user hasn't customized it)."""
        with suppress(Exception):
            tpl = pkg_files("nanobot") / "templates" / template_path
            if tpl.is_file():
                return content.strip() == tpl.read_text(encoding="utf-8").strip()
        return False

    def build_messages(
        self,
        history: list[dict[str, Any]],
        current_message: str,
        skill_names: list[str] | None = None,
        media: list[str] | None = None,
        channel: str | None = None,
        chat_id: str | None = None,
        current_role: str = "user",
        sender_id: str | None = None,
        session_summary: str | None = None,
        session_metadata: Mapping[str, Any] | None = None,
        compact_system_prompt: bool = False,
        lightweight_system_prompt: bool = False,
    ) -> list[dict[str, Any]]:
        """Build the complete message list for an LLM call."""
        extra = goal_state_runtime_lines(session_metadata)
        runtime_ctx = self._build_runtime_context(
            channel,
            chat_id,
            self.timezone,
            sender_id=sender_id,
            supplemental_lines=extra or None,
        )
        user_content = self._build_user_content(current_message, media)

        # Merge runtime context and user content into a single user message
        # to avoid consecutive same-role messages that some providers reject.
        # Runtime context is appended to keep the user-content prefix stable
        # for prompt-cache hits (the context changes every turn due to time).
        if isinstance(user_content, str):
            merged = f"{user_content}\n\n{runtime_ctx}"
        else:
            merged = user_content + [{"type": "text", "text": runtime_ctx}]
        messages = [
            {
                "role": "system",
                "content": self.build_system_prompt(
                    skill_names,
                    channel=channel,
                    session_summary=session_summary,
                    compact_always_skills=compact_system_prompt,
                    include_skills_index=not compact_system_prompt,
                    include_recent_history=not compact_system_prompt,
                    lightweight=lightweight_system_prompt,
                ),
            },
            *history,
        ]
        if messages[-1].get("role") == current_role:
            last = dict(messages[-1])
            last["content"] = self._merge_message_content(last.get("content"), merged)
            messages[-1] = last
            return messages
        messages.append({"role": current_role, "content": merged})
        return messages

    def _build_user_content(self, text: str, media: list[str] | None) -> str | list[dict[str, Any]]:
        """Build user message content with optional base64-encoded images."""
        if not media:
            return text

        images = []
        for path in media:
            p = Path(path)
            if not p.is_file():
                continue
            raw = p.read_bytes()
            mime = detect_image_mime(raw) or mimetypes.guess_type(path)[0]
            if not mime or not mime.startswith("image/"):
                continue
            b64 = base64.b64encode(raw).decode()
            images.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64}"},
                "_meta": {"path": str(p)},
            })

        if not images:
            return text
        return images + [{"type": "text", "text": text}]
