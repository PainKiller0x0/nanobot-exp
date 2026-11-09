"""QQ channel implementation using botpy SDK.

Inbound:
- Parse QQ botpy messages (C2C / Group)
- Download attachments to media dir using chunked streaming write (memory-safe)
- Publish to Nanobot bus via BaseChannel._handle_message()
- Content includes a clear, actionable "Received files:" list with local paths

Outbound:
- Send attachments (msg.media) first via QQ rich media API (base64 upload + msg_type=7)
- Then send text (plain or markdown)
- msg.media supports local paths, file:// paths, and http(s) URLs

Notes:
- QQ restricts many audio/video formats. We conservatively classify as image vs file.
- Attachment structures differ across botpy versions; we try multiple field candidates.
"""

# pyright: reportConstantRedefinition=false, reportMissingTypeStubs=false, reportPrivateUsage=false

from __future__ import annotations

import asyncio
import base64
import json
import mimetypes
import os
import re
import time
from collections import deque
from collections.abc import Callable, Mapping
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Literal, cast
from urllib.parse import unquote, urlparse

import aiohttp
from loguru import logger
from pydantic import Field

from nanobot.bus.delivery import ChannelNotReadyError
from nanobot.bus.events import OutboundMessage
from nanobot.bus.outbound_events import ContextCompactionEvent
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config_base import Base
from nanobot.exp.qq import article_handlers as qq_article_handlers
from nanobot.exp.qq import article_runtime as qq_article_runtime
from nanobot.exp.qq import gateway_greeting as qq_gateway_greeting
from nanobot.exp.qq import local_handlers as qq_local_handlers
from nanobot.exp.qq import signatures as qq_signatures
from nanobot.exp.qq import signed_delivery as qq_signed_delivery
from nanobot.exp.qq import stream_runtime as qq_stream_runtime
from nanobot.exp.qq import streaming as qq_streaming
from nanobot.security.network import validate_url_target
from nanobot.utils.helpers import split_message

try:
    from nanobot.config.paths import get_media_dir
except Exception:  # pragma: no cover
    get_media_dir = None  # type: ignore

try:
    import botpy
    from botpy.gateway import BotWebSocket
    from botpy.http import Route

    QQ_AVAILABLE = True
except ImportError:  # pragma: no cover
    QQ_AVAILABLE = False
    botpy = None
    BotWebSocket = None
    Route = None


# QQ rich media file_type: 1=image, 4=file
# (2=voice, 3=video are restricted; we only use image vs file)
QQ_FILE_TYPE_IMAGE = 1
QQ_FILE_TYPE_FILE = 4

_RECONNECT_BACKOFF_START = 5
_RECONNECT_BACKOFF_MAX = 300


_TTS_ERROR_REPLY_PREFIXES = (
    "error:",
    "error calling llm:",
    "exception:",
    "traceback (most recent call last):",
    "gemini request failed:",
    "image generation failed:",
    "ai 调用失败:",
    "ai 调用失败：",
    "生图失败:",
    "生图失败：",
    "i encountered an error doing what you asked.",
    "i'm having a hard time fulfilling your request.",
    "i seem to be encountering an error.",
    "sorry, i encountered an error",
)


def _is_obvious_error_reply(text: str | None) -> bool:
    """Keep raw provider failures from being read aloud as normal replies."""
    return (text or "").lstrip().casefold().startswith(_TTS_ERROR_REPLY_PREFIXES)


def _unwrap_text_envelope(text: str) -> str:
    """Unwrap only the exact text envelope occasionally leaked by the model."""
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return text
    if not isinstance(value, dict):
        return text
    payload = cast(dict[str, object], value)
    if (
        set(payload) == {"status", "content"}
        and payload["status"] == "text"
        and isinstance(payload["content"], str)
    ):
        return payload["content"]
    return text


def _is_network_error(exc: BaseException) -> bool:
    return isinstance(exc, (aiohttp.ClientConnectorError, OSError))

_IMAGE_EXTS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".bmp",
    ".webp",
    ".tif",
    ".tiff",
    ".ico",
    ".svg",
}

_SAFE_NAME_RE = re.compile(r"[^\w.\-()\[\]（）【】\u4e00-\u9fff]+", re.UNICODE)


def _sanitize_filename(name: str) -> str:
    name = (name or "").strip()
    name = Path(name).name
    name = _SAFE_NAME_RE.sub("_", name).strip("._ ")
    return name


def _is_image_name(name: str) -> bool:
    return Path(name).suffix.lower() in _IMAGE_EXTS


def _parse_qq_timestamp(ts: str | None) -> datetime | None:  # pyright: ignore[reportUnusedFunction]
    """Parse QQ API timestamp string to UTC datetime.

    QQ returns timestamps as Unix epoch in seconds (or ms), e.g. '1743890400'.
    """
    if not ts:
        return None
    try:
        # Try as numeric string (seconds or milliseconds)
        value = int(ts)
        # If value looks like milliseconds ( > 1e10 for year 1970+ ),
        # divide by 1000
        if value > 10**10:
            value //= 1000
        return datetime.fromtimestamp(value, tz=timezone.utc)
    except (ValueError, OSError):
        return None


def _guess_send_file_type(filename: str) -> int:
    ext = Path(filename).suffix.lower()
    mime, _ = mimetypes.guess_type(filename)
    if ext in _IMAGE_EXTS or (mime and mime.startswith("image/")):
        return QQ_FILE_TYPE_IMAGE
    return QQ_FILE_TYPE_FILE


def _strip_silent_marker(text: str) -> str:
    return qq_signatures.strip_silent_marker(text)


_GENERATED_IMAGE_READY_TEXT = "\u56fe\u7247\u751f\u6210\u597d\u4e86\u3002"
_GEMINI_IMAGE_URL_HOSTS = {"150.158.121.88", "127.0.0.1", "localhost", "172.17.0.1"}
_GEMINI_IMAGE_MARKDOWN_RE = re.compile(
    r"!\[[^\]]*\]\((?P<url>https?://[^\s)]+/gemini-images/[^\s)]+)\)",
    re.IGNORECASE,
)
_GEMINI_IMAGE_LINK_RE = re.compile(
    r"\[(?:Open image)\]\((?P<url>https?://[^\s)]+/gemini-images/[^\s)]+)\)",
    re.IGNORECASE,
)


_IMAGE_REQUEST_NEGATIVE_MARKERS = (
    "do not generate image", "don't generate image", "not generate image", "just describe",
    "\u753b\u56fe\u5d29", "\u751f\u56fe\u5931\u8d25", "\u751f\u6210\u56fe\u7247\u5931\u8d25",
    "\u5e2e\u6211\u770b\u4e0b\u65e5\u5fd7", "\u770b\u4e0b\u65e5\u5fd7", "\u62a5\u9519",
)
_IMAGE_REQUEST_MARKERS = (
    "generate an image", "create an image", "draw an image", "make an image",
    "generate a picture", "create a picture", "draw a picture",
    "\u7ed9\u6211\u753b", "\u5e2e\u6211\u753b", "\u753b\u4e00\u5f20", "\u753b\u5f20",
    "\u751f\u6210\u4e00\u5f20\u56fe", "\u751f\u6210\u56fe\u7247", "\u521b\u5efa\u56fe\u7247", "\u51fa\u4e00\u5f20\u56fe",
)


def _has_explicit_image_generation_request(text: str) -> bool:
    """Allow automatic Gemini image delivery only for an explicit image request."""
    lowered = (text or "").strip().lower()
    if not lowered or any(marker in lowered for marker in _IMAGE_REQUEST_NEGATIVE_MARKERS):
        return False
    return any(marker in lowered for marker in _IMAGE_REQUEST_MARKERS)


def _is_gemini_image_url(url: str) -> bool:
    try:
        parsed = urlparse(url.strip().strip("<>"))
    except Exception:
        return False
    host = (parsed.hostname or "").lower()
    return (
        parsed.scheme in {"http", "https"}
        and host in _GEMINI_IMAGE_URL_HOSTS
        and parsed.path.startswith("/gemini-images/")
        and _is_image_name(parsed.path)
    )


def _gemini_image_fetch_url(url: str) -> tuple[str, bool]:
    """Rewrite our public Gemini image URLs to the host-only gateway from containers."""
    if not _is_gemini_image_url(url):
        return url, False
    parsed = urlparse(url.strip().strip("<>"))
    return parsed._replace(scheme="http", netloc="172.17.0.1:8093").geturl(), True


def _extract_generated_image_media(content: str) -> tuple[str, list[str]]:
    """Turn Gemini image Markdown into QQ media refs and remove brittle public links."""
    urls: list[str] = []

    def add_url(url: str) -> None:
        clean = url.strip().strip("<>")
        if _is_gemini_image_url(clean) and clean not in urls:
            urls.append(clean)

    def remove_markdown(match: re.Match[str]) -> str:
        add_url(match.group("url"))
        return "\n"

    text = _GEMINI_IMAGE_MARKDOWN_RE.sub(remove_markdown, content or "")
    text = _GEMINI_IMAGE_LINK_RE.sub(remove_markdown, text)

    lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if _is_gemini_image_url(line):
            add_url(line)
            continue
        lines.append(raw_line)

    cleaned = "\n".join(lines).strip()
    if urls:
        cleaned = re.sub(r"(?i)^image generated\.\s*", lambda _: _GENERATED_IMAGE_READY_TEXT, cleaned).strip()
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        if not cleaned:
            cleaned = _GENERATED_IMAGE_READY_TEXT
    return cleaned, urls


def _make_bot_class(channel: QQChannel) -> type[Any]:
    """Create a botpy Client subclass bound to the given channel."""
    botpy_sdk = cast(Any, botpy)
    intents = botpy_sdk.Intents(public_messages=True, direct_message=True)

    class _Bot(botpy_sdk.Client):
        def __init__(self):
            # Disable botpy's file log — nanobot uses loguru; default "botpy.log" fails on read-only fs
            super().__init__(  # pyright: ignore[reportUnknownMemberType]
                intents=intents,
                ext_handlers=False,
            )
            self._ws_backoff: dict[int, int] = {}
            self._ws_retry_at: dict[int, float] = {}

        async def bot_connect(self, session: object) -> None:
            """Connect one gateway session with per-session exponential backoff."""
            session_id = id(session)
            retry_at = self._ws_retry_at.pop(session_id, None)
            if retry_at is not None:
                remaining = retry_at - time.monotonic()
                if remaining > 0:
                    await asyncio.sleep(remaining)

            websocket_class = cast(Any, BotWebSocket)
            client = websocket_class(session, self._connection)
            backoff = self._ws_backoff.get(session_id, _RECONNECT_BACKOFF_START)
            try:
                await client.ws_connect()
                self._ws_backoff.pop(session_id, None)
            except (Exception, KeyboardInterrupt, SystemExit) as exc:
                if _is_network_error(exc):
                    channel.logger.warning(
                        "QQ bot network error (retry in {}s): {}",
                        backoff,
                        exc,
                    )
                    self._ws_retry_at[session_id] = time.monotonic() + backoff
                    self._ws_backoff[session_id] = min(
                        backoff * 2,
                        _RECONNECT_BACKOFF_MAX,
                    )
                else:
                    channel.logger.exception("QQ bot WebSocket error: {}", exc)
                self._connection.add(session)

        async def on_ready(self):
            logger.info("QQ bot ready: {}", self.robot.name)
            await channel._check_greeting_trigger()

        async def on_c2c_message_create(self, message: object) -> None:
            await channel._on_message(message, is_group=False)

        async def on_group_at_message_create(self, message: object) -> None:
            await channel._on_message(message, is_group=True)

    return _Bot


# QQ's C2C/group events do not carry ``message_reference``; botpy models that
# field because the object is shared with guild messages, but QQ never sends it
# here.  The quoted original arrives in ``msg_elements``, linked from
# ``message_scene.ext`` by ``ref_msg_idx``.  botpy parses neither field, and
# ``BaseMessage.__slots__`` drops the raw payload, so
# ``_install_qq_payload_capture`` keeps the payload from the constructor before
# it is discarded.  If a future botpy exposes those fields on the message
# object, ``_quoted_content_for`` prefers that copy and the hook becomes dead
# weight rather than a correctness dependency.

QQ_QUOTED_CONTEXT_MAX_CHARS = 4_000
QQ_RAW_PAYLOAD_CACHE = 200

_qq_raw_payloads: dict[str, dict[str, Any]] = {}


def _flatten_scene_ext(scene: Any) -> dict[str, str]:
    if not isinstance(scene, Mapping):
        return {}
    ext = cast("Mapping[str, Any]", scene).get("ext")
    if not isinstance(ext, list):
        return {}
    flattened: dict[str, str] = {}
    for item in cast("list[Any]", ext):
        if isinstance(item, str) and "=" in item:
            key, _, value = item.partition("=")
            flattened[key] = value
    return flattened


def extract_quoted_content(raw: Mapping[str, Any] | None) -> str | None:
    """Return the text of the message the sender quoted, if any.

    QQ points at the quoted message from ``message_scene.ext``: ``ref_msg_idx=X``
    matches the ``msg_elements`` entry whose ``msg_idx`` is ``X``, and that
    entry's ``content`` is the original text.  Matching on the index instead of
    taking the first element keeps this correct if QQ ever sends more than one.
    """
    if not isinstance(raw, Mapping):
        return None

    ref_idx = _flatten_scene_ext(raw.get("message_scene")).get("ref_msg_idx")
    if not ref_idx:
        return None

    elements = raw.get("msg_elements")
    if not isinstance(elements, list):
        return None

    for element in cast("list[Any]", elements):
        if not isinstance(element, Mapping):
            continue
        entry = cast("Mapping[str, Any]", element)
        if entry.get("msg_idx") != ref_idx:
            continue
        text = entry.get("content")
        if not isinstance(text, str) or not text.strip():
            return None
        text = text.strip()
        if len(text) > QQ_QUOTED_CONTEXT_MAX_CHARS:
            text = text[:QQ_QUOTED_CONTEXT_MAX_CHARS] + "..."
        return text
    return None


def _install_qq_payload_capture() -> None:
    """Keep raw QQ payloads that botpy would otherwise discard (idempotent)."""
    if not QQ_AVAILABLE:
        return
    try:
        from botpy import message as botpy_message

        for message_cls in (botpy_message.C2CMessage, botpy_message.GroupMessage):
            original_init = cast("Callable[..., Any]", message_cls.__init__)
            if getattr(original_init, "_nanobot_qq_capture", False):
                continue

            def _capture(
                self: Any,
                api: Any,
                event_id: Any,
                data: Any,
                _original: Callable[..., Any] = original_init,
            ) -> Any:
                if isinstance(data, Mapping):
                    payload = cast("Mapping[str, Any]", data)
                    message_id = payload.get("id")
                    if isinstance(message_id, str):
                        _qq_raw_payloads[message_id] = dict(payload)
                        while len(_qq_raw_payloads) > QQ_RAW_PAYLOAD_CACHE:
                            _qq_raw_payloads.pop(next(iter(_qq_raw_payloads)))
                return _original(self, api, event_id, data)

            setattr(_capture, "_nanobot_qq_capture", True)
            setattr(message_cls, "__init__", _capture)
    except Exception:  # pragma: no cover - optional dependency shape may vary
        logger.debug("QQ quoted-message payload capture unavailable")


def _quoted_content_for(message: Any) -> str | None:
    scene = getattr(message, "message_scene", None)
    elements = getattr(message, "msg_elements", None)
    if scene is not None or elements is not None:
        return extract_quoted_content({"message_scene": scene, "msg_elements": elements})
    return extract_quoted_content(_qq_raw_payloads.get(str(getattr(message, "id", ""))))


class QQConfig(Base):
    """QQ channel configuration using botpy SDK."""

    enabled: bool = False
    app_id: str = ""
    secret: str = ""
    allow_from: list[str] = Field(default_factory=list)
    msg_format: Literal["plain", "markdown"] = "plain"

    # Optional: directory to save inbound attachments. If empty, use nanobot get_media_dir("qq").
    media_dir: str = ""

    download_chunk_size: int = 1024 * 256
    download_max_bytes: int = 1024 * 1024 * 200

    # QQ's C2C/group message API has no edit or recall endpoint, so automatic
    # notices would land as separate permanent messages (#5784). Unset inherits
    # the global policy (off by default); explicit legacy true/false still override it.
    show_compaction_notices: bool | None = None

    # QQ can truncate/deny oversized text payloads. Split long replies into chunks.
    text_chunk_max_len: int = 1200

    # Optional immediate acknowledgement for inbound messages. Empty disables it.
    ack_message: str = ""

    # Signature validation alert reporting
    signature_alert_enabled: bool = True
    signature_alert_chat_id: str = ""

    # botpy logs timeout and returns None instead of raising; these knobs let us
    # retry passive replies with the same msg_seq while avoiding duplicate cron pushes.
    botpy_http_timeout_sec: float = 5.0
    send_retry_on_empty_response: bool = False
    send_retry_attempts: int = 1
    send_retry_delay_sec: float = 0.8

    # QQ officially accepts a stream payload on markdown messages even though
    # public docs lag behind. Keep it opt-in and limited to passive replies so
    # cron/RSS pushes keep the older one-shot path.
    stream_enabled: bool = False
    stream_requires_msg_id: bool = True
    stream_min_chars: int = 1
    stream_max_chars: int = 5000
    stream_chunk_chars: int = 180
    stream_interval_sec: float = 0.0
    stream_first_flush_chars: int = 2
    stream_defer_first_frame_until_end: bool = False
    stream_delta_flush_chars: int = 120
    stream_delta_flush_interval_sec: float = 0.35

    # TTS (Text-to-Speech) via MiMo API
    tts_enabled: bool = True
    tts_voice: str = "茉莉"
    tts_timeout_sec: int = 120
    tts_max_chars: int = 1500
    tts_api_url: str = 'https://api.xiaomimimo.com/v1/chat/completions'



def _elapsed_perf_ms(start: Any, end: float) -> int:
    try:
        value = float(start)
    except (TypeError, ValueError):
        return 0
    if value <= 0:
        return 0
    return max(0, int((end - value) * 1000))

class QQChannel(BaseChannel):
    """QQ channel using botpy SDK with WebSocket connection."""

    name = "qq"
    display_name = "QQ"

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return QQConfig().model_dump(by_alias=True, exclude_none=True)

    @property
    def supports_streaming(self) -> bool:
        return qq_streaming.supports_streaming(self.config)
    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = QQConfig.model_validate(config)
        super().__init__(config, bus)
        self.config: QQConfig = config
        # Preserve explicitly configured notices for standalone channel callers.
        # ChannelManager resolves global inheritance from the original section.
        self.show_compaction_notices = bool(config.show_compaction_notices)

        self._client: Any | None = None
        self._http: aiohttp.ClientSession | None = None

        self._processed_ids: deque[str] = deque(maxlen=1000)
        self._msg_seq: int = 1  # used to avoid QQ API dedup
        self._chat_type_cache: dict[str, str] = {}
        self._stream_states: dict[str, dict[str, Any]] = {}
        self._sent_generated_image_urls: deque[str] = deque(maxlen=100)
        # Set only while the current inbound turn explicitly asks for an image.
        self._generated_image_delivery_allowed: dict[str, bool] = {}
        self._tts_enabled: dict[str, bool] = {}
        self._tts_accumulated: dict[str, str] = {}

        _install_qq_payload_capture()

        self._media_root: Path = self._init_media_root()


    def _init_media_root(self) -> Path:
        if self.config.media_dir:
            root = Path(self.config.media_dir).expanduser()
        elif get_media_dir:
            try:
                root = Path(get_media_dir("qq"))
            except Exception:
                root = Path.home() / ".nanobot" / "media" / "qq"
        else:
            root = Path.home() / ".nanobot" / "media" / "qq"

        root.mkdir(parents=True, exist_ok=True)
        logger.info("QQ media directory: {}", str(root))
        return root

    async def login(self, force: bool = False) -> bool:
        """Scan a QQ Bot QR code and save the AppID/secret it returns."""
        from nanobot.channels.qq.connect import QQConnectStore

        if not force and self.config.app_id and self.config.secret:
            return True
        credentials = await QQConnectStore().login()
        if credentials is None:
            return False
        self.config.app_id, self.config.secret = credentials
        return True

    async def start(self) -> None:
        """Start the QQ bot with auto-reconnect loop."""
        if not QQ_AVAILABLE:
            logger.error("QQ SDK not installed. Run: pip install qq-botpy")
            return

        if not self.config.app_id or not self.config.secret:
            logger.error("QQ app_id and secret not configured")
            return

        self._running = True
        self._http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120))

        self._client = _make_bot_class(self)()
        logger.info("QQ bot started (C2C & Group supported)")
        await self._run_bot()

    async def _run_bot(self) -> None:
        backoff = 5
        max_backoff = 300
        while self._running:
            try:
                client = cast(Any, self._client)
                await client.start(appid=self.config.app_id, secret=self.config.secret)
                backoff = 5
            except Exception as e:
                if _is_network_error(e):
                    logger.warning("QQ bot network error (retry in {}s): {}", backoff, e)
                else:
                    logger.warning("QQ bot error: {}", e)
            if self._running:
                logger.info("Reconnecting QQ bot in {} seconds...", backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)

    async def _check_greeting_trigger(self) -> None:
        """Check for gateway restart greeting trigger and send a greeting."""
        flag_file = qq_gateway_greeting.DEFAULT_RESTART_FLAG_PATH
        logger.debug("check_greeting: flag exists={}", flag_file.exists())
        content = qq_gateway_greeting.build_restart_greeting(flag_path=flag_file)
        if not content:
            return
        logger.info("check_greeting: sending greeting '{}'", content)
        await self.bus.publish_outbound(
            OutboundMessage(
                channel="qq",
                chat_id="965E0CA5AB52FBFC537A2E68A7349B9E",
                content=content,
            )
        )

    async def _run_sidecar_json(self, args: list[str], timeout_sec: float = 30.0) -> dict[str, Any] | None:
        return await qq_article_runtime.run_sidecar_json(
            self._http,
            args,
            timeout_sec=timeout_sec,
            logger=logger,
        )

    async def _run_yage_signed(
        self,
        timeout_sec: float = 45.0,
        *,
        nth: int | None = None,
        target_date: str | None = None,
        force_latest: bool = False,
    ) -> str | None:
        """Run yage checker with selector and return raw stdout."""
        return await qq_article_runtime.run_yage_signed(
            self._http,
            timeout_sec=timeout_sec,
            nth=nth,
            target_date=target_date,
            force_latest=force_latest,
            logger=logger,
        )

    async def _run_wechat_signed(
        self,
        subscription_id: int,
        timeout_sec: float = 45.0,
        *,
        force: bool = True,
    ) -> str | None:
        """Run wechat_push script and return raw stdout."""
        return await qq_article_runtime.run_wechat_signed(
            self._http,
            subscription_id,
            timeout_sec=timeout_sec,
            force=force,
            logger=logger,
        )

    async def _try_handle_yage_raw(
        self,
        chat_id: str,
        content: str,
        message_id: str | None,
    ) -> bool:
        return await qq_article_handlers.try_handle_yage_raw(
            chat_id=chat_id,
            content=content,
            message_id=message_id,
            run_yage_signed=self._run_yage_signed,
            publish_outbound=self.bus.publish_outbound,
            logger=logger,
        )

    async def _try_handle_wechat_grounded(self, user_id: str, chat_id: str, content: str, message_id: str) -> bool:
        return await qq_article_handlers.try_handle_wechat_grounded(
            user_id=user_id,
            chat_id=chat_id,
            content=content,
            message_id=message_id,
            is_allowed=self.is_allowed,
            run_sidecar_json=self._run_sidecar_json,
            publish_outbound=self.bus.publish_outbound,
        )

    async def stop(self) -> None:
        """Stop bot and cleanup resources."""
        self._running = False
        if self._client:
            try:
                await self._client.close()
            except Exception:
                pass
        self._client = None

        if self._http:
            try:
                await self._http.close()
            except Exception:
                pass
        self._http = None

        logger.info("QQ bot stopped")



    async def send(self, msg: OutboundMessage) -> None:
        """Send attachments first, then text."""
        # QQ has no edit or recall endpoint for automatic compaction notices;
        # explicit /compact feedback remains available.
        if (
            isinstance(msg.event, ContextCompactionEvent)
            and not (msg.event.notify or self.show_compaction_notices)
        ):
            return

        send_started = time.perf_counter()
        trace_id = str(msg.metadata.get("_trace_id") or msg.metadata.get("_turn_id") or "")
        queue_wait_ms = _elapsed_perf_ms(msg.metadata.get("_send_queued_perf"), send_started)
        status = "ok"
        content = _unwrap_text_envelope(msg.content or "")
        logger.info("🔍 SEND called content_len={} chat_id={} tts_enabled={}",
                     len(content), msg.chat_id, self._tts_enabled.get(msg.chat_id, True))
        auto_media: list[str] = []
        allow_generated_images = self._generated_image_delivery_allowed.get(msg.chat_id, False)
        if content.strip():
            content, detected_media = _extract_generated_image_media(content)
            if detected_media and not allow_generated_images:
                logger.warning("QQ generated image suppressed for non-image turn chat_id={} urls={}", msg.chat_id, len(detected_media))
            auto_media = detected_media if allow_generated_images else []
        auto_media = [url for url in auto_media if url not in self._sent_generated_image_urls]
        media_refs = [*(msg.media or []), *auto_media]

        mode = "media_only" if media_refs else "empty"
        reason = ""
        media_sent = 0
        chunks_sent = 0

        try:
            if not self._client:
                raise ChannelNotReadyError("QQ client not initialized")

            msg_id = msg.metadata.get("message_id")
            chat_type = self._chat_type_cache.get(msg.chat_id, "c2c")
            is_group = chat_type == "group"

            # 1) Send media
            for media_ref in media_refs:
                ok = await self._send_media(
                    chat_id=msg.chat_id,
                    media_ref=media_ref,
                    msg_id=msg_id,
                    is_group=is_group,
                )
                if ok:
                    media_sent += 1
                    if media_ref in auto_media:
                        self._sent_generated_image_urls.append(media_ref)
                    continue
                filename = (
                    os.path.basename(urlparse(media_ref).path)
                    or os.path.basename(media_ref)
                    or "file"
                )
                await self._send_text_only(
                    chat_id=msg.chat_id,
                    is_group=is_group,
                    msg_id=msg_id,
                    content=f"[Attachment send failed: {filename}]",
                )
                chunks_sent += 1

            # 2) Send text (chunked to avoid QQ-side truncation on long payloads)
            if content and content.strip():
                prepared = await qq_signed_delivery.prepare_outbound_content(
                    content,
                    session=self._http,
                    run_wechat_signed=self._run_wechat_signed,
                    run_yage_signed=self._run_yage_signed,
                    chat_id=msg.chat_id,
                    logger=logger,
                )
                if prepared.suppressed:
                    status = "suppressed"
                    reason = str(prepared.reason or "")
                    logger.info("QQ outbound suppressed reason={} chat_id={}", prepared.reason, msg.chat_id)
                    return
                if prepared.blocked:
                    status = "blocked"
                    reason = str(prepared.reason or "")
                    logger.warning(
                        "QQ outbound blocked reason={} chat_id={}",
                        prepared.reason,
                        msg.chat_id,
                    )
                    await self._report_signature_blocked(
                        source_chat_id=msg.chat_id,
                        source_is_group=is_group,
                        source_msg_id=msg_id,
                    )
                    chunks_sent += 1
                    return

                safe_content = prepared.content
                is_signed_payload = prepared.is_signed_payload
                wechat_ack = prepared.wechat_ack

                if is_signed_payload:
                    # Prefer one-shot delivery for raw signed articles.
                    # Only fallback to splitting when QQ rejects oversize payload.
                    try:
                        mode = "signed_one_shot"
                        await self._send_text_only(
                            chat_id=msg.chat_id,
                            is_group=is_group,
                            msg_id=msg_id,
                            content=safe_content,
                        )
                        chunks_sent += 1
                        self._schedule_delivery_ack(safe_content, wechat_ack, chat_id=msg.chat_id)
                        return
                    except Exception as e:
                        logger.warning(
                            "QQ signed payload one-shot send failed, fallback to chunking chat_id={} err={}",
                            msg.chat_id,
                            e,
                        )

                if self._should_stream_text(
                    msg_id=msg_id,
                    is_signed_payload=is_signed_payload,
                    content=safe_content,
                ):
                    try:
                        mode = "streaming"
                        await self._send_text_streaming(
                            chat_id=msg.chat_id,
                            is_group=is_group,
                            msg_id=msg_id,
                            content=safe_content,
                        )
                        chunks_sent += 1
                        logger.info("📢 TTS CHECK chat_id={} enabled={}",
                                     msg.chat_id, self._tts_enabled.get(msg.chat_id, True))
                        if (
                            self._tts_enabled.get(msg.chat_id, True)
                            and not _is_obvious_error_reply(safe_content)
                        ):
                            await self._send_tts_audio(
                                chat_id=msg.chat_id, is_group=is_group, msg_id=msg_id, text=safe_content,
                            )
                        return
                    except Exception as e:
                        logger.warning(
                            "QQ stream send failed, fallback to normal chunking chat_id={} err={}",
                            msg.chat_id,
                            e,
                        )

                mode = "chunked"
                max_len = max(200, int(getattr(self.config, "text_chunk_max_len", 1200) or 1200))
                for chunk in split_message(safe_content, max_len):
                    if not chunk:
                        continue
                    try:
                        await self._send_text_only(
                            chat_id=msg.chat_id,
                            is_group=is_group,
                            msg_id=msg_id,
                            content=chunk,
                        )
                        chunks_sent += 1
                    except Exception as e:
                        status = "failed"
                        reason = "text_send_failed"
                        logger.error("QQ text send failed chat_id={} err={}", msg.chat_id, e)
                        return
                if is_signed_payload:
                    self._schedule_delivery_ack(safe_content, wechat_ack, chat_id=msg.chat_id)

            # 3) TTS: if enabled for this user, generate audio and send
            if (
                content
                and content.strip()
                and self._tts_enabled.get(msg.chat_id, True)
                and not _is_obvious_error_reply(content)
            ):
                try:
                    await self._send_tts_audio(
                        chat_id=msg.chat_id, is_group=is_group, msg_id=msg_id, text=content,
                    )
                except Exception as e:
                    logger.warning("QQ TTS send failed chat_id={} err={}", msg.chat_id, e)
        finally:
            # Never let an explicit image request authorize a later chat turn.
            self._generated_image_delivery_allowed.pop(msg.chat_id, None)
            finished_at = time.perf_counter()
            turn_done_ms = _elapsed_perf_ms(msg.metadata.get("_turn_started_perf"), finished_at)
            logger.info(
                "QQ outbound send finished trace_id={} chat_id={} status={} mode={} total_ms={} queue_wait_ms={} turn_to_send_done_ms={} media={} chunks={} reason={}",
                trace_id or "-",
                msg.chat_id,
                status,
                mode,
                int((finished_at - send_started) * 1000),
                queue_wait_ms,
                turn_done_ms,
                media_sent,
                chunks_sent,
                reason or "-",
            )

    async def _report_signature_blocked(
        self,
        source_chat_id: str,
        source_is_group: bool,
        source_msg_id: str | None,
    ) -> None:
        """Send anti-tamper alert to source chat and optional alert chat."""
        if not getattr(self.config, "signature_alert_enabled", True):
            return

        content = (
            "[ALERT] 内容签名校验失败，消息已被拦截未发送。\n"
            "可能原因：输出被改写、拼接或截断。\n"
            "请检查对应脚本输出是否为 NBRAW1-SHA256 签名格式。"
        )
        await self._send_text_only(
            chat_id=source_chat_id,
            is_group=source_is_group,
            msg_id=source_msg_id,
            content=content,
        )

        alert_chat_id = (getattr(self.config, "signature_alert_chat_id", "") or "").strip()
        if not alert_chat_id or alert_chat_id == source_chat_id:
            return

        alert_is_group = self._chat_type_cache.get(alert_chat_id, "c2c") == "group"
        await self._send_text_only(
            chat_id=alert_chat_id,
            is_group=alert_is_group,
            msg_id=None,
            content=f"{content}\nsource_chat_id: {source_chat_id}",
        )

    async def _send_text_only(
        self,
        chat_id: str,
        is_group: bool,
        msg_id: str | None,
        content: str,
    ) -> None:
        if not self._client:
            return
        content = _strip_silent_marker(content)
        if not content:
            return

        self._msg_seq += 1
        use_markdown = self.config.msg_format == "markdown"
        payload: dict[str, Any] = {
            "msg_type": 2 if use_markdown else 0,
            "msg_id": msg_id,
            "msg_seq": self._msg_seq,
        }
        if use_markdown:
            payload["markdown"] = {"content": content}
        else:
            payload["content"] = content

        await self._post_text_payload(
            chat_id=chat_id,
            is_group=is_group,
            msg_id=msg_id,
            payload=payload,
        )

    def _schedule_delivery_ack(
        self,
        signed_payload: str,
        wechat_ack: tuple[int, int] | None,
        *,
        chat_id: str,
    ) -> None:
        if not wechat_ack:
            return

        async def _run() -> None:
            try:
                await qq_signed_delivery.ack_delivery(
                    self._http,
                    signed_payload,
                    wechat_ack,
                    chat_id=chat_id,
                    logger=logger,
                )
            except Exception as exc:
                logger.warning("QQ signed delivery ack failed chat_id={} err={}", chat_id, exc)

        coro = _run()
        try:
            asyncio.create_task(coro)
        except RuntimeError:
            coro.close()
            logger.debug("QQ signed delivery ack skipped: no running event loop chat_id={}", chat_id)

    def _should_stream_text(
        self,
        *,
        msg_id: str | None,
        is_signed_payload: bool,
        content: str,
    ) -> bool:
        return qq_streaming.should_stream_text(
            self.config,
            msg_id=msg_id,
            is_signed_payload=is_signed_payload,
            content=content,
        )
    def _stream_delta_flush_policy(self, *, first_frame_sent: bool) -> tuple[int, float]:
        return qq_streaming.delta_flush_policy(self.config, first_frame_sent=first_frame_sent)
    def _split_stream_chunks(self, text: str) -> list[str]:
        return qq_streaming.split_stream_chunks(self.config, text)
    async def _send_stream_frame(
        self,
        *,
        chat_id: str,
        is_group: bool,
        msg_id: str | None,
        content: str,
        state: int,
        index: int,
        reset: bool,
        stream_id: str | None = None,
    ) -> str | None:
        self._msg_seq += 1
        stream_meta: dict[str, Any] = {
            "state": state,
            "index": index,
            "reset": reset,
        }
        if stream_id:
            stream_meta["id"] = stream_id
        payload: dict[str, Any] = {
            "msg_type": 2,
            "msg_id": msg_id,
            "msg_seq": self._msg_seq,
            "markdown": {"content": content},
            "stream": stream_meta,
        }
        result = await self._post_stream_payload(
            chat_id=chat_id,
            is_group=is_group,
            payload=payload,
        )
        if isinstance(result, dict):
            result_data = cast(dict[str, Any], result)
            if result_data.get("id"):
                return str(result_data["id"])
        return None

    async def send_delta(
        self,
        chat_id: str,
        delta: str,
        metadata: dict[str, Any] | None = None,
        *,
        stream_id: str | None = None,
        stream_end: bool = False,
        resuming: bool = False,
        merge_next: bool = False,
    ) -> None:
        # Translate the upstream channel contract into the existing QQ state
        # machine without mutating the manager-owned metadata dictionary.
        metadata = dict(metadata or {})
        if stream_id is not None:
            metadata['_stream_id'] = stream_id
        if stream_end:
            metadata['_stream_end'] = True
        if resuming:
            metadata['_resuming'] = True
        if merge_next:
            metadata['_merge_next'] = True

        allow_generated_images = self._generated_image_delivery_allowed.get(chat_id, False)
        content, detected_media = _extract_generated_image_media(delta or "")
        if detected_media and not allow_generated_images:
            logger.warning("QQ streamed generated image suppressed for non-image turn chat_id={} urls={}", chat_id, len(detected_media))
        auto_media = detected_media if allow_generated_images else []
        if auto_media:
            auto_media = [url for url in auto_media if url not in self._sent_generated_image_urls]
            if not auto_media:
                return
            msg_id = (metadata or {}).get("message_id")
            is_group = self._chat_type_cache.get(chat_id, "c2c") == "group"
            for media_ref in auto_media:
                ok = await self._send_media(
                    chat_id=chat_id,
                    media_ref=media_ref,
                    msg_id=msg_id,
                    is_group=is_group,
                )
                if ok:
                    self._sent_generated_image_urls.append(media_ref)
                    continue
                filename = (
                    os.path.basename(urlparse(media_ref).path)
                    or os.path.basename(media_ref)
                    or "file"
                )
                await self._send_text_only(
                    chat_id=chat_id,
                    is_group=is_group,
                    msg_id=msg_id,
                    content=f"[Attachment send failed: {filename}]",
                )
            if content.strip():
                await self._send_text_only(
                    chat_id=chat_id,
                    is_group=is_group,
                    msg_id=msg_id,
                    content=content,
                )
            return

        if detected_media:
            # The image markdown/link was removed above; keep only safe text.
            if not content.strip():
                return
            delta = content

        await qq_stream_runtime.send_delta(
            config=self.config,
            stream_states=self._stream_states,
            chat_type_cache=self._chat_type_cache,
            send_stream_frame=self._send_stream_frame,
            send_text_only=self._send_text_only,
            chat_id=chat_id,
            delta=delta,
            metadata=metadata,
            logger=logger,
        )

        # TTS: accumulate streamed content, trigger on stream end
        if self._tts_enabled.get(chat_id, True):
            meta = metadata or {}
            stream_key = str(meta.get("_stream_id") or chat_id)
            if delta:
                self._tts_accumulated[stream_key] = (self._tts_accumulated.get(stream_key) or "") + delta
            if meta.get("_stream_end"):
                full_text = (self._tts_accumulated.pop(stream_key, None) or "").strip()
                if full_text and not _is_obvious_error_reply(full_text):
                    is_group = self._chat_type_cache.get(str(chat_id), "c2c") == "group"
                    msg_id = meta.get("message_id") or meta.get("msg_id")
                    msg_id = str(msg_id) if msg_id else None
                    _ = asyncio.create_task(self._send_tts_audio(
                        chat_id=chat_id, is_group=is_group, msg_id=msg_id, text=full_text,
                    ))

    async def _send_text_streaming(
        self,
        chat_id: str,
        is_group: bool,
        msg_id: str | None,
        content: str,
    ) -> None:
        """Send a markdown message through QQ's streaming payload."""
        if not self._client:
            return
        await qq_stream_runtime.send_text_streaming(
            config=self.config,
            send_stream_frame=self._send_stream_frame,
            chat_id=chat_id,
            is_group=is_group,
            msg_id=msg_id,
            content=content,
            logger=logger,
        )

    async def _post_stream_payload(
        self,
        chat_id: str,
        is_group: bool,
        payload: dict[str, Any],
    ) -> Any | None:
        """Post QQ stream payload through raw botpy HTTP to avoid SDK kwarg filtering."""
        self._apply_botpy_http_timeout()
        client = cast(Any, self._client)
        if not client or not getattr(client.api, "_http", None) or Route is None:
            raise RuntimeError("QQ raw HTTP client is not available for streaming")

        if is_group:
            endpoint = "/v2/groups/{group_openid}/messages"
            id_key = "group_openid"
        else:
            endpoint = "/v2/users/{openid}/messages"
            id_key = "openid"

        route_class = cast(Any, Route)
        route = route_class("POST", endpoint, **{id_key: chat_id})
        return await client.api._http.request(route, json=payload)

    def _apply_botpy_http_timeout(self) -> None:
        """Keep botpy sends from hanging longer than our QQ channel budget."""
        timeout = float(getattr(self.config, "botpy_http_timeout_sec", 0) or 0)
        if not self._client or timeout <= 0:
            return
        try:
            api = getattr(self._client, "api", None)
            http = getattr(api, "_http", None)
            if http is not None:
                http.timeout = timeout
        except Exception as e:  # pragma: no cover - defensive only
            logger.debug("QQ botpy timeout tune skipped: {}", e)

    async def _post_text_payload(
        self,
        chat_id: str,
        is_group: bool,
        msg_id: str | None,
        payload: dict[str, Any],
    ) -> Any | None:
        """Post text through botpy, retrying passive replies when botpy reports no response."""
        self._apply_botpy_http_timeout()
        can_retry = bool(msg_id) and bool(getattr(self.config, "send_retry_on_empty_response", False))
        retry_attempts = int(getattr(self.config, "send_retry_attempts", 0) or 0)
        attempts = 1 + max(0, retry_attempts if can_retry else 0)
        delay = max(0.0, float(getattr(self.config, "send_retry_delay_sec", 0.0) or 0.0))

        client = cast(Any, self._client)
        for attempt in range(1, attempts + 1):
            try:
                if is_group:
                    result = await client.api.post_group_message(group_openid=chat_id, **payload)
                else:
                    result = await client.api.post_c2c_message(openid=chat_id, **payload)
                if can_retry and result is None:
                    raise asyncio.TimeoutError("QQ API returned no response")
                return result
            except (asyncio.TimeoutError, aiohttp.ClientError, OSError) as e:
                if attempt >= attempts:
                    logger.warning(
                        "QQ text send failed after {} attempt(s) chat_id={} msg_seq={} err={}",
                        attempts,
                        chat_id,
                        payload.get("msg_seq"),
                        e,
                    )
                    raise
                logger.warning(
                    "QQ text send attempt {}/{} failed chat_id={} msg_seq={} err={}; retrying same msg_seq",
                    attempt,
                    attempts,
                    chat_id,
                    payload.get("msg_seq"),
                    e,
                )
                if delay:
                    await asyncio.sleep(delay)

    async def _send_media(
        self,
        chat_id: str,
        media_ref: str,
        msg_id: str | None,
        is_group: bool,
    ) -> bool:
        if not self._client:
            return False

        data, filename = await self._read_media_bytes(media_ref)
        if not data or not filename:
            return False

        try:
            file_type = _guess_send_file_type(filename)
            file_data_b64 = base64.b64encode(data).decode()

            media_obj = await self._post_base64file(
                chat_id=chat_id,
                is_group=is_group,
                file_type=file_type,
                file_data=file_data_b64,
                file_name=filename,
                srv_send_msg=False,
            )
            if not media_obj:
                logger.error("QQ media upload failed: empty response")
                return False

            self._msg_seq += 1
            if is_group:
                await self._client.api.post_group_message(
                    group_openid=chat_id,
                    msg_type=7,
                    msg_id=msg_id,
                    msg_seq=self._msg_seq,
                    media=media_obj,
                )
            else:
                await self._client.api.post_c2c_message(
                    openid=chat_id,
                    msg_type=7,
                    msg_id=msg_id,
                    msg_seq=self._msg_seq,
                    media=media_obj,
                )

            logger.info("QQ media sent: {}", filename)
            return True
        except (aiohttp.ClientError, OSError) as e:
            logger.error("QQ send media network failed filename={} err={}", filename, e)
            raise
        except Exception as e:
            logger.error("QQ send media failed filename={} err={}", filename, e)
            return False

    async def _send_tts_audio(
        self,
        chat_id: str,
        is_group: bool,
        msg_id: str | None,
        text: str,
    ) -> bool:
        """Generate TTS audio(s) from text, split into sentence chunks if needed."""
        logger.info("TTS starting chat_id={} text_len={}", chat_id, len(text or ""))
        if not text or not text.strip():
            return False
        api_key = os.environ.get("MIMO_API_KEY", "")
        if not api_key:
            logger.error("TTS failed: MIMO_API_KEY not set")
            return False
        http = cast(aiohttp.ClientSession, self._http)
        client = cast(Any, self._client)

        # Split text at sentence boundaries
        raw_text = text.strip()
        sentences = re.split(r'(?<=[。！？\n])', raw_text)
        sentences = [s.strip() for s in sentences if s.strip()]
        if not sentences:
            sentences = [raw_text[:500]]

        chunks: list[str] = []
        cur = ""
        mc = 1500
        for s in sentences:
            if len(s) > mc:
                if cur:
                    chunks.append(cur)
                    cur = ""
                for i in range(0, len(s), mc):
                    chunks.append(s[i:i+mc])
            elif len(cur) + len(s) <= mc:
                cur += s
            else:
                chunks.append(cur)
                cur = s
        if cur:
            chunks.append(cur)

        if len(chunks) > 3:
            chunks = chunks[:3]
        if len(chunks) > 1:
            logger.info("TTS split into {} chunks", len(chunks))
        logger.info("TTS chunks={}", len(chunks))

        async def _send_one(chunk_text: str, idx: int) -> bool:
            logger.info("TTS chunk[{}]: {} chars", idx, len(chunk_text))
            async with http.post(
                self.config.tts_api_url,
                json={"model": "mimo-v2.5-tts", "messages": [{"role": "user", "content": "用温暖亲切的中文女性声音朗读"}, {"role": "assistant", "content": chunk_text}], "audio": {"format": "mp3", "voice": self.config.tts_voice}, "stream": False},
                headers={"api-key": api_key},
                timeout=aiohttp.ClientTimeout(total=120),
            ) as resp:
                if resp.status != 200:
                    logger.error("TTS chunk[{}] API error: {}", idx, resp.status)
                    return False
                d = await resp.json()
                audio_b64 = d.get("choices", [{}])[0].get("message", {}).get("audio", {}).get("data", "")
            if not audio_b64:
                return False

            media_obj = await self._post_base64file(
                chat_id=chat_id, is_group=is_group,
                file_type=4, file_data=audio_b64,
                file_name=f"voice_{idx}.mp3", srv_send_msg=False,
            )
            seq = self._msg_seq + idx
            if is_group:
                await client.api.post_group_message(group_openid=chat_id, msg_type=7, msg_id=msg_id, msg_seq=seq, media=media_obj)
            else:
                await client.api.post_c2c_message(openid=chat_id, msg_type=7, msg_id=msg_id, msg_seq=seq, media=media_obj)
            logger.info("TTS chunk[{}] sent ({} chars)", idx, len(chunk_text))
            return True

        results = await asyncio.gather(*[_send_one(c, i) for i, c in enumerate(chunks)], return_exceptions=True)
        ok = sum(1 for r in results if r is True)
        logger.info("TTS done: {}/{} chat_id={}", ok, len(chunks), chat_id)
        return ok > 0

    async def _read_media_bytes(self, media_ref: str) -> tuple[bytes | None, str | None]:
        media_ref = (media_ref or "").strip()
        if not media_ref:
            return None, None

        if not media_ref.startswith("http://") and not media_ref.startswith("https://"):
            try:
                if media_ref.startswith("file://"):
                    parsed = urlparse(media_ref)
                    # Windows: path in netloc; Unix: path in path
                    raw = parsed.path or parsed.netloc
                    local_path = Path(unquote(raw))
                else:
                    local_path = Path(os.path.expanduser(media_ref))

                if not local_path.is_file():
                    logger.warning("QQ outbound media file not found: {}", str(local_path))
                    return None, None

                data = await asyncio.to_thread(local_path.read_bytes)
                return data, local_path.name
            except Exception as e:
                logger.warning("QQ outbound media read error ref={} err={}", media_ref, e)
                return None, None

        # Remote URL. Trusted generated-image links are served by our local 8093 gateway;
        # rewrite them inside the container so QQ receives an uploaded image, not a dead link.
        fetch_ref, trusted_local = _gemini_image_fetch_url(media_ref)
        if not trusted_local:
            ok, err = validate_url_target(fetch_ref)
            if not ok:
                logger.warning("QQ outbound media URL validation failed url={} err={}", media_ref, err)
                return None, None

        if not self._http:
            self._http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120))
        try:
            async with self._http.get(fetch_ref, allow_redirects=True) as resp:
                if resp.status >= 400:
                    logger.warning(
                        "QQ outbound media download failed status={} url={}",
                        resp.status,
                        media_ref,
                    )
                    return None, None
                data = await resp.read()
                if not data:
                    return None, None
                filename = os.path.basename(urlparse(media_ref).path) or "file.bin"
                return data, filename
        except Exception as e:
            logger.warning("QQ outbound media download error url={} err={}", media_ref, e)
            return None, None

    # https://github.com/tencent-connect/botpy/issues/198
    # https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/send-receive/rich-media.html
    async def _post_base64file(
        self,
        chat_id: str,
        is_group: bool,
        file_type: int,
        file_data: str,
        file_name: str | None = None,
        srv_send_msg: bool = False,
    ) -> dict[str, Any]:
        if not self._client:
            raise RuntimeError("QQ client not initialized")

        if is_group:
            endpoint = "/v2/groups/{group_openid}/files"
            id_key = "group_openid"
        else:
            endpoint = "/v2/users/{openid}/files"
            id_key = "openid"

        payload = {
            id_key: chat_id,
            "file_type": file_type,
            "file_data": file_data,
            "srv_send_msg": srv_send_msg,
        }
        if file_type != QQ_FILE_TYPE_IMAGE and file_name:
            payload["file_name"] = file_name

        route_class = cast(Any, Route)
        route = route_class("POST", endpoint, **{id_key: chat_id})
        client = self._client
        result: object = await client.api._http.request(route, json=payload)
        if isinstance(result, dict) and "file_info" in result:
            result_data = cast(dict[str, Any], result)
            return {"file_info": result_data["file_info"]}
        return cast(dict[str, Any], result)


    async def _try_handle_personal_ops_query(
        self,
        *,
        chat_id: str,
        is_group: bool,
        message_id: str,
        content: str,
    ) -> bool:
        return await qq_local_handlers.try_handle_personal_ops_query(
            chat_id=chat_id,
            is_group=is_group,
            message_id=message_id,
            content=content,
            text_chunk_max_len=getattr(self.config, "text_chunk_max_len", 1200),
            send_text_only=self._send_text_only,
            logger=logger,
        )

    async def _try_handle_knowledge_inbox_query(
        self,
        *,
        chat_id: str,
        is_group: bool,
        message_id: str,
        content: str,
    ) -> bool:
        return await qq_local_handlers.try_handle_knowledge_inbox_query(
            chat_id=chat_id,
            is_group=is_group,
            message_id=message_id,
            content=content,
            text_chunk_max_len=getattr(self.config, "text_chunk_max_len", 1200),
            send_text_only=self._send_text_only,
            logger=logger,
        )


    # ---------------------------
    # Inbound (receive)
    # ---------------------------

    async def _on_message(self, data: object, is_group: bool = False) -> None:
        data = cast(Any, data)
        try:
            await self._process_inbound_message(data, is_group)
        except Exception:
            logger.exception("Error handling inbound message id={}", getattr(data, "id", "?"))

    async def _process_inbound_message(
        self,
        data: Any,
        is_group: bool = False,
    ) -> None:
        """Parse inbound message, download attachments, and publish to the bus."""
        if data.id in self._processed_ids:
            return
        self._processed_ids.append(data.id)

        author = getattr(data, "author", None)
        if is_group:
            chat_id = getattr(data, "group_openid", "")
            user_id = getattr(author, "member_openid", "unknown")
            if not chat_id:
                logger.warning(
                    "QQ group message missing group_openid message_id={}",
                    getattr(data, "id", "unknown"),
                )
                return
            self._chat_type_cache[chat_id] = "group"
        else:
            chat_id = str(getattr(author, "id", None) or getattr(author, "user_openid", "unknown"))
            user_id = chat_id
            self._chat_type_cache[chat_id] = "c2c"

        # Check access before acknowledgements or attachment downloads.
        if not self.is_allowed(user_id):
            logger.warning(
                "QQ access denied for sender {} chat_id={} message_id={}",
                user_id, chat_id, getattr(data, "id", "unknown"),
            )
            if not is_group:
                await self._handle_message(
                    sender_id=user_id,
                    chat_id=chat_id,
                    content="",
                    is_dm=True,
                )
            return
        user_content = (getattr(data, "content", "") or "").strip()
        content = user_content
        self._generated_image_delivery_allowed[chat_id] = _has_explicit_image_generation_request(user_content)
        quoted = _quoted_content_for(data)
        if quoted:
            quote_tag = f"[Reply to: {quoted}]"
            content = f"{quote_tag}\n{content}" if content else quote_tag

        ack_message = (getattr(self.config, "ack_message", "") or "").strip()
        if ack_message:
            try:
                await self._send_text_only(
                    chat_id=chat_id,
                    is_group=is_group,
                    msg_id=data.id,
                    content=ack_message,
                )
            except Exception as e:
                logger.warning("QQ ack send failed message_id={} err={}", data.id, e)

        # Handle voice-mode settings locally. They must never enter the LLM/tool path.
        if any(phrase in user_content for phrase in ("用语音回复", "语音回复我", "打开语音回复", "开启语音回复")):
            if not os.environ.get("MIMO_API_KEY", "").strip():
                self._tts_enabled[chat_id] = False
                await self._send_text_only(
                    chat_id=chat_id,
                    is_group=is_group,
                    msg_id=data.id,
                    content="语音回复暂不可用：服务器还没有配置语音服务密钥。",
                )
                logger.warning("QQ TTS enable requested but MIMO_API_KEY is not configured chat_id={}", chat_id)
                return
            self._tts_enabled[chat_id] = True
            await self._send_text_only(
                chat_id=chat_id, is_group=is_group, msg_id=data.id,
                content="已开启语音回复模式 🔊 之后我会把回复念给你听。",
            )
            logger.info("QQ TTS enabled for chat_id={}", chat_id)
            return
        if "退出语音" in user_content or "关闭语音" in user_content or "不要语音" in user_content:
            self._tts_enabled[chat_id] = False
            await self._send_text_only(
                chat_id=chat_id, is_group=is_group, msg_id=data.id,
                content="已关闭语音回复模式 ✅",
            )
            logger.info("QQ TTS disabled for chat_id={}", chat_id)
            return

        # the data used by tests don't contain attachments property
        # so we use getattr with a default of [] to avoid AttributeError in tests
        attachments = cast(list[object], getattr(data, "attachments", None) or [])
        if user_content and not attachments:
            if await self._try_handle_personal_ops_query(
                chat_id=chat_id,
                is_group=is_group,
                message_id=data.id,
                content=user_content,
            ):
                return
            if await self._try_handle_knowledge_inbox_query(
                chat_id=chat_id,
                is_group=is_group,
                message_id=data.id,
                content=user_content,
            ):
                return

        media_paths, recv_lines, att_meta = await self._handle_attachments(attachments)

        # Compose content that always contains actionable saved paths
        if recv_lines:
            tag = "[Image]" if any(_is_image_name(Path(p).name) for p in media_paths) else "[File]"
            file_block = "Received files:\n" + "\n".join(recv_lines)
            content = f"{content}\n\n{file_block}".strip() if content else f"{tag}\n{file_block}"

        if not content and not media_paths:
            return

        if user_content and not media_paths:
            yage_handled = await self._try_handle_yage_raw(
                chat_id=chat_id,
                content=user_content,
                message_id=data.id,
            )
            if yage_handled:
                logger.info("QQ yage raw handler handled message_id={}", data.id)
                return

            handled = await self._try_handle_wechat_grounded(
                user_id=user_id,
                chat_id=chat_id,
                content=user_content,
                message_id=data.id,
            )
            if handled:
                logger.info("QQ grounded WeChat guard handled message_id={}", data.id)
                return

        await self._handle_message(
            sender_id=user_id,
            chat_id=chat_id,
            content=content,
            media=media_paths if media_paths else None,
            metadata={
                "message_id": data.id,
                "attachments": att_meta,
            },
            is_dm=not is_group,
        )

    async def _handle_attachments(
        self,
        attachments: list[object],
    ) -> tuple[list[str], list[str], list[dict[str, Any]]]:
        media_paths: list[str] = []
        recv_lines: list[str] = []
        att_meta: list[dict[str, Any]] = []

        if not attachments:
            return media_paths, recv_lines, att_meta

        for att in attachments:
            url = getattr(att, "url", None) or ""
            filename = getattr(att, "filename", None) or ""
            ctype = getattr(att, "content_type", None) or ""

            logger.info("Downloading file from QQ: {}", filename or url)
            local_path = await self._download_to_media_dir_chunked(url, filename_hint=filename)

            att_meta.append(
                {
                    "url": url,
                    "filename": filename,
                    "content_type": ctype,
                    "saved_path": local_path,
                }
            )

            if local_path:
                media_paths.append(local_path)
                shown_name = filename or os.path.basename(local_path)
                recv_lines.append(f"- {shown_name}\n  saved: {local_path}")
            else:
                shown_name = filename or url
                recv_lines.append(f"- {shown_name}\n  saved: [download failed]")

        return media_paths, recv_lines, att_meta

    async def _download_to_media_dir_chunked(
        self,
        url: str,
        filename_hint: str = "",
    ) -> str | None:
        """Download a bounded attachment safely, preferring the QQ sidecar."""
        if url.startswith("//"):
            url = "https:" + url
        ts = int(time.time() * 1000)
        safe = _sanitize_filename(filename_hint)
        ext = Path(urlparse(url).path).suffix or Path(filename_hint).suffix or ".bin"
        filename = safe if safe and Path(safe).suffix else (safe + ext if safe else f"qq_file_{ts}{ext}")
        target = self._media_root / filename
        if target.exists():
            target = self._media_root / f"{target.stem}_{ts}{target.suffix}"

        max_bytes = max(
            1024 * 1024,
            int(getattr(self.config, "download_max_bytes", 0) or (200 * 1024 * 1024)),
        )
        ok, err = await asyncio.to_thread(validate_url_target, url)
        if not ok:
            logger.warning("inbound media URL blocked url={} err={}", url, err)
            return None

        if not self._http:
            self._http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120))

        # Keep the low-memory sidecar path, but fall back to direct streaming when
        # the sidecar is unavailable or returns an invalid response.
        try:
            async with self._http.post(
                "http://172.17.0.1:8092/download",
                json={
                    "url": url,
                    "target_path": str(target),
                    "max_bytes": max_bytes,
                },
            ) as resp:
                data = await resp.json()
                if isinstance(data, dict) and cast(dict[str, Any], data).get("success"):
                    logger.info("QQ file saved via sidecar: {}", str(target))
                    return str(target)
                logger.warning("QQ sidecar download failed, falling back: {}", data)
        except Exception as exc:
            logger.debug("QQ sidecar download unavailable, falling back: {}", exc)

        tmp_path: Path | None = None
        try:
            async with self._http.get(
                url,
                timeout=aiohttp.ClientTimeout(total=120),
                allow_redirects=False,
            ) as resp:
                if resp.status != 200:
                    logger.warning("QQ attachment download returned status={} url={}", resp.status, url)
                    return None

                content_type = str(resp.headers.get("Content-Type") or "").split(";", 1)[0].strip()
                if ext == ".bin" and content_type:
                    ext = mimetypes.guess_extension(content_type) or ext
                filename = (
                    safe if safe and Path(safe).suffix
                    else f"{safe}{ext}" if safe
                    else f"qq_file_{ts}{ext}"
                )
                target = self._media_root / filename
                if target.exists():
                    target = self._media_root / f"{target.stem}_{ts}{target.suffix}"

                content_length = resp.headers.get("Content-Length")
                if content_length:
                    try:
                        if int(content_length) > max_bytes:
                            logger.warning("QQ attachment exceeds max_bytes={} url={}", max_bytes, url)
                            return None
                    except ValueError:
                        pass

                tmp_path = target.with_suffix(target.suffix + ".part")
                downloaded = 0
                chunk_size = max(1024, int(getattr(self.config, "download_chunk_size", 262144) or 262144))
                def _open_tmp(path: Path) -> BinaryIO:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    return path.open("wb")

                handle = await asyncio.to_thread(_open_tmp, tmp_path)
                try:
                    async for chunk in resp.content.iter_chunked(chunk_size):
                        if not chunk:
                            continue
                        downloaded += len(chunk)
                        if downloaded > max_bytes:
                            logger.warning("QQ attachment exceeded max_bytes={} url={}", max_bytes, url)
                            return None
                        await asyncio.to_thread(handle.write, chunk)
                finally:
                    await asyncio.to_thread(handle.close)

                await asyncio.to_thread(os.replace, tmp_path, target)
                tmp_path = None
                logger.info("QQ file saved: {}", str(target))
                return str(target)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("QQ attachment download failed url={} err={}", url, exc)
            return None
        finally:
            if tmp_path is not None:
                with suppress(OSError):
                    tmp_path.unlink(missing_ok=True)
