# nanobot-exp 架构设计

本文档描述 `nanobot-exp` 当前线上实现。它不是愿景文档，而是为了后续改动时能快速判断边界、风险和回滚方式。

## 目标

`nanobot-exp` 是基于上游 `HKUDS/nanobot` 的个人线上 fork。核心规则是：

> Nanobot 本体尽量贴近上游，个人产品、定时任务、看板和集成尽量放到 sidecar 或 skill。

架构目标：

- `nanobot/` 保持小而清晰，方便继续合并上游。
- 长期运行的个人业务逻辑不塞进 Python core。
- 小内存 VPS 上优先使用 Rust sidecar。
- 公网只保留一个 Web 入口。
- secret、日志、数据库、真实 cron 目标和运行态数据不进 Git。
- 每个服务都能独立重启、独立回测、独立回滚。

## 运行拓扑

```text
                         public internet
                              |
                              v
                    http://<host>:8093
                  LOF dashboard + reverse proxy
                              |
       +----------------------+----------------------+
       |          |           |          |           |
     /rss/    /reflexio/    /obp/    /trends/   /sidecars
       |          |           |          |           |
  RSS sidecar  Reflexio   OBP bridge  Trend     manager API
  127.0.0.1    127.0.0.1  127.0.0.1   Radar     same process
  :8091        :8081      :8000       :8095

  Nanobot core 和内部桥接不直接暴露公网：

  nanobot-cage          127.0.0.1:8080    Podman
  qq-sidecar-rs         172.17.0.1:8092   systemd, Podman bridge 可访问
  notify-sidecar-rs     127.0.0.1:8094    systemd
```

只有 `lof-sidecar-rs` 作为公网入口。它负责：

- `/` 和 `/lof`：LOF/QDII 看板。
- `/sidecars` 和 `/api/sidecars`：服务矩阵。
- `/rss/`、`/reflexio/`、`/obp/`、`/trends/`：反代到内部 sidecar。

`podman-port-forward-allow.service` 是公网端口守卫。预期端口策略是：

- 公网开放：`8093`，以及 SSH 和云厂商必要管理端口。
- 仅本机或容器桥接：`8000`、`8080`、`8081`、`8091`、`8092`、`8094`、`8095`。

## 服务矩阵

服务注册表以 `ops/config/sidecars.json` 为准。线上运行副本在 `/root/.nanobot/sidecars.json`。

| ID | 服务 | 运行方式 | 端口 | 公网路径 | 职责 |
|---|---|---:|---:|---|---|
| `nanobot` | Nanobot Core | Podman | `8080` | 无 | QQ/WeChat 入口、agent loop、dream |
| `rss` | RSS Sidecar | Podman | `8091` | `/rss/` | 微信文章、鸭哥 AI、Markdown 预览、广告过滤 |
| `qq` | QQ Bridge | systemd | `8092` | 无 | QQ API 直连探测、签名发送支持 |
| `lof` | LOF Dashboard | systemd | `8093` | `/` | QDII/LOF 看板、公网反代、服务总控 |
| `notify` | Notify Bridge | systemd | `8094` | 无 | cron 调度、重试状态、QQ 通知分发 |
| `trend` | Trend Radar | systemd | `8095` | `/trends/` | NewsNow 热榜、搜索、话题分析、MCP 风格工具 |
| `reflexio` | Reflexio | systemd | `8081` | `/reflexio/` | 记忆和反思看板 |
| `obp` | OBP Bridge | systemd | `8000` | `/obp/` | 兜底桥、回调和控制台 |
| `podman-public-rule` | Port Guard | systemd | n/a | 无 | 阻断旧业务端口公网访问 |

## 目录布局

```text
nanobot-exp/
  nanobot/                         上游核心，尽量少改
  scripts/                         上游友好的运行时补丁脚本
  docs/                            用户文档和架构文档
  ops/
    config/sidecars.json           脱敏后的服务注册表
    config/notify-sidecar-rs/
      config.example.json          示例配置，不含真实 QQ 目标 ID
    bin/sidecarctl                 日常运维 CLI
    scripts/deploy-sidecar.sh      构建、安装、重启、状态检查入口
    sbin/                          主机辅助脚本
    systemd/                       systemd unit 和 drop-in
    sources/
      _shared/                     skill 客户端共享 Python helper
      *-rs/                        Rust sidecar 源码快照
      *-assistant/                 Nanobot skill 源码快照
```

线上还有 `/root/nanobot-ops`，这是实际运维工作副本，`/usr/local/sbin/deploy-sidecar` 默认从这里构建和部署。
GitHub 里的 `ops/` 是它的脱敏快照。

## 部署模型

部署链路保持简单：

```text
修改 /root/nanobot-ops 源码
        |
        v
deploy-sidecar <target>
        |
        +-- Rust sidecar: cargo build --release + install 到 /usr/local/bin
        +-- RSS sidecar: podman build + restart local image
        |
        v
systemd restart + health check
```

常用命令：

```bash
deploy-sidecar all --status
deploy-sidecar lof
deploy-sidecar trend
sidecarctl status
sidecarctl logs lof
sidecarctl restart notify
systemctl status nanobot-stack.target
```

`nanobot-stack.target` 用轻量 `PartOf=` drop-in 把服务分组。它只是 systemd 分组，不是调度系统，也不是 k8s。

## 数据和状态归属

边界必须清楚：

- Git 保存代码、文档、示例配置、systemd unit 和部署胶水。
- `/root/.nanobot` 保存运行配置、workspace skills、sidecar 状态、RSS 数据库和 secrets。
- `/root/.nanobot/secrets/*.env` 保存凭据和代理认证材料。
- Rust `target/`、日志、SQLite 数据库、真实 notify 配置不提交。

| 数据 | 归属 | 是否进 Git |
|---|---|---|
| QQ app secret | `/root/.nanobot/config.json` 或 secrets env | 不提交 |
| Notify 目标 ID | 线上 `config.json` | 不提交 |
| Notify 示例配置 | `ops/config/notify-sidecar-rs/config.example.json` | 提交 |
| Trend cache | `/root/.nanobot/data/trend-sidecar/state.json` | 不提交 |
| RSS DB | live sidecar volume/workspace | 不提交 |
| Sidecar 源码 | `ops/sources/*` | 提交 |

## Nanobot Core 边界

Nanobot core 应该负责：

- 聊天入口和出口。
- Agent loop、LLM/tool 编排。
- 很难外置的小型路由胶水。
- 调用本地 sidecar API 和 skill 脚本。

Nanobot core 不应该负责：

- RSS 抓取和文章存储。
- QDII/LOF 行情抓取。
- Cron 执行和 retry 状态。
- 热榜新闻采集。
- Web dashboard。
- 长期运行的个人业务逻辑。

如果一个功能可以表达为 `HTTP API + CLI/script + dashboard`，通常应该做成 sidecar 或 skill，而不是继续改 core。

## Skills 和公共 helper

个人 skill 的源码快照放在 `ops/sources/*`，线上运行副本在 workspace。

共享 Python helper：

```text
ops/sources/_shared/ops_common.py
```

当前提供：

- `JsonHttpClient`：base URL fallback、JSON GET/POST、文本请求。
- `parse_dt`、`fmt_time`、`now_shanghai`。
- `short`：适合 QQ 输出的短文本截断。

这样 `trend-radar`、`personal-ops-assistant`、`wechat-rss-sidecar-skill` 不需要各自复制 HTTP fallback 和时间解析逻辑。

抽取原则：

- 通用 IO、时间、短文本 helper 放 `_shared`。
- 业务格式化留在各自 skill。
- 不把 secret、真实目标 ID、机器私有状态塞进共享代码。

## Sidecar 职责

### `lof-sidecar-rs`

- `8093` 公网入口。
- LOF/QDII 看板、报告、历史溢价视图。
- 内部 sidecar 反代。
- 服务矩阵和健康聚合。

### `wechat-rss-rs`

- RSS 订阅管理。
- 微信文章和鸭哥 AI 抓取。
- Markdown 预览。
- LLM 设置和广告过滤。
- 用 Podman 隔离 RSS 运行环境。

### `notify-sidecar-rs`

- cron-like 调度。
- retry/timeout 状态。
- 通过 QQ bridge 或 Nanobot 配置分发通知。
- 把循环任务从 Nanobot core 内存里拿出去。

### `trend-sidecar-rs`

- NewsNow 热榜采集。
- 本地缓存和自动刷新。
- 搜索、话题分析、摘要 API。
- `/trends/mcp` 下提供 MCP 风格 JSON-RPC 工具。

### `qq-sidecar-rs`

- 轻量 QQ API 桥。
- 直连发送健康探测。
- 给 notify 脚本提供稳定本地目标。

### `nanobot-reflexio-rs`

- Reflexio 风格记忆/反思看板。
- 有独立 Web 和数据生命周期，所以不放 core。

### `obp-rs`

- OpenAI-compatible/failover 桥和回调控制台。
- 公网访问必须经 `8093/obp`，并保留认证或网络限制。

## MCP 和 AI 分析路径

当前 MCP-like 路径优先本地化：

```text
Trend Radar sidecar
  /api/trends/*
  /api/mcp/tools
  /mcp
        |
        v
Nanobot skill 或 LLM call
        |
        v
QQ 回复 / dashboard 摘要
```

这样可以先获得 MCP 能力形态，又不引入重型 MCP server stack。
如果未来需要外部 MCP client，再优先加认证和内网监听，不要直接裸露公网。

## 当前实现 review

方向是对的：

- core/sidecar 拆分已经形成，个人功能大多离开 `nanobot/`。
- Podman 迁移后，常驻内存比 Docker 低。
- 服务矩阵和 `sidecarctl` 让 health/log/restart 有统一入口。
- Trend Radar 提供新闻采集和 MCP 风格工具，但没有把重 Python 服务塞进 core。
- `_shared/ops_common.py` 已经减少 skill 客户端重复代码。

主要技术债：

- `lof-sidecar-rs` 仍然偏大，一个文件里同时有 dashboard、LOF 逻辑、反代和服务管理。
- `wechat-rss-rs` 偏大，UI、settings、crawler、DB、LLM test endpoint 混在一起。
- `ops/` 快照和 `/root/nanobot-ops` 线上工作副本可能漂移，需要把 sync/commit 变成习惯。
- `/obp/` 和未来 MCP 入口的认证边界要继续显式维护，不能为了方便把 admin 面裸露出去。
- 部分 systemd unit 指向 `/root/.nanobot` 线上路径，这是设计选择，但恢复环境时必须先恢复 workspace 和 secrets。

建议下一步重构：

1. Rust sidecar 的大块 HTML/CSS 如果继续增长，拆到 `static` 或 `include_str!` 文件。
2. `lof-sidecar-rs` 如果继续加功能，把 reverse proxy、service manager、LOF domain 分 module。
3. `wechat-rss-rs` 拆 DB、settings、crawler、LLM client 模块。
4. 增加 `ops/scripts/check-architecture.sh`，检查 sidecars registry、systemd unit、文档端口是否一致。
5. 新个人自动化默认采用 `skill + sidecar API`，除非确实必须改 Nanobot core。

## 变更 checklist

新增功能时按这个顺序判断：

1. 先定边界：core、skill、sidecar、script。
2. 如果长期运行或拥有数据，优先 sidecar。
3. 受管理服务必须写入 `sidecars.json`。
4. 增加 health endpoint 和 `deploy-sidecar` 支持。
5. secret 和 live data 不进 Git。
6. sidecar API 稳定后，再加 skill 或 QQ fast path。
7. 回测：

```bash
deploy-sidecar <target>
deploy-sidecar all --status
python3 -m py_compile <changed-python-scripts>
cargo check --offline --manifest-path <changed-rust-sidecar>/Cargo.toml
```

8. 只要服务图或边界变化，就同步更新本文档。
