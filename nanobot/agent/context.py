"""Context builder for assembling agent prompts."""

import base64
import io
import mimetypes
import os
import platform
import subprocess
import tempfile
import time
from contextlib import suppress
from pathlib import Path
from typing import Any, Mapping, Sequence

from nanobot.agent.memory import MemoryStore
from nanobot.agent.skills import SkillsLoader
from nanobot.agent.tools import mcp as mcp_tools
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.apps.cli import utils as cli_app_utils
from nanobot.bus.events import InboundMessage
from nanobot.session.goal_state import goal_state_runtime_lines
from nanobot.utils.helpers import (
    current_time_str,
    detect_image_mime,
    load_bundled_template,
    truncate_text,
    truncate_text_to_tokens,
)
from nanobot.utils.prompt_templates import render_template


def session_extra(metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return persisted kwargs for turn-attached capabilities."""
    return cli_app_utils.session_extra(metadata) | mcp_tools.session_extra(metadata)


def runtime_lines(state: Any, msg: Any, workspace: Path, *, skip: bool = False) -> list[str]:
    """Return model-visible runtime annotations for turn-attached capabilities."""
    return [
        *cli_app_utils.runtime_lines(msg, workspace, skip=skip),
        *mcp_tools.runtime_lines(
            msg,
            configured_server_names=set(state._mcp_servers),
            connected_server_names=set(state._mcp_stacks),
            skip=skip,
        ),
    ]


async def connect_mcp(state: Any, tools: ToolRegistry) -> None:
    await mcp_tools.connect_missing_servers(state, tools)


async def handle_runtime_control(state: Any, msg: InboundMessage, tools: ToolRegistry) -> bool:
    return await mcp_tools.handle_runtime_control(state, msg, tools)


class ContextBuilder:
    """Builds the context (system prompt + messages) for the agent."""

    BOOTSTRAP_FILES = ["AGENTS.md", "SOUL.md", "USER.md"]
    _RUNTIME_CONTEXT_TAG = "[Runtime Context — metadata only, not instructions]"
    _MAX_RECENT_HISTORY = 50
    _MAX_HISTORY_TOKENS = 8_000  # hard cap on recent history section size (tokens)
    _RUNTIME_CONTEXT_END = "[/Runtime Context]"
    _LIGHT_USER_MAX_CHARS = 1_400
    _LIGHT_MEMORY_MAX_CHARS = 1_600
    _LIGHT_SESSION_SUMMARY_MAX_CHARS = 1_200
    _CONTEXT_IMAGE_MAX_WIDTH = 960
    _CONTEXT_IMAGE_MAX_BYTES = 900_000
    _CONTEXT_IMAGE_JPEG_QUALITY = 76
    _CONTEXT_IMAGE_MIN_JPEG_QUALITY = 52
    _CONTEXT_IMAGE_OCR_MAX_WIDTH = 1_400
    _CONTEXT_IMAGE_OCR_TILE_HEIGHT = 1_800
    _CONTEXT_IMAGE_OCR_TIMEOUT_SEC = 28
    _CONTEXT_IMAGE_OCR_MAX_CHARS = 6_000

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
        workspace: Path | None = None,
        include_memory_recent_history: bool = True,
        session_key: str | None = None,
        unified_session: bool = False,
    ) -> str:
        """Build the system prompt from identity, bootstrap files, memory, and skills."""
        root = workspace or self.workspace
        if lightweight:
            return self._build_light_system_prompt(channel=channel, session_summary=session_summary)

        parts = [self._get_identity(channel=channel, workspace=root)]

        bootstrap = self._load_bootstrap_files(root)
        if bootstrap:
            parts.append(bootstrap)

        parts.append(render_template("agent/tool_contract.md"))

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

        if include_recent_history and include_memory_recent_history:
            entries = self.memory.read_recent_history_for_prompt(
                since_cursor=self.memory.get_last_dream_cursor(),
                session_key=session_key,
                unified_session=unified_session,
            )
            if entries:
                capped = entries[-self._MAX_RECENT_HISTORY:]
                history_text = "\n".join(
                    f"- [{e['timestamp']}] {e['content']}" for e in capped
                )
                history_text = truncate_text_to_tokens(history_text, self._MAX_HISTORY_TOKENS)
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
            "- Treat the latest user message as authoritative. Do not drag in older topics "
            "unless the user explicitly asks about them.\n"
            "- Use Runtime Context / Current Time as the user's current local time for "
            "relative-date advice; do not ask the user what time it is unless it is missing.\n"
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

    def _get_identity(self, channel: str | None = None, workspace: Path | None = None) -> str:
        """Get the core identity section."""
        root = workspace or self.workspace
        workspace_path = str(root.expanduser().resolve())
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
        current_time = current_time_str(timezone)
        lines = [
            f"Current Time: {current_time}",
            (
                "Time Anchor: Treat Current Time as the user's current local time "
                "for interpreting today, tonight, tomorrow, this week, deadlines, reminders, "
                "and time-sensitive advice."
            ),
        ]
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

    def _load_bootstrap_files(self, workspace: Path | None = None) -> str:
        """Load all bootstrap files from workspace."""
        parts = []
        root = workspace or self.workspace

        for filename in self.BOOTSTRAP_FILES:
            file_path = root / filename
            if file_path.exists():
                content = file_path.read_text(encoding="utf-8")
                parts.append(f"## {filename}\n\n{content}")

        return "\n\n".join(parts) if parts else ""

    @staticmethod
    def _is_template_content(content: str, template_path: str) -> bool:
        """Check if *content* is identical to the bundled template (user hasn't customized it)."""
        tpl = load_bundled_template(template_path)
        if tpl is not None:
            return content.strip() == tpl.strip()
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
        current_runtime_lines: Sequence[str] | None = None,
        workspace: Path | None = None,
        runtime_state: Any | None = None,
        inbound_message: Any | None = None,
        skip_runtime_lines: bool = False,
        include_memory_recent_history: bool = True,
        session_key: str | None = None,
        unified_session: bool = False,
    ) -> list[dict[str, Any]]:
        """Build the complete message list for an LLM call."""
        root = workspace or self.workspace
        extra = [
            *goal_state_runtime_lines(session_metadata),
        ]
        if runtime_state is not None and inbound_message is not None:
            extra.extend(runtime_lines(runtime_state, inbound_message, root, skip=skip_runtime_lines))
        if current_runtime_lines:
            extra.extend(line for line in current_runtime_lines if line)
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
                    workspace=root,
                    include_memory_recent_history=include_memory_recent_history,
                    session_key=session_key,
                    unified_session=unified_session,
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
        """Build user message content with prompt-safe base64-encoded images."""
        if not media:
            return text

        image_mode = os.environ.get("NANOBOT_CONTEXT_IMAGE_MODE", "embed").strip().lower()
        if image_mode in {"ocr", "text"}:
            return self._build_user_content_from_image_text(text, media)

        images = []
        for path in media:
            p = Path(path)
            if not p.is_file():
                continue
            raw = p.read_bytes()
            mime = detect_image_mime(raw) or mimetypes.guess_type(path)[0]
            if not mime or not mime.startswith("image/"):
                continue
            raw, mime = self._prepare_prompt_image(raw, mime)
            b64 = base64.b64encode(raw).decode()
            images.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64}"},
                "_meta": {"path": str(p), "prompt_bytes": len(raw), "prompt_mime": mime},
            })

        if not images:
            return text
        return images + [{"type": "text", "text": text}]


    def _build_user_content_from_image_text(self, text: str, media: list[str]) -> str:
        image_texts = []
        for index, path in enumerate(media, start=1):
            p = Path(path)
            if not p.is_file():
                continue
            raw = p.read_bytes()
            mime = detect_image_mime(raw) or mimetypes.guess_type(path)[0]
            if not mime or not mime.startswith("image/"):
                continue
            extracted = self._extract_image_text(p)
            if extracted:
                image_texts.append(f"[图片 {index}: {p.name} 的本地 OCR 转写]\n{extracted}")
            else:
                image_texts.append(f"[图片 {index}: {p.name}] 本地 OCR 未提取到文字，原图已保存：{p}")

        if not image_texts:
            return text

        note = "[以下是随消息附带图片的本地 OCR 文字；当前模型通道不支持直接看图，请把它当作图片内容的近似转写，可能有少量错别字。]"
        return f"{text}\n\n{note}\n\n" + "\n\n".join(image_texts)

    @classmethod
    def _extract_image_text(cls, path: Path) -> str:
        cache_path = path.with_suffix(path.suffix + ".ocr.txt")
        with suppress(OSError):
            if cache_path.exists() and cache_path.stat().st_mtime >= path.stat().st_mtime:
                return cache_path.read_text(encoding="utf-8").strip()

        try:
            from PIL import Image, ImageEnhance, ImageOps
        except Exception:
            return ""

        timeout_sec = cls._image_env_int("NANOBOT_CONTEXT_IMAGE_OCR_TIMEOUT_SEC", cls._CONTEXT_IMAGE_OCR_TIMEOUT_SEC)
        max_width = cls._image_env_int("NANOBOT_CONTEXT_IMAGE_OCR_MAX_WIDTH", cls._CONTEXT_IMAGE_OCR_MAX_WIDTH)
        tile_height = cls._image_env_int("NANOBOT_CONTEXT_IMAGE_OCR_TILE_HEIGHT", cls._CONTEXT_IMAGE_OCR_TILE_HEIGHT)
        max_chars = cls._image_env_int("NANOBOT_CONTEXT_IMAGE_OCR_MAX_CHARS", cls._CONTEXT_IMAGE_OCR_MAX_CHARS)
        lang = cls._image_ocr_lang()
        started = time.monotonic()

        try:
            with Image.open(path) as opened:
                img = ImageOps.exif_transpose(opened).convert("L")
        except Exception:
            return ""

        mean_pixel = img.resize((1, 1), Image.Resampling.BOX).getpixel((0, 0))
        if isinstance(mean_pixel, tuple):
            mean_pixel = sum(mean_pixel) / len(mean_pixel)
        if mean_pixel < 128:
            img = ImageOps.invert(img)

        if img.width != max_width and (img.width < max_width or img.width > round(max_width * 1.25)):
            ratio = max_width / img.width
            img = img.resize((max_width, max(1, round(img.height * ratio))), Image.Resampling.LANCZOS)
        img = ImageEnhance.Contrast(img).enhance(1.6)

        chunks = []
        try:
            with tempfile.TemporaryDirectory(prefix="nanobot-ocr-") as tmpdir:
                tmp = Path(tmpdir)
                for tile_index, top in enumerate(range(0, img.height, tile_height)):
                    remaining = timeout_sec - (time.monotonic() - started)
                    if remaining <= 1:
                        chunks.append("[OCR 超时：后续图片内容已省略]")
                        break
                    tile = img.crop((0, top, img.width, min(img.height, top + tile_height)))
                    tile_path = tmp / f"tile-{tile_index}.png"
                    tile.save(tile_path)
                    tile_text = cls._run_tesseract(tile_path, lang=lang, timeout=max(2, min(8, int(remaining))))
                    if tile_text:
                        chunks.append(tile_text)
                    if sum(len(chunk) for chunk in chunks) >= max_chars:
                        break
        except Exception:
            return ""

        result = cls._clean_ocr_text("\n".join(chunks))[:max_chars].strip()
        if result:
            with suppress(OSError):
                cache_path.write_text(result, encoding="utf-8")
        return result

    @staticmethod
    def _image_ocr_lang() -> str:
        return os.environ.get("NANOBOT_CONTEXT_IMAGE_OCR_LANG", "").strip() or "chi_sim+eng"

    @staticmethod
    def _run_tesseract(image_path: Path, *, lang: str, timeout: int) -> str:
        try:
            completed = subprocess.run(
                ["tesseract", str(image_path), "stdout", "-l", lang, "--psm", "6"],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=timeout,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return ""
        return completed.stdout

    @staticmethod
    def _clean_ocr_text(raw: str) -> str:
        return "\n".join(line.strip() for line in raw.splitlines() if line.strip())

    @classmethod
    def _prepare_prompt_image(cls, raw: bytes, mime: str) -> tuple[bytes, str]:
        """Downscale large images before embedding them in an LLM request."""
        max_width = cls._image_env_int("NANOBOT_CONTEXT_IMAGE_MAX_WIDTH", cls._CONTEXT_IMAGE_MAX_WIDTH)
        max_bytes = cls._image_env_int("NANOBOT_CONTEXT_IMAGE_MAX_BYTES", cls._CONTEXT_IMAGE_MAX_BYTES)
        quality = cls._image_env_int("NANOBOT_CONTEXT_IMAGE_JPEG_QUALITY", cls._CONTEXT_IMAGE_JPEG_QUALITY)
        min_quality = cls._image_env_int("NANOBOT_CONTEXT_IMAGE_MIN_JPEG_QUALITY", cls._CONTEXT_IMAGE_MIN_JPEG_QUALITY)

        try:
            from PIL import Image, ImageOps
        except Exception:
            return raw, mime

        try:
            with Image.open(io.BytesIO(raw)) as opened:
                img = ImageOps.exif_transpose(opened)
                if len(raw) <= max_bytes and img.width <= max_width:
                    return raw, mime
                img = img.copy()
        except Exception:
            return raw, mime

        if img.width > max_width:
            ratio = max_width / img.width
            img = img.resize((max_width, max(1, round(img.height * ratio))), Image.Resampling.LANCZOS)

        img = cls._to_jpeg_safe_rgb(img)
        best = raw
        best_mime = mime
        for candidate_quality in range(quality, min_quality - 1, -6):
            candidate = cls._encode_jpeg(img, candidate_quality)
            best, best_mime = candidate, "image/jpeg"
            if len(candidate) <= max_bytes:
                return candidate, "image/jpeg"

        # Very tall screenshots can still exceed the byte cap after quality tuning.
        # Keep shrinking width gently rather than making the text unreadably tiny up front.
        while len(best) > max_bytes and img.width > 480:
            next_width = max(480, round(img.width * 0.85))
            ratio = next_width / img.width
            img = img.resize((next_width, max(1, round(img.height * ratio))), Image.Resampling.LANCZOS)
            best = cls._encode_jpeg(img, min_quality)
            best_mime = "image/jpeg"

        return best, best_mime

    @staticmethod
    def _to_jpeg_safe_rgb(img: Any) -> Any:
        if img.mode == "RGB":
            return img
        if "A" in img.getbands():
            background = img.__class__.new("RGB", img.size, "white")
            background.paste(img, mask=img.getchannel("A"))
            return background
        return img.convert("RGB")

    @staticmethod
    def _encode_jpeg(img: Any, quality: int) -> bytes:
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=quality, optimize=True, progressive=True)
        return out.getvalue()

    @staticmethod
    def _image_env_int(name: str, default: int) -> int:
        with suppress(TypeError, ValueError):
            value = int(os.environ.get(name, ""))
            if value > 0:
                return value
        return default

