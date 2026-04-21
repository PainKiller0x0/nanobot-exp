# Quick Start (nanobot-exp) / 快速开始（nanobot-exp）

This page provides the shortest usable setup for nanobot-exp.

本页提供 nanobot-exp 的最短可用配置路径。

## 1. Install / 安装

```bash
git clone https://github.com/PainKiller0x0/nanobot-exp.git
cd nanobot-exp
pip install -e .
```

## 2. Initialize Config / 初始化配置

```bash
nanobot onboard
```

Default config path / 默认配置路径：

- Linux/macOS: `~/.nanobot/config.json`

## 3. Configure Model and API Key / 配置模型与 API Key

Edit `~/.nanobot/config.json` with at least:

编辑 `~/.nanobot/config.json`，至少包含：

```json
{
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-v1-xxx"
    }
  },
  "agents": {
    "defaults": {
      "provider": "openrouter",
      "model": "anthropic/claude-opus-4-5"
    }
  }
}
```

## 4. Start Chat / 启动对话

```bash
nanobot agent
```

## 5. Install External Extensions (Optional) / 安装外挂扩展（可选）

nanobot-exp recommends keeping custom features in a separate extension repo:

nanobot-exp 建议将自定义功能放在独立扩展仓库：

```bash
scripts/install_extentions.sh \
  --repo git@github.com:YOUR_ORG/nanobot-extensions.git \
  --ref v0.3.1 \
  --modules extensions.reflexio

source ~/.nanobot/extensions.env
```

Tips / 提示：

- `--ref` supports branch/tag/commit.
- `--ref` 支持 branch/tag/commit。
- The installer writes `~/.nanobot/extensions.lock` for rollback and auditing.
- 安装器会写入 `~/.nanobot/extensions.lock`，用于回滚和审计。

Then restart nanobot.

然后重启 nanobot。

## 6. Fast Smoke Check / 快速冒烟检查

Before push/deploy, run:

在 push / 部署前运行：

```bash
scripts/run_smoke.sh
```

## 7. Useful Commands / 常用命令

```bash
nanobot --help
nanobot channels --help
nanobot gateway --help
```

## 8. Troubleshooting / 故障排查

- Config error: validate JSON format in `~/.nanobot/config.json`.
- 配置报错：检查 `~/.nanobot/config.json` 是否为合法 JSON。
- Provider error: verify API key and provider/model match.
- Provider 报错：确认 API key 与 provider/model 匹配。
- Extension not loaded: confirm `source ~/.nanobot/extensions.env` and check `PYTHONPATH` / `NANOBOT_EXTENSION_MODULES`.
- 扩展未加载：确认执行了 `source ~/.nanobot/extensions.env`，并检查 `PYTHONPATH` / `NANOBOT_EXTENSION_MODULES`。

More extension details / 扩展细节： [EXTENSIONS_GLUE.md](./EXTENSIONS_GLUE.md)