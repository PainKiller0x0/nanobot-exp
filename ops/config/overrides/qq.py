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

from __future__ import annotations

import asyncio
import base64
import mimetypes
import os
import re
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import unquote, urlparse

import aiohttp
from loguru import logger
from pydantic import Field

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import Base
from nanobot.exp.qq import article_handlers as qq_article_handlers
from nanobot.exp.qq import article_runtime as qq_article_runtime
from nanobot.exp.qq import gateway_greeting as qq_gateway_greeting
from nanobot.exp.qq import local_handlers as qq_local_handlers
from nanobot.exp.qq import signatures as qq_signatures
from nanobot.exp.qq import signed_delivery as qq_signed_delivery
from nanobot.exp.qq import streaming as qq_streaming
from nanobot.exp.qq import stream_runtime as qq_stream_runtime
from nanobot.security.network import validate_url_target
from nanobot.utils.helpers import split_message

try:
    from nanobot.config.paths import get_media_dir
except Exception:  # pragma: no cover
    get_media_dir = None  # type: ignore

try:
    import botpy
    from botpy.http import Route

    QQ_AVAILABLE = True
except ImportError:  # pragma: no cover
    QQ_AVAILABLE = False
    botpy = None
    Route = None

if TYPE_CHECKING:
    from botpy.message import BaseMessage, C2CMessage, GroupMessage
    from botpy.types.message import Media


# QQ rich media file_type: 1=image, 4=file
# (2=voice, 3=video are restricted; we only use image vs file)
QQ_FILE_TYPE_IMAGE = 1
QQ_FILE_TYPE_FILE = 4

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

# Replace unsafe characters with "_", keep Chinese and common safe punctuation.
_SAFE_NAME_RE = re.compile(r"[^\w.\-()\[\]（）【】\u4e00-\u9fff]+", re.UNICODE)


def _sanitize_filename(name: str) -> str:
    """Sanitize filename to avoid traversal and problematic chars."""
    name = (name or "").strip()
    name = Path(name).name
    name = _SAFE_NAME_RE.sub("_", name).strip("._ ")
    return name


def _is_image_name(name: str) -> bool:
    return Path(name).suffix.lower() in _IMAGE_EXTS


def _parse_qq_timestamp(ts: str | None) -> datetime | None:
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
    """Conservative send type: images -> 1, else -> 4."""
    ext = Path(filename).suffix.lower()
    mime, _ = mimetypes.guess_type(filename)
    if ext in _IMAGE_EXTS or (mime and mime.startswith("image/")):
        return QQ_FILE_TYPE_IMAGE
    return QQ_FILE_TYPE_FILE


def _strip_silent_marker(text: str) -> str:
    return qq_signatures.strip_silent_marker(text)
def _make_bot_class(channel: QQChannel) -> type[botpy.Client]:
    """Create a botpy Client subclass bound to the given channel."""
    intents = botpy.Intents(public_messages=True, direct_message=True)

    class _Bot(botpy.Client):
        def __init__(self):
            # Disable botpy's file log — nanobot uses loguru; default "botpy.log" fails on read-only fs
            super().__init__(intents=intents, ext_handlers=False)

        async def on_ready(self):
            logger.info("QQ bot ready: {}", self.robot.name)
            await channel._check_greeting_trigger()

        async def on_c2c_message_create(self, message: C2CMessage):
            await channel._on_message(message, is_group=False)

        async def on_group_at_message_create(self, message: GroupMessage):
            await channel._on_message(message, is_group=True)

    return _Bot


class QQConfig(Base):
    """QQ channel configuration using botpy SDK."""

    enabled: bool = False
    app_id: str = ""
    secret: str = ""
    allow_from: list[str] = Field(default_factory=list)
    msg_format: Literal["plain", "markdown"] = "plain"

    # Optional: directory to save inbound attachments. If empty, use nanobot get_media_dir("qq").
    media_dir: str = ""

    # Download tuning
    download_chunk_size: int = 1024 * 256  # 256KB
    download_max_bytes: int = 1024 * 1024 * 200  # 200MB safety limit

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
    stream_min_chars: int = 120
    stream_max_chars: int = 5000
    stream_chunk_chars: int = 180
    stream_interval_sec: float = 0.0
    stream_first_flush_chars: int = 24
    stream_delta_flush_chars: int = 120
    stream_delta_flush_interval_sec: float = 0.35


class QQChannel(BaseChannel):
    """QQ channel using botpy SDK with WebSocket connection."""

    name = "qq"
    display_name = "QQ"

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return QQConfig().model_dump(by_alias=True)

    @property
    def supports_streaming(self) -> bool:
        return qq_streaming.supports_streaming(self.config)
    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = QQConfig.model_validate(config)
        super().__init__(config, bus)
        self.config: QQConfig = config

        self._client: botpy.Client | None = None
        self._http: aiohttp.ClientSession | None = None

        self._processed_ids: deque[str] = deque(maxlen=1000)
        self._msg_seq: int = 1  # used to avoid QQ API dedup
        self._chat_type_cache: dict[str, str] = {}
        self._stream_states: dict[str, dict[str, Any]] = {}

        self._media_root: Path = self._init_media_root()

    # ---------------------------
    # Lifecycle
    # ---------------------------

    def _init_media_root(self) -> Path:
        """Choose a directory for saving inbound attachments."""
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
        """Run the bot connection with auto-reconnect."""
        while self._running:
            try:
                await self._client.start(appid=self.config.app_id, secret=self.config.secret)
                # Bot connected successfully - greeting is now triggered in on_ready
            except Exception as e:
                logger.warning("QQ bot error: {}", e)
            if self._running:
                logger.info("Reconnecting QQ bot in 5 seconds...")
                await asyncio.sleep(5)

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

    # ---------------------------
    # Outbound (send)
    # ---------------------------


    async def send(self, msg: OutboundMessage) -> None:
        """Send attachments first, then text."""
        if not self._client:
            logger.warning("QQ client not initialized")
            return

        msg_id = msg.metadata.get("message_id")
        chat_type = self._chat_type_cache.get(msg.chat_id, "c2c")
        is_group = chat_type == "group"

        # 1) Send media
        for media_ref in msg.media or []:
            ok = await self._send_media(
                chat_id=msg.chat_id,
                media_ref=media_ref,
                msg_id=msg_id,
                is_group=is_group,
            )
            if not ok:
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

        # 2) Send text (chunked to avoid QQ-side truncation on long payloads)
        if msg.content and msg.content.strip():
            prepared = await qq_signed_delivery.prepare_outbound_content(
                msg.content,
                session=self._http,
                run_wechat_signed=self._run_wechat_signed,
                run_yage_signed=self._run_yage_signed,
                chat_id=msg.chat_id,
                logger=logger,
            )
            if prepared.suppressed:
                logger.info("QQ outbound suppressed reason={} chat_id={}", prepared.reason, msg.chat_id)
                return
            if prepared.blocked:
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
                return

            safe_content = prepared.content
            is_signed_payload = prepared.is_signed_payload
            wechat_ack = prepared.wechat_ack

            if is_signed_payload:
                # Prefer one-shot delivery for raw signed articles.
                # Only fallback to splitting when QQ rejects oversize payload.
                try:
                    await self._send_text_only(
                        chat_id=msg.chat_id,
                        is_group=is_group,
                        msg_id=msg_id,
                        content=safe_content,
                    )
                    await qq_signed_delivery.ack_delivery(
                        self._http,
                        safe_content,
                        wechat_ack,
                        chat_id=msg.chat_id,
                        logger=logger,
                    )
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
                    await self._send_text_streaming(
                        chat_id=msg.chat_id,
                        is_group=is_group,
                        msg_id=msg_id,
                        content=safe_content,
                    )
                    return
                except Exception as e:
                    logger.warning(
                        "QQ stream send failed, fallback to normal chunking chat_id={} err={}",
                        msg.chat_id,
                        e,
                    )

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
                except Exception as e:
                    logger.error("QQ text send failed chat_id={} err={}", msg.chat_id, e)
                    return
            if is_signed_payload:
                await qq_signed_delivery.ack_delivery(
                    self._http,
                    safe_content,
                    wechat_ack,
                    chat_id=msg.chat_id,
                    logger=logger,
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
        """Send a plain/markdown text message."""
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
        if isinstance(result, dict) and result.get("id"):
            return str(result["id"])
        return None

    async def send_delta(
        self,
        chat_id: str,
        delta: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
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
        if not self._client or not getattr(self._client.api, "_http", None) or Route is None:
            raise RuntimeError("QQ raw HTTP client is not available for streaming")

        if is_group:
            endpoint = "/v2/groups/{group_openid}/messages"
            id_key = "group_openid"
        else:
            endpoint = "/v2/users/{openid}/messages"
            id_key = "openid"

        route = Route("POST", endpoint, **{id_key: chat_id})
        return await self._client.api._http.request(route, json=payload)

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

        for attempt in range(1, attempts + 1):
            try:
                if is_group:
                    result = await self._client.api.post_group_message(group_openid=chat_id, **payload)
                else:
                    result = await self._client.api.post_c2c_message(openid=chat_id, **payload)
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
        """Read bytes -> base64 upload -> msg_type=7 send."""
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

    async def _read_media_bytes(self, media_ref: str) -> tuple[bytes | None, str | None]:
        """Read bytes from http(s) or local file path; return (data, filename)."""
        media_ref = (media_ref or "").strip()
        if not media_ref:
            return None, None

        # Local file: plain path or file:// URI
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

        # Remote URL
        ok, err = validate_url_target(media_ref)
        if not ok:
            logger.warning("QQ outbound media URL validation failed url={} err={}", media_ref, err)
            return None, None

        if not self._http:
            self._http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120))
        try:
            async with self._http.get(media_ref, allow_redirects=True) as resp:
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
    ) -> Media:
        """Upload base64-encoded file and return Media object."""
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

        route = Route("POST", endpoint, **{id_key: chat_id})
        result = await self._client.api._http.request(route, json=payload)
        if isinstance(result, dict) and "file_info" in result:
            return {"file_info": result["file_info"]}
        return result


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

    async def _on_message(self, data: C2CMessage | GroupMessage, is_group: bool = False) -> None:
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

        content = (getattr(data, "content", "") or "").strip()

        # the data used by tests don't contain attachments property
        # so we use getattr with a default of [] to avoid AttributeError in tests
        attachments = getattr(data, "attachments", None) or []
        if content and not attachments:
            if await self._try_handle_personal_ops_query(
                chat_id=chat_id,
                is_group=is_group,
                message_id=data.id,
                content=content,
            ):
                return
            if await self._try_handle_knowledge_inbox_query(
                chat_id=chat_id,
                is_group=is_group,
                message_id=data.id,
                content=content,
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

        if content and not media_paths:
            yage_handled = await self._try_handle_yage_raw(
                chat_id=chat_id,
                content=content,
                message_id=data.id,
            )
            if yage_handled:
                logger.info("QQ yage raw handler handled message_id={}", data.id)
                return

            handled = await self._try_handle_wechat_grounded(
                user_id=user_id,
                chat_id=chat_id,
                content=content,
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
        )

    async def _handle_attachments(
        self,
        attachments: list[BaseMessage._Attachments],
    ) -> tuple[list[str], list[str], list[dict[str, Any]]]:
        """Extract, download (chunked), and format attachments for agent consumption."""
        media_paths: list[str] = []
        recv_lines: list[str] = []
        att_meta: list[dict[str, Any]] = []

        if not attachments:
            return media_paths, recv_lines, att_meta

        for att in attachments:
            url, filename, ctype = att.url, att.filename, att.content_type

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
        """Download an inbound attachment using QQ-Sidecar-RS."""

        ts = int(time.time() * 1000)
        safe = _sanitize_filename(filename_hint)
        ext = Path(urlparse(url).path).suffix
        if not ext:
            ext = Path(filename_hint).suffix
        if not ext:
            ext = ".bin"

        if safe:
            if not Path(safe).suffix:
                safe = safe + ext
            filename = safe
        else:
            filename = f"qq_file_{ts}{ext}"

        target = self._media_root / filename
        if target.exists():
            target = self._media_root / f"{target.stem}_{ts}{target.suffix}"

        max_bytes = max(1024 * 1024, int(getattr(self.config, "download_max_bytes", 0) or (200 * 1024 * 1024)))

        if not self._http:
            import aiohttp
            self._http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120))

        try:
            async with self._http.post(
                "http://172.17.0.1:8092/download",
                json={
                    "url": url,
                    "target_path": str(target),
                    "max_bytes": max_bytes
                }
            ) as resp:
                data = await resp.json()
                if data.get("success"):
                    logger.info("QQ file saved via sidecar: {}", str(target))
                    return str(target)
                else:
                    logger.error("QQ sidecar download error: {}", data.get("error"))
                    return None
        except Exception as e:
            logger.error("QQ sidecar download request error: {}", e)
            return None
