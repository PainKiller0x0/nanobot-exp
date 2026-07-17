# nanobot-ops — 线上部署清单

本文档记录线上服务器 150.158.121.88 中哪些是**生产必需文件**。

## 生产服务一览（共 13 个）

| 端口 | 服务 | 类型 | 源码位置 |
|-----|------|------|---------|
| 8080 | nanobot-cage | Podman 容器 | `nanobot/` |
| 8091 | wechat-rss-sidecar | Podman 容器 | `ops/sources/wechat-rss-rs/` |
| 8093 | lof-sidecar | Rust 二进制 | `ops/sources/lof-sidecar-rs/` |
| 8096 | session-mgr-rs | Rust 二进制 | `ops/sources/session-mgr-rs/` |
| 8098 | dsa-webui | Python FastAPI | `/root/daily_stock_analysis/`（独立项目）|
| 8000 | obp-rs | Rust 二进制 | `ops/sources/obp-rs/` |
| — | memory-rs | Rust 二进制 | `ops/sources/memory-rs/` |
| — | notify-sidecar-rs | Rust 二进制 | `ops/sources/notify-sidecar-rs/` |
| — | trend-sidecar-rs | Rust 二进制 | `ops/sources/trend-sidecar-rs/` |
| — | qq-sidecar-rs | Rust 二进制 | `ops/sources/qq-sidecar-rs/` |
| — | gemini-fastapi-tunnel | SSH 隧道 | `/root/Gemini-FastAPI/`（独立项目）|
| 443 | caddy | 反向代理 | `/etc/caddy/Caddyfile` |

## 磁盘分布（/dev/vda1 共 50G）

| 路径 | 大小 | 说明 |
|-----|------|------|
| `/root/nanobot/` | 3.1GB | 完整 Git 仓库 |
| `ops/sources/*/target/` | ~2.4GB | Rust 编译缓存 — **线上必需，保留** |
| `.venv/` | 230MB | Python venv |
| `.git/` | 158MB | Git 历史 |
| `/root/.nanobot/` | 637MB | 运行时数据 + session 日志 |
| Podman 镜像 | 3.72GB | 3 个 nanobot 镜像 |

## 重要对照

```
版本控制的源码          → 线上运行的文件
─────────────────────────────────────────
nanobot/channels/qq.py  → 容器 /app/nanobot/channels/qq.py（volume mount）
/root/.nanobot/overrides/qq.py  → 容器启动时覆盖上述文件
ops/config/*            → sidecar 配置（复制到 /root/.nanobot 或对应路径）
ops/systemd/*           → /etc/systemd/system/ 中对应的 .service
ops/bin/*               → 部署辅助脚本
```

## 本地 vs 线上

本地 `D:\files\nanobot_test\` 下的 `archive/`、`smoke/`、`patches/`、`fixes/`、`inspect/`、`tools/`、`rust-src/` 目录以及各种测试脚本（`test_*.py`、`fix_*.py` 等）均为**开发调试产物**，不在线上，不进入 Git main 分支。
