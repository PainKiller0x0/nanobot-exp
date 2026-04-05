"""
L1: ShadowEngine — 影子引擎

职责:
1. 启动/管理 main + shadow 两个 gateway 子进程
2. 健康检查 (进程存活 + session 新鲜度)
3. 故障时激活 shadow gateway
4. 重建 main gateway 并在健康后切回

设计原则（对标 Android A/B）:
- Main = Slot A（当前运行的版本）
- Shadow = Slot B（上一个确认安全的版本，inactive slot）
- ShadowEngine 始终监控 Main，Main 健康时才有效
"""

from __future__ import annotations

import asyncio
import json
import logging
import signal
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from ark.slot_manager import SlotManager

NANOBOT_ROOT = Path.home() / ".nanobot"
PENDING_SWITCH_FILE = NANOBOT_ROOT / "pending_switch"



logger = logging.getLogger(__name__)

# 路径常量
NANOBOT_ROOT = Path.home() / ".nanobot"
SLOT_A = NANOBOT_ROOT / "slot_a"
SLOT_B = NANOBOT_ROOT / "slot_b"
ACTIVE_SLOT_FILE = NANOBOT_ROOT / "active_slot"

# 自检参数
CHECK_INTERVAL = 5.0  # 健康检查间隔（秒）
SESSION_MAX_AGE = 120  # session 文件最大年龄（秒）
REBUILD_DELAY = 10  # 重建 main 前等待（秒）


@dataclass
class GatewayProcess:
    """单个 gateway 进程"""
    name: str
    port: int
    process: Optional[asyncio.subprocess.Process] = None
    is_shadow: bool = False


class ShadowEngine:
    """
    L1: 影子引擎

    管理两个 gateway 子进程:
    - Main Gateway (Slot A): 正常运行时，接收所有改动
    - Shadow Gateway (Slot B): 平时待机，收到 ACTIVATE 后接管
    """

    def __init__(
        self,
        main_port: int = 8080,
        shadow_port: int = 8081,
        check_interval: float = CHECK_INTERVAL
    ):
        self._main_port = main_port
        self._shadow_port = shadow_port
        self._check_interval = check_interval

        self._main_gateway: Optional[GatewayProcess] = None
        self._shadow_gateway: Optional[GatewayProcess] = None
        self._slots = SlotManager()

        # False = shadow 在服务，True = main 在服务
        self._main_is_active = True
        self._shadow_activated = False
        # 记录 main gateway 最近一次 spawn 时间，用于启动缓冲期（不健康检查）
        self._main_spawn_time: float = 0.0


    # ── 生命周期 ────────────────────────────────────────────────────────

    async def start(self):
        """启动双引擎"""
        logger.info(f"ShadowEngine starting (main={self._main_port}, shadow={self._shadow_port})")

        # 启动 main gateway
        main_proc = await self._spawn_gateway(self._main_port, is_shadow=False)
        self._main_spawn_time = time.monotonic()
        self._main_gateway = GatewayProcess(
            name="main",
            port=self._main_port,
            process=main_proc,
            is_shadow=False
        )

        # 启动 shadow gateway (待机)
        # NOTE: shadow.py 独立进程已经在监听 shadow_port.
        # 启动时不需要 spawn gateway subprocess——failover 时 shadow.py 自己会 spawn。
        # 避免重复处理 QQ 消息，这里不启动 shadow gateway subprocess。
        # shadow_proc = await self._spawn_gateway(self._shadow_port, is_shadow=True)
        self._shadow_gateway = GatewayProcess(
            name="shadow",
            port=self._shadow_port,
            process=None,
            is_shadow=True
        )

        self._main_is_active = True


        logger.info("ShadowEngine started")

    async def stop(self):
        """停止所有 gateway 子进程"""
        self._shutdown = True


        for gw in (self._main_gateway, self._shadow_gateway):
            if gw and gw.process:
                try:
                    gw.process.terminate()
                    await asyncio.wait_for(gw.process.wait(), timeout=5)
                except asyncio.TimeoutError:
                    gw.process.kill()
                    await gw.process.wait()
                except Exception as e:
                    logger.warning(f"Error stopping {gw.name}: {e}")

        logger.info("ShadowEngine stopped")

    # ── 子进程管理 ──────────────────────────────────────────────────────

    async def _spawn_gateway(
        self,
        port: int,
        is_shadow: bool
    ) -> asyncio.subprocess.Process:
        """启动 gateway 子进程，等待端口就绪"""
        import os as _os

        if is_shadow:
            # Shadow gateway: 走独立入口 ark_entry/shadow.py，不加载 nanobot 包
            import nanobot
            nanobot_root = Path(nanobot.__file__).parent.parent
            shadow_entry = nanobot_root / "ark_entry" / "shadow.py"
            args = [sys.executable, str(shadow_entry), "--port", str(port)]
            pid_path = NANOBOT_ROOT / "gateway_shadow.pid"
            args.extend(["--pid-file", str(pid_path)])
        else:
            args = [sys.executable, "-m", "nanobot", "gateway"]
            args.extend(["--port", str(port)])
            args.extend(["--pid-file", str(NANOBOT_ROOT / "gateway_main.pid")])
            gateway_ws = self._slots.current.workspace

        env = {**_os.environ}
        env["ARK_SLOT_WORKSPACE"] = str(self._slots.current.workspace)
        label = "Shadow" if is_shadow else "Main"
        logger.debug(f"{label} gateway workspace: {self._slots.current.workspace}")
        proc = await asyncio.create_subprocess_exec(
            *args,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        logger.info(
            f"Spawned {'shadow' if is_shadow else 'main'} gateway "
            f"(pid={proc.pid}, port={port})"
        )
        # 检查 session 文件新鲜度
        if not _is_session_fresh(SESSION_MAX_AGE):
            logger.warning("Main gateway session not fresh")
            await self._failover_to_shadow()

    # ── 故障切换 ────────────────────────────────────────────────────────

    async def _failover_to_shadow(self):
        """
        故障切换到 shadow gateway
        1. 写 pending_switch 文件，通知 watchdog 进入 ARK 模式（不重启 gateway）
        2. 发送 ACTIVATE 到 shadow
        3. shadow 读取 session 接管
        4. 后台重建 main
        """
        if self._shadow_activated:
            logger.debug("Shadow already activated, skipping failover")
            return

        logger.warning("Failing over to shadow gateway")

        # 通知 watchdog 进入 ARK 模式，不要重启 gateway
        PENDING_SWITCH_FILE.write_text(json.dumps({
            "event": "failover",
            "from": "main",
            "to": "shadow",
            "at": datetime.now().isoformat(),
        }))
        logger.info("Wrote pending_switch (ARK mode)")

        success = await self._send_activate()
        if success:
            self._main_is_active = False
            self._shadow_activated = True
            logger.info("Shadow gateway activated")

            # 后台重建 main gateway
            asyncio.create_task(self._rebuild_main())
        else:
            logger.error("Failed to activate shadow, shadow gateway may be down")

    async def _send_activate(self) -> bool:
        """发送 ACTIVATE 信号到 shadow gateway"""
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection("localhost", self._shadow_port),
                timeout=5
            )

            writer.write(b"ACTIVATE\n")
            await writer.drain()

            resp = await asyncio.wait_for(reader.readline(), timeout=5)
            logger.info(f"Shadow responded: {resp.decode().strip()}")

            writer.close()
            await writer.wait_closed()

            return True
        except asyncio.TimeoutError:
            logger.error("Shadow gateway activation timed out")
            return False
        except Exception as e:
            logger.error(f"Failed to activate shadow: {e}")
            return False

    async def _send_state(self, state: dict) -> bool:
        """发送状态更新到 shadow gateway"""
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection("localhost", self._shadow_port),
                timeout=5
            )

            import json
            writer.write(f"STATE\n{json.dumps(state)}\n".encode())
            await writer.drain()

            resp = await asyncio.wait_for(reader.readline(), timeout=5)
            ok = resp.decode().strip() == "STATE_OK"

            writer.close()
            await writer.wait_closed()

            return ok
        except Exception as e:
            logger.warning(f"State sync to shadow failed: {e}")
            return False

    # ── 重建 Main ───────────────────────────────────────────────────────

    async def _rebuild_main(self):
        """重建 main gateway"""
        await asyncio.sleep(REBUILD_DELAY)

        # 终止旧 main
        if self._main_gateway and self._main_gateway.process:
            try:
                self._main_gateway.process.terminate()
                await asyncio.wait_for(
                    self._main_gateway.process.wait(),
                    timeout=5
                )
            except asyncio.TimeoutError:
                self._main_gateway.process.kill()
                await self._main_gateway.process.wait()
            except Exception:
                pass

        # 启动新 main
        main_proc = await self._spawn_gateway(self._main_port, is_shadow=False)
        self._main_gateway = GatewayProcess(
            name="main",
            port=self._main_port,
            process=main_proc,
            is_shadow=False
        )

        # 等待新 main 就绪
        await asyncio.sleep(5)

        # 检查新 main 健康状态
        if await self._check_main_health_poll():
            await self._switch_back_to_main()

    async def _check_main_health_poll(self) -> bool:
        """轮询检查 main 健康（用于重建后验证）"""
        for _ in range(3):
            await asyncio.sleep(2)
            if not self._main_gateway or not self._main_gateway.process:
                continue
            try:
                await asyncio.wait_for(self._main_gateway.process.wait(), timeout=0.01)
            except asyncio.TimeoutError:
                if _is_session_fresh(SESSION_MAX_AGE):
                    return True
        return False

    async def _switch_back_to_main(self):
        """切回 main gateway"""
        if not self._shadow_activated:
            return

        logger.info("Main gateway healthy, switching back")

        # 通知 shadow 停机（简单做法：杀 shadow 进程）
        if self._shadow_gateway and self._shadow_gateway.process:
            try:
                self._shadow_gateway.process.terminate()
                await asyncio.wait_for(
                    self._shadow_gateway.process.wait(),
                    timeout=5
                )
            except asyncio.TimeoutError:
                self._shadow_gateway.process.kill()
            except Exception:
                pass

        self._shadow_activated = False
        self._main_is_active = True

        # 重新启动 shadow 作为备用
        shadow_proc = await self._spawn_gateway(self._shadow_port, is_shadow=True)
        self._shadow_gateway = GatewayProcess(
            name="shadow",
            port=self._shadow_port,
            process=shadow_proc,
            is_shadow=True
        )

        logger.info("Switched back to main gateway, shadow restarted as standby")


# ── 工具函数 ──────────────────────────────────────────────────────────

def _is_session_fresh(max_age: int = SESSION_MAX_AGE) -> bool:
    """检查 session 文件新鲜度（跨进程，不需要 async）"""
    try:
        if not ACTIVE_SLOT_FILE.exists():
            return False

        slot_name = ACTIVE_SLOT_FILE.read_text().strip().lower()
        slot_path = SLOT_A if slot_name == "a" else SLOT_B

        latest = slot_path / "sessions" / "latest.json"
        if not latest.exists():
            return False

        age = time.time() - latest.stat().st_mtime
        return age < max_age
    except Exception:
        return False
