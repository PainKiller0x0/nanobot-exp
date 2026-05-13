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
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import aiohttp
from loguru import logger
from pydantic import Field

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import Base
from nanobot.exp.qq import article_requests as qq_article_requests
from nanobot.exp.qq import article_runtime as qq_article_runtime
from nanobot.exp.qq import fast_paths as qq_fast_paths
from nanobot.exp.qq import gateway_greeting as qq_gateway_greeting
from nanobot.exp.qq import inbound_runtime as qq_inbound_runtime
from nanobot.exp.qq import local_commands as qq_local_commands
from nanobot.exp.qq import media_io as qq_media_io
from nanobot.exp.qq import outbound_runtime as qq_outbound_runtime
from nanobot.exp.qq import rich_media as qq_rich_media
from nanobot.exp.qq import signatures as qq_signatures
from nanobot.exp.qq import streaming as qq_streaming
from nanobot.exp.qq import stream_runtime as qq_stream_runtime
from nanobot.exp.qq import text_transport as qq_text_transport
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
QQ_FILE_TYPE_IMAGE = qq_media_io.QQ_FILE_TYPE_IMAGE
QQ_FILE_TYPE_FILE = qq_media_io.QQ_FILE_TYPE_FILE

# Backward-compatible helper exports used by tests and local callers.
_sanitize_filename = qq_media_io.sanitize_filename
_is_image_name = qq_media_io.is_image_name
_parse_qq_timestamp = qq_media_io.parse_qq_timestamp
_guess_send_file_type = qq_media_io.guess_send_file_type


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

    def _extract_wechat_question(self, content: str) -> str | None:
        return qq_article_requests.extract_wechat_question(content)

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

    @staticmethod
    def _cn_num_to_int(text: str) -> int | None:
        return qq_article_requests.cn_num_to_int(text)

    def _parse_yage_selector(self, content: str) -> tuple[int | None, str | None]:
        return qq_article_requests.parse_yage_selector(content)

    def _extract_yage_request(self, content: str) -> bool:
        return qq_article_requests.is_yage_request(content)

    async def _try_handle_yage_raw(
        self,
        chat_id: str,
        content: str,
        message_id: str | None,
    ) -> bool:
        if not self._extract_yage_request(content):
            return False
        nth, target_date = self._parse_yage_selector(content)
        raw = await self._run_yage_signed(
            timeout_sec=45.0,
            nth=nth,
            target_date=target_date,
            force_latest=bool((nth is None and target_date is None) or (nth == 1 and not target_date)),
        )
        if raw is None:
            await self.bus.publish_outbound(
                OutboundMessage(
                    channel="qq",
                    chat_id=chat_id,
                    content="鸭哥文章抓取失败，请稍后重试。",
                    metadata={"message_id": message_id},
                )
            )
            return True
        if not raw.strip():
            not_found_hint = ""
            if target_date:
                not_found_hint = f" (date={target_date})"
            elif nth and nth > 1:
                not_found_hint = f" (nth={nth})"
            await self.bus.publish_outbound(
                OutboundMessage(
                    channel="qq",
                    chat_id=chat_id,
                    content=f"当前未抓取到匹配的鸭哥文章内容{not_found_hint}。",
                    metadata={"message_id": message_id},
                )
            )
            return True
        await self.bus.publish_outbound(
            OutboundMessage(
                channel="qq",
                chat_id=chat_id,
                content=raw,
                metadata={"message_id": message_id},
            )
        )
        logger.info("QQ yage raw handler sent signed latest article chat_id={}", chat_id)
        return True

    def _is_wechat_title_query(self, content: str) -> bool:
        return qq_article_requests.is_wechat_title_query(content)

    async def _try_handle_wechat_grounded(self, user_id: str, chat_id: str, content: str, message_id: str) -> bool:
        if not self.is_allowed(user_id):
            return False

        title_query = self._is_wechat_title_query(content)
        question = self._extract_wechat_question(content)
        if not title_query and not question:
            return False

        if title_query and not question:
            latest = await self._run_sidecar_json(["latest", "--days", "7", "--limit", "50"])
            if not latest or latest.get("status") in {"empty", "error"}:
                reply = "已核验原文：未找到可用文章（NOT_FOUND_IN_ARTICLE）"
            else:
                reply = (
                    f"\u6700\u65b0\u6587\u7ae0\uff1a{latest.get('title') or ''}\n"
                    f"entry_id: {latest.get('entry_id') or 0}\n"
                    f"published_at: {latest.get('published_at') or ''}\n"
                    f"link: {latest.get('link') or ''}"
                )
            await self.bus.publish_outbound(
                OutboundMessage(
                    channel="qq",
                    chat_id=chat_id,
                    content=reply,
                    metadata={"message_id": message_id},
                )
            )
            return True

        ask = await self._run_sidecar_json(
            ["ask", "--question", question or content, "--days", "7", "--limit", "50"]
        )
        if not ask:
            await self.bus.publish_outbound(
                OutboundMessage(
                    channel="qq",
                    chat_id=chat_id,
                    content="已核验原文：未命中问题答案（NOT_FOUND_IN_ARTICLE）",
                    metadata={"message_id": message_id},
                )
            )
            return True

        status = str(ask.get("status") or "").lower()
        if status != "ok":
            reply = (
                "已核验原文：未命中问题答案（NOT_FOUND_IN_ARTICLE）\n"
                f"entry_id: {ask.get('entry_id') or 0}\n"
                f"published_at: {ask.get('published_at') or ''}\n"
                f"link: {ask.get('link') or ''}"
            )
        else:
            answer = str(ask.get("answer") or "").strip()
            reply = (
                f"entry_id: {ask.get('entry_id') or 0}\n"
                f"published_at: {ask.get('published_at') or ''}\n"
                f"link: {ask.get('link') or ''}\n\n"
                f"{answer or 'NOT_FOUND_IN_ARTICLE'}"
            )
        await self.bus.publish_outbound(
            OutboundMessage(
                channel="qq",
                chat_id=chat_id,
                content=reply,
                metadata={"message_id": message_id},
            )
        )
        return True

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

        await qq_outbound_runtime.send_outbound(
            msg,
            session=self._http,
            chat_type_cache=self._chat_type_cache,
            text_chunk_max_len=int(getattr(self.config, "text_chunk_max_len", 1200) or 1200),
            send_media=self._send_media,
            send_text_only=self._send_text_only,
            send_text_streaming=self._send_text_streaming,
            should_stream_text=self._should_stream_text,
            run_wechat_signed=self._run_wechat_signed,
            run_yage_signed=self._run_yage_signed,
            report_signature_blocked=self._report_signature_blocked,
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
        payload = qq_text_transport.build_text_payload(
            content=content,
            msg_id=msg_id,
            msg_seq=self._msg_seq + 1,
            use_markdown=self.config.msg_format == "markdown",
        )
        if not payload:
            return

        self._msg_seq += 1
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
        payload = qq_text_transport.build_stream_payload(
            content=content,
            msg_id=msg_id,
            msg_seq=self._msg_seq,
            state=state,
            index=index,
            reset=reset,
            stream_id=stream_id,
        )
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
        return await qq_text_transport.post_stream_payload(
            self._client,
            Route,
            chat_id=chat_id,
            is_group=is_group,
            payload=payload,
            timeout_sec=float(getattr(self.config, "botpy_http_timeout_sec", 0) or 0),
            logger=logger,
        )

    async def _post_text_payload(
        self,
        chat_id: str,
        is_group: bool,
        msg_id: str | None,
        payload: dict[str, Any],
    ) -> Any | None:
        """Post text through botpy, retrying passive replies when botpy reports no response."""
        return await qq_text_transport.post_text_payload(
            self._client,
            chat_id=chat_id,
            is_group=is_group,
            msg_id=msg_id,
            payload=payload,
            timeout_sec=float(getattr(self.config, "botpy_http_timeout_sec", 0) or 0),
            retry_on_empty_response=bool(getattr(self.config, "send_retry_on_empty_response", False)),
            retry_attempts=int(getattr(self.config, "send_retry_attempts", 0) or 0),
            retry_delay_sec=float(getattr(self.config, "send_retry_delay_sec", 0.0) or 0.0),
            logger=logger,
        )

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
            await qq_rich_media.post_media_message(
                self._client.api,
                chat_id=chat_id,
                is_group=is_group,
                msg_id=msg_id,
                msg_seq=self._msg_seq,
                media_obj=media_obj,
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
        if qq_media_io.is_remote_media_ref(media_ref) and not self._http:
            self._http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120))
        return await qq_media_io.read_media_bytes(self._http, media_ref, logger=logger)

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
        return await qq_rich_media.post_base64file(
            self._client.api._http,
            Route,
            chat_id=chat_id,
            is_group=is_group,
            file_type=file_type,
            file_data=file_data,
            file_name=file_name,
            srv_send_msg=srv_send_msg,
        )


    def _match_personal_ops_command(self, content: str) -> str | None:
        return qq_fast_paths.match_personal_ops_command(content)

    async def _run_personal_ops_command(self, command: str) -> str:
        return await qq_local_commands.run_personal_ops_command(command)

    async def _try_handle_personal_ops_query(
        self,
        *,
        chat_id: str,
        is_group: bool,
        message_id: str,
        content: str,
    ) -> bool:
        command = self._match_personal_ops_command(content)
        if not command:
            return False

        reply = await self._run_personal_ops_command(command)
        max_len = max(200, int(getattr(self.config, "text_chunk_max_len", 1200) or 1200))
        for chunk in split_message(reply, max_len):
            if chunk.strip():
                await self._send_text_only(
                    chat_id=chat_id,
                    is_group=is_group,
                    msg_id=message_id,
                    content=chunk,
                )
        logger.info("QQ personal ops fast path handled command={} message_id={}", command, message_id)
        return True

    def _match_knowledge_inbox_command(self, content: str) -> list[str] | None:
        return qq_fast_paths.match_knowledge_inbox_command(content)

    async def _run_knowledge_inbox_command(self, args: list[str]) -> str:
        return await qq_local_commands.run_knowledge_inbox_command(args)

    async def _try_handle_knowledge_inbox_query(
        self,
        *,
        chat_id: str,
        is_group: bool,
        message_id: str,
        content: str,
    ) -> bool:
        args = self._match_knowledge_inbox_command(content)
        if not args:
            return False

        reply = await self._run_knowledge_inbox_command(args)
        max_len = max(200, int(getattr(self.config, "text_chunk_max_len", 1200) or 1200))
        for chunk in split_message(reply, max_len):
            if chunk.strip():
                await self._send_text_only(
                    chat_id=chat_id,
                    is_group=is_group,
                    msg_id=message_id,
                    content=chunk,
                )
        logger.info("QQ knowledge inbox fast path handled args={} message_id={}", args, message_id)
        return True


    # ---------------------------
    # Inbound (receive)
    # ---------------------------

    async def _on_message(self, data: C2CMessage | GroupMessage, is_group: bool = False) -> None:
        """Parse inbound message, download attachments, and publish to the bus."""
        if data.id in self._processed_ids:
            return
        self._processed_ids.append(data.id)

        chat_context = qq_inbound_runtime.resolve_chat_context(
            data,
            is_group=is_group,
            chat_type_cache=self._chat_type_cache,
            logger=logger,
        )
        if chat_context is None:
            return
        chat_id, user_id = chat_context

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

        content = qq_inbound_runtime.compose_attachment_content(
            content,
            media_paths=media_paths,
            recv_lines=recv_lines,
        )

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
        """Extract, download, and format attachments for agent consumption."""
        return await qq_media_io.handle_attachments(
            attachments,
            self._download_to_media_dir_chunked,
            logger=logger,
        )

    async def _download_to_media_dir_chunked(
        self,
        url: str,
        filename_hint: str = "",
    ) -> str | None:
        """Download an inbound attachment using QQ-Sidecar-RS."""
        max_bytes = max(
            1024 * 1024,
            int(getattr(self.config, "download_max_bytes", 0) or (200 * 1024 * 1024)),
        )
        if not self._http:
            self._http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120))
        return await qq_media_io.download_to_media_dir_chunked(
            self._http,
            self._media_root,
            url,
            filename_hint=filename_hint,
            max_bytes=max_bytes,
            logger=logger,
        )
