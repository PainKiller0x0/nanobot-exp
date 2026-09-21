# Nanobot Exp

这是 [HKUDS/nanobot](https://github.com/HKUDS/nanobot) 的生产维护 fork，当前基线为上游 **v0.3.5**。

本仓库服务于 PainKiller0x0 的 Nanobot 部署，重点是：

- 保持 Nanobot 核心与上游接近，便于后续升级。
- 通过独立扩展层提供 QQ/微信运行时、记忆、历史上下文和模型兜底能力。
- 通过 Rust sidecar、systemd 和运维脚本支撑 VPS 上的长期运行。
- 所有密钥、运行时配置、数据库和备份都留在服务器私有目录，不进入 Git。

## 目录结构

| 目录 | 用途 |
|---|---|
| `nanobot/` | 上游 Nanobot 核心代码 |
| `nanobot/exp/` | 本地扩展胶水层，不直接改主循环 |
| `nanobot/exp/qq/` | QQ 消息投递、流式回复、文章和本地命令辅助 |
| `nanobot/exp/agent/` | 历史上下文预算、工具预算、记忆桥接和模型 fallback |
| `ops/sources/` | Rust sidecar 和其他本地服务源码 |
| `ops/scripts/` | 安装、同步、健康检查、冒烟测试和回滚脚本 |
| `ops/systemd/` | VPS 服务与 timer 单元 |
| `docs/` | 架构、扩展胶水、运行时补丁和 memory-rs 文档 |

## 生产部署

当前 VPS 部署目录：

```text
/root/nanobot
```

主服务：

```text
podman-nanobot-cage.service
```

本机健康检查：

```text
curl http://127.0.0.1:8080/health
```

线上容器通过挂载仓库运行。VPS 使用 `ops/Dockerfile.vps-runtime` 构建增量运行镜像，避免每次同步上游都重新构建完整 WebUI 工具链。

当前通道白名单由环境变量控制：

```text
NANOBOT_CHANNEL_ALLOWLIST=qq,weixin
```

## 扩展原则

本 fork 的本地功能尽量遵循以下边界：

1. Nanobot 核心只保留必要的兼容改动。
2. 新行为优先放到 `nanobot/exp/` 或独立 sidecar。
3. 记忆、通知、模型路由和 QQ 运行时不把密钥写入源码。
4. 上游升级后先做兼容性检查，再重装扩展胶水。
5. 生产变更先保留 Git、镜像和配置回滚点。

详细设计见：

- [架构说明](docs/ARCHITECTURE.md)
- [扩展胶水层](docs/EXTENSIONS_GLUE.md)
- [运行时补丁脚本](docs/RUNTIME_PATCH_SCRIPTS.md)
- [memory-rs](docs/memory-rs.md)

## 升级与回滚

同步上游时，优先从 [HKUDS/nanobot](https://github.com/HKUDS/nanobot) 的目标版本建立迁移分支，再逐项恢复本地扩展和运维文件。不要直接用上游分支覆盖生产分支。

当前保留的回滚点：

- Git 迁移回滚：`backup/pre-upstream-20260921`
- 本次 GitHub `main` 覆盖前的备份：`backup/pre-main-sync-20260921`
- VPS 镜像回滚：`localhost/nanobot-nanobot:pre-v0.3.5-20260921`

## 发布前检查

至少确认：

- `git diff --check` 通过。
- 目标测试和扩展冒烟测试通过。
- `/health` 返回 `status=ok` 且 `ready=true`。
- QQ/微信机器人完成启动并能收到一条真实回复。
- GitHub 推送成功后，再执行生产容器重启或镜像切换。

## 安全边界

不要提交以下内容：

- API key、OAuth token、WebSocket secret。
- `/root/.nanobot/` 下的运行时配置和数据库。
- `ops/backups/` 下的服务器备份。
- 个人聊天记录、文章原文和消息平台凭据。

本项目沿用上游 Nanobot 的许可证和社区信息，功能变更以本仓库提交记录及 `docs/` 为准。
