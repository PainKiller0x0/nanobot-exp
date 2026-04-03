"""
共享的 gateway 组件初始化逻辑

commands.gateway() 和 ShadowGateway._run_gateway() 都用这个，
避免重复维护两份相同的初始化代码。
"""

from __future__ import annotations

import asyncio
import signal
from pathlib import Path
from typing import Any

from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.channels.manager import ChannelManager
from nanobot.config.schema import Config
from loguru import logger
from nanobot.cron.service import CronService
from nanobot.heartbeat.service import HeartbeatService
from nanobot.session.manager import SessionManager


def _load_runtime_config(config_arg: str | None, workspace_arg: str | None) -> Config:
    """
    加载 runtime config（直接复用 commands._load_runtime_config）。

    参数优先级: config_arg > workspace_arg > 默认 config.json
    """
    from nanobot.cli.commands import _load_runtime_config as _original
    return _original(config_arg, workspace_arg)


def _make_provider(config: Config) -> Any:
    """创建 LLM provider。"""
    from nanobot.agent.provider.factory import make_provider
    return make_provider(config)


async def build_gateway(
    config: Config,
    console: Any = None,
    shutdown_event: asyncio.Event | None = None,
) -> dict[str, Any]:
    """
    构建 gateway 所有组件，返回 dict 包含:

    - bus: MessageBus
    - provider: LLM provider
    - session_manager: SessionManager
    - agent: AgentLoop
    - channels: ChannelManager
    - cron: CronService
    - heartbeat: HeartbeatService
    - shutdown_event: asyncio.Event (caller负责set)
    """
    import os
    from rich.console import Console

    if console is None:
        console = Console()

    if shutdown_event is None:
        shutdown_event = asyncio.Event()

    # ARK shadow gateway：使用 standby slot 的 workspace（通过环境变量传入）
    workspace_override = os.environ.get("ARK_SLOT_WORKSPACE")
    if workspace_override:
        config.agents.defaults.workspace = str(Path(workspace_override).expanduser())
        logger.debug(f"Using ARK slot workspace: {workspace_override}")

    bus = MessageBus()
    provider = _make_provider(config)
    session_manager = SessionManager(config.workspace_path)

    # Cron service: workspace-scoped store
    cron_store_path = config.workspace_path / "cron" / "jobs.json"
    cron = CronService(cron_store_path)

    # Agent loop
    agent = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=config.workspace_path,
        model=config.agents.defaults.model,
        max_iterations=config.agents.defaults.max_tool_iterations,
        context_window_tokens=config.agents.defaults.context_window_tokens,
        web_search_config=config.tools.web.search,
        web_proxy=config.tools.web.proxy or None,
        exec_config=config.tools.exec,
        cron_service=cron,
        restrict_to_workspace=config.tools.restrict_to_workspace,
        session_manager=session_manager,
        mcp_servers=config.tools.mcp_servers,
        channels_config=config.channels,
        timezone=config.agents.defaults.timezone,
    )

    channels = ChannelManager(config, bus)

    # Heartbeat service
    hb_cfg = config.gateway.heartbeat
    heartbeat = HeartbeatService(
        workspace=config.workspace_path,
        provider=provider,
        model=agent.model,
        interval_s=hb_cfg.interval_s,
        enabled=hb_cfg.enabled,
        timezone=config.agents.defaults.timezone,
    )

    loop = asyncio.get_running_loop()

    def _sigterm_handler():
        console.print("[yellow]Received SIGTERM[/yellow]")
        asyncio.create_task(_gs())

    try:
        loop.add_signal_handler(signal.SIGTERM, _sigterm_handler)
    except NotImplementedError:
        pass  # Windows

    async def _gs():
        """Shared graceful shutdown sequence."""
        console.print("[yellow]Graceful shutdown in progress...[/yellow]")
        agent.stop()
        heartbeat.stop()
        cron.stop()
        try:
            for key, session in session_manager._cache.items():
                session_manager.save(session)
            console.print(f"[green]✓[/green] Sessions saved ({len(session_manager._cache)})")
        except Exception:
            console.print("[red]✗[/red] Session save failed")
        await channels.stop_all()
        await agent.close_mcp()
        shutdown_event.set()

    return {
        "bus": bus,
        "provider": provider,
        "session_manager": session_manager,
        "agent": agent,
        "channels": channels,
        "cron": cron,
        "heartbeat": heartbeat,
        "shutdown_event": shutdown_event,
        "console": console,
        "graceful_shutdown": _gs,
    }
