"""QQ management contract."""

from nanobot.channels._manifest import field, required_fields
from nanobot.channels.contracts import ChannelSetupSpec
from nanobot.channels.plugin import ChannelPlugin

SETUP_SPEC = ChannelSetupSpec(
    fields={
        # Written by QR binding; manual entry stays available in the WebUI.
        "appId": field(),
        "secret": field("secret"),
        "allowFrom": field("list"),
        "msgFormat": field("enum", choices={"plain", "markdown"}, default="plain"),
        "ackMessage": field(default="⏳ Processing..."),
        "showCompactionNotices": field("bool", inheritable=True),
        "mediaDir": field(),
        "downloadChunkSize": field("int", default=1024 * 256),
        "downloadMaxBytes": field("int", default=1024 * 1024 * 200),
        "textChunkMaxLen": field("int", default=1200),
        "signatureAlertEnabled": field("bool", default=True),
        "signatureAlertChatId": field(),
        "botpyHttpTimeoutSec": field("float", default=5.0),
        "sendRetryOnEmptyResponse": field("bool", default=False),
        "sendRetryAttempts": field("int", default=1),
        "sendRetryDelaySec": field("float", default=0.8),
        "streamEnabled": field("bool", default=False),
        "streamRequiresMsgId": field("bool", default=True),
        "streamMinChars": field("int", default=1),
        "streamMaxChars": field("int", default=5000),
        "streamChunkChars": field("int", default=180),
        "streamIntervalSec": field("float", default=0.0),
        "streamFirstFlushChars": field("int", default=2),
        "streamDeferFirstFrameUntilEnd": field("bool", default=False),
        "streamDeltaFlushChars": field("int", default=120),
        "streamDeltaFlushIntervalSec": field("float", default=0.35),
        "ttsEnabled": field("bool", default=True),
        "ttsVoice": field(default="茉莉"),
        "ttsTimeoutSec": field("int", default=120),
        "ttsMaxChars": field("int", default=1500),
        "ttsApiUrl": field(default="https://api.xiaomimimo.com/v1/chat/completions"),
    },
    required=required_fields("appId", "secret"),
    official_url="https://q.qq.com/",
)

PLUGIN = ChannelPlugin(
    name="qq",
    display_name="QQ",
    runtime=f"{__package__}.runtime:QQChannel",
    connector=f"{__package__}.connect:QQConnectStore",
    setup=SETUP_SPEC,
    dependencies=(
        "aiohttp>=3.9.0,<4.0.0",
        "qq-botpy>=1.2.0,<2.0.0",
    ),
    webui="webui/index.tsx",
)
