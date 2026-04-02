# 快速上手 / Quick Start

> 本 fork 地址：[PainKiller0x0/nanobot](https://github.com/PainKiller0x0/nanobot)
> 基于上游 [HKUDS/nanobot](https://github.com/HKUDS/nanobot) v0.1.4.post6，rebase 到 v0.2.0

---

## 一、安装 / Installation

```bash
# 克隆本仓库
git clone https://github.com/PainKiller0x0/nanobot.git
cd nanobot

# 安装（开发模式，可编辑）
pip install -e .

# 或者从 PyPI 安装稳定版
pip install nanobot-ai
```

> **要求：** Python 3.11+，建议使用虚拟环境：
> ```bash
> python3.11 -m venv .venv && source .venv/bin/activate
> pip install -e .
> ```

---

## 二、配置 API Key / Configure API Key

```bash
# 复制配置模板
cp nanobot.yaml.example nanobot.yaml
# 编辑 nanobot.yaml，填入你的 API key
```

`nanobot.yaml` 至少需要配置：

```yaml
# nanobot.yaml（此文件不要提交！已在 .gitignore 中）

agents:
  defaults:
    model: anthropic/claude-sonnet-4-5     # 选择你的模型

providers:
  anthropic:
    api_key: sk-ant-api03-xxxxx            # 填入你的 API key
```

> **获取 API Key：**
> - Anthropic: https://console.anthropic.com/
> - OpenAI: https://platform.openai.com/api-keys
> - DeepSeek: https://platform.deepseek.com/
> - 更多 provider 见 `nanobot.yaml.example`

---

## 三、启动（选一种渠道）/ Start a Channel

### A — QQ（OneBot v11）

需要一个小号 + go-cqhttp（或 Lagrange）在本地运行。

```yaml
# nanobot.yaml
channels:
  qq:
    enabled: true
    app_id: 123456789        # QQ 开放平台申请
    secret: xxxxxx            # QQ 开放平台申请
    ws_url: ws://127.0.0.1:8080/ws
```

详细配置见 [QQ 频道配置指南](https://github.com/HKUDS/nanobot#-qq)。

### B — 微信（个人号，实验性）

```bash
pip install "nanobot-ai[weixin]"
```

```yaml
# nanobot.yaml
channels:
  weixin:
    enabled: true
```

首次启动会弹出二维码，扫码后 token 自动保存。

### C — Telegram

```yaml
# nanobot.yaml
channels:
  telegram:
    enabled: true
    bot_token: 123456:ABC-xxxxx   # @BotFather 获取
```

### D — CLI（无需配置渠道）

```bash
nanobot chat
```

直接在终端交互，只需配置模型，无需渠道 API key。

### E — Web/API 接口

```bash
pip install "nanobot-ai[api]"
nanobot api
# → http://localhost:18790
```

---

## 四、运行 / Launch

```bash
# 启动 gateway（所有已启用的渠道）
nanobot gateway

# 或交互式配置向导
nanobot configure
```

---

## 五、安装渠道依赖（可选）/ Optional Channel Dependencies

```bash
pip install "nanobot-ai[qq]"       # QQ 支持
pip install "nanobot-ai[weixin]"   # 微信支持
pip install "nanobot-ai[wecom]"    # 企业微信支持
pip install "nanobot-ai[matrix]"   # Matrix 支持
```

---

## 六、同步上游更新 / Sync Upstream

```bash
# 添加上游仓库
git remote add upstream https://github.com/HKUDS/nanobot.git

# 拉取上游更新
git fetch upstream
git rebase upstream/main   # 或 git merge upstream/main
```

---

## 常见问题 / Troubleshooting

| 问题 | 解决 |
|------|------|
| `ModuleNotFoundError` | 重新执行 `pip install -e .` |
| 渠道无法连接 | 检查防火墙 / webhook URL |
| 模型无响应 | 确认 `nanobot.yaml` 中 API key 正确 |
| 内存占用高 | 在配置中减小 `context_window_tokens` |

更多配置选项和高级功能，见完整 [README.md](README.md)。
