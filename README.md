# nanobot-exp

`nanobot-exp` is a personal production fork of [HKUDS/nanobot](https://github.com/HKUDS/nanobot).

This repository keeps the Nanobot core close to upstream while adding the production glue I actually use every day: QQ/WeChat channels, sidecars, model routing, content workflows, operations guardrails, and dashboards.

> Current baseline: Nanobot `0.2.1` plus the `ops/` sidecar layer. Runtime secrets, databases, logs and live target IDs are intentionally kept out of git.

## 中文说明

### 这个仓库是什么

这是一个“上游 Nanobot + 个人生产胶水”的仓库，不是重新发明一个全新的 agent 框架。

核心思路：

- `nanobot/` 尽量跟随上游，只保留必要的下游兼容、QQ/微信体验和安全修复。
- `ops/` 承载线上服务编排、sidecar 源码快照、systemd 单元、部署脚本和运维工具。
- 各类重功能尽量放到 sidecar 或 skill，不把 Nanobot 主进程拖成一个越来越重的常驻巨兽。
- 默认 nanobot 先更新、回测、跑 GitHub Actions，再同步给广州 nanobot 等其他实例。

### 设计原则

| 原则 | 说明 |
| --- | --- |
| 跟上游而不是吞上游 | 上游有的核心能力尽量复用；下游差异放在胶水层、配置层和 sidecar。 |
| 少常驻，多按需 | 浏览器、抓取、清洗、趋势分析等重活尽量按需或独立服务运行。 |
| 真实数据优先 | 系统状态、LOF、成本、cron、sidecar health 走真实脚本和 API，不让 LLM 乱猜。 |
| 成本可见 | OBP 记录来源、模型、免费/付费 token 和成本，方便控制 API 钱包。 |
| 安全默认收口 | 业务端口不公网直连；公网只走 Caddy/域名反代和认证策略。 |

## 当前架构

```text
QQ / WeChat / API clients
        |
        v
Nanobot core 0.2.x
  - chat loop / tools / memory / cron
  - QQ streaming output
  - direct ops replies for health/status questions
        |
        +---------------- internal tools / callbacks ----------------+
                                                                     |
Public web entry                                                     |
  Caddy :80/:443                                                     |
  auth / noindex / reverse proxy                                     |
        |                                                            |
        v                                                            |
127.0.0.1:8093 dashboard gateway                                     |
  /                 今日驾驶舱 / 能力总控台                           |
  /rss/             RSS、微信文章、Markdown 预览、付费文章清洗器       |
  /inbox            知识收件箱                                        |
  /lof              LOF / QDII 套利监控                               |
  /trends/          Trend Radar Lite                                  |
  /reflexio/        记忆与反思看板                                    |
  /obp/             OBP 管理页面                                      |
  /obp/v1           OpenAI-compatible API                             |
  /obp/anthropic/v1 Anthropic-compatible API                          |
        |
        +--> Rust / Python sidecars on loopback or container network
```

公网入口不要写死裸 IP。线上业务端口 `8000/8080/8081/8091/8092/8093/8094/8095` 默认不直接暴露，统一经 Caddy 反代和认证策略访问。

## 能力地图

| 层 | 组件 | 当前用途 |
| --- | --- | --- |
| 聊天入口 | QQ、微信、OpenAI-compatible API | 日常对话、图片理解、运维快捷问答、定时推送出口。 |
| 内容工作台 | RSS sidecar、知识收件箱、付费文章清洗器 | 微信/RSS 文章抓取、广告过滤、Markdown 预览、手动评分、删除、补读。 |
| 趋势雷达 | Trend Radar Lite | 多源热点采集、历史热搜、每日新闻简报、MCP 风格工具接口。 |
| 投资看板 | LOF sidecar | QDII/LOF 实时刷新、溢价连续统计、申赎门槛过滤、QQ 报告推送。 |
| 模型网关 | OBP | 模型组、fallback、emergency、OpenAI/Anthropic 兼容入口、来源和成本账本。 |
| 记忆系统 | Nanobot memory、Reflexio | 对话记忆、延迟压缩、记忆看板、反思数据保留。 |
| 运维守卫 | sidecarctl、ops guard、systemd timers | 服务自愈、备份、上游版本通知、OBP 预算告警、健康日报。 |
| 驾驶舱 | dashboard gateway | 今日重点、服务健康、任务状态、模型成本、能力矩阵、快速入口。 |

## 和上游有什么不同

这个 fork 的目标不是改掉 Nanobot，而是把它变成一个可长期运行的个人系统。

主要差异：

- QQ 渠道体验：流式输出、ack、媒体发送、图片/文本组合、超时和重复输出保护。
- WeChat/RSS/知识工作流：微信文章、RSS、飞书/普通链接收纳、文章评分、清洗和补读。
- Sidecar 化：LOF、OBP、Trend Radar、Notify、Reflexio、QQ bridge 等服务从主进程拆出。
- OBP 模型路由：按来源、任务类型、成本、fallback 和 emergency 做统一路由与审计。
- 运维闭环：`sidecarctl`、ops guard、备份 timer、自愈 timer、上游版本提醒和预算提醒。
- 生产安全：业务端口收口到 loopback/Caddy，secrets 不进 git，公开页面避免裸 IP 暴露。

## 本地快速开始

```bash
uv sync
uv run nanobot --config ~/.nanobot/config.json
uv run pytest tests/
```

只开发上游核心功能时，直接跑 Nanobot 测试即可。涉及 sidecar、真实推送、OBP、RSS、LOF 或线上定时任务时，需要在生产服务器或等价的本地服务环境中回测。

常用检查：

```bash
uv run ruff check nanobot tests --select F
uv run pytest tests/
```

## 生产部署形态

线上默认是 Podman + systemd + Caddy：

| 服务 | 说明 |
| --- | --- |
| `podman-nanobot-cage.service` | Nanobot 主容器。 |
| `lof-sidecar.service` | 8093 loopback 网关和 LOF 看板。 |
| `obp-rs.service` | OBP 模型网关。 |
| `podman-wechat-rss-sidecar.service` | RSS / 微信文章 sidecar。 |
| `notify-sidecar-rs.service` | 定时任务桥和推送调度。 |
| `qq-sidecar-rs.service` | QQ 消息出口桥。 |
| `trend-sidecar-rs.service` | Trend Radar Lite。 |
| `nanobot-reflexio-rs.service` | Reflexio 记忆看板。 |
| `nanobot-ops-heal.timer` | 低层自愈巡检。 |
| `nanobot-data-backup.timer` | 数据备份。 |

服务 registry 位于 `ops/config/sidecars.json`，驾驶舱和 `sidecarctl` 都从这里读取。

## 运维命令

```bash
sidecarctl status
sidecarctl doctor
sidecarctl stack
sidecarctl url rss
sidecarctl logs lof
sidecarctl restart notify
```

```bash
python3 ops/scripts/nanobot-ops-guard.py --mode heal --force-report
python3 ops/scripts/nanobot-ops-guard.py --mode backup --dry-run
python3 ops/scripts/nanobot-ops-guard.py --mode upstream --force-report
python3 ops/scripts/nanobot-ops-guard.py --mode obp-budget --force-report
```

```bash
/usr/local/sbin/rust-sidecar-maintain status
/usr/local/sbin/rust-sidecar-maintain build-install
/usr/local/sbin/rust-sidecar-maintain clean-targets
```

## OBP API

OBP 是统一模型入口，既服务默认 nanobot，也可以服务广州 nanobot 等其他实例。

OpenAI-compatible：

```text
POST https://<public-domain>/obp/v1/chat/completions
```

Anthropic-compatible：

```text
POST https://<public-domain>/obp/anthropic/v1/messages
```

认证方式由线上配置决定，支持 Basic Auth / Bearer Token。公开 README 不记录真实账号、密码、token、base URL 或 provider key。

OBP 记录：

- 请求来源，例如 `default-nanobot`、`guangzhou-nanobot`。
- 请求模型、实际模型、渠道、fallback 原因。
- token、缓存命中、免费/付费分类和成本。
- 月预算、熔断、backup 和 emergency 路径。

## 内容与信息工作流

| 功能 | 入口 | 说明 |
| --- | --- | --- |
| RSS 文章 | `/rss/` | 微信文章、鸭哥 AI 要闻、Markdown 预览、明暗模式。 |
| 付费文章清洗器 | `/rss/cleaner` | 面向手动复制的长文，规则清洗为 Markdown，可按需 LLM 精修。 |
| 知识收件箱 | `/inbox` | 链接收纳、抓取、摘要、评分、删除、手动校正。 |
| Trend Radar | `/trends/` | 热榜采集、历史榜、每日简报、过滤八卦噪声。 |
| 补读 | Nanobot 指令 | 对已抓取文章按原推送格式重新发送全文。 |

原则是：能规则处理就不调用模型；需要摘要/判断时优先走免费或低成本模型；真正复杂问题再升级。

## 上游同步流程

默认链路：

```bash
git fetch official --tags
git merge official/main
uv run ruff check nanobot tests --select F
uv run pytest tests/
git push exp HEAD:main
```

同步策略：

- 先在默认 nanobot 更新和回测。
- GitHub Actions 通过后再给其他实例升级。
- 不把线上 secrets、数据库、日志、真实 cron target、浏览器 cookie 放进 git。
- 如果上游改动和下游胶水冲突，优先保持上游核心结构，下游差异挪到 `ops/`、skill 或 sidecar。

## Secrets 和线上数据

不要提交：

- `/root/.nanobot/config.json` 中的真实密钥值。
- `/root/.nanobot/secrets/*.env`。
- runtime database、history、日志、cookie、真实 QQ/微信目标 ID。
- Rust `target/`、Podman image layer、临时备份和缓存。

建议配置方式：

```json
{
  "providers": {
    "custom": {
      "apiKey": "${NANOBOT_PROVIDER_API_KEY}"
    }
  }
}
```

真实值放在受限权限的 env 文件里，由 systemd / Podman 注入。

## 目录速览

```text
nanobot/                 Nanobot core and downstream compatibility patches
tests/                   Core regression tests
ops/                     Live-server sidecars, scripts, units and registry
ops/sources/             Source snapshots for Rust/Python sidecars
ops/systemd/             Systemd units and timers
ops/config/              Sidecar and capability registries
scripts/                 Local smoke/deploy/helper scripts
docs/                    Architecture notes and implementation docs
```

## 相关文档

- `docs/ARCHITECTURE.md`: 当前架构设计和边界。
- `docs/adr/`: 架构决策记录。
- `ops/README.md`: 线上 ops 层说明。
- `ops/docs/restore.md`: 恢复与备份说明。

## Upstream Credit

Nanobot is originally developed by [HKUDS](https://github.com/HKUDS). This fork exists because I use Nanobot as a real personal assistant and need a production-shaped layer around it.

## English Brief

`nanobot-exp` keeps Nanobot close to upstream while adding a private production layer for daily use.

### What This Fork Adds

- QQ/WeChat production channel fixes, including QQ streaming and media handling.
- Sidecar-based services for RSS, LOF/QDII monitoring, Trend Radar, Reflexio, Notify and OBP.
- A unified dashboard gateway served behind Caddy instead of exposing raw service ports.
- OBP model routing with OpenAI-compatible and Anthropic-compatible APIs, source tracking, fallback paths and cost accounting.
- Knowledge Inbox, article cleaning, RSS previews, daily briefs and full-article replay.
- Ops guardrails: backups, self-healing, upstream release checks, budget alerts and service registry tooling.

### Local Development

```bash
uv sync
uv run nanobot --config ~/.nanobot/config.json
uv run ruff check nanobot tests --select F
uv run pytest tests/
```

### Production Notes

- Public access should go through Caddy and a domain, not raw IP plus service port.
- Runtime secrets and data are excluded from git.
- Sidecars are tracked as reproducible source snapshots under `ops/sources/`.
- The default Nanobot instance is the staging ground before changes are pushed and rolled out to other instances.
