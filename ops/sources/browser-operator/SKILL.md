---
name: browser-operator
description: 按需启动真实浏览器执行网页访问、登录态读取、页面截图和轻量交互。仅在用户明确要求“打开网页/用浏览器/截图/登录态/点击填写”时使用。
metadata:
  nanobot:
    always: false
---

# Browser Operator

这个 skill 为 nanobot 提供按需浏览器能力，底层优先使用 `bb-browser`。

## 使用边界

- 默认不要用浏览器处理普通公开网页摘要；公开文章优先使用 `knowledge-inbox`、RSS sidecar 或普通 fetch。
- 只有用户明确要求浏览器行为时才使用：打开网页、截图、登录态页面、点击、填写表单、执行 JS、需要浏览器渲染后的内容。
- 不做常驻服务，不主动启动 MCP server。每次按需调用，任务完成后关闭 tab；文本/截图类任务默认杀掉 bb-browser 专用 Chrome。
- 不读取或输出浏览器 Cookie、localStorage、token、密码字段。
- 不执行支付、转账、发帖、删除、关注、下单等有副作用操作，除非用户在当前对话里明确确认。
- 遇到登录页面时，说明需要用户手动登录一次；不要尝试猜密码。

## 常用命令

检查依赖和是否有残留浏览器进程：

```bash
python3 /root/.nanobot/workspace/skills/browser-operator/browser_once.py check
```

读取渲染后的页面正文，任务结束后自动关闭 tab 并杀掉专用 Chrome：

```bash
python3 /root/.nanobot/workspace/skills/browser-operator/browser_once.py quick-text "https://example.com" --limit 8000
```

截图，任务结束后自动清理浏览器进程：

```bash
python3 /root/.nanobot/workspace/skills/browser-operator/browser_once.py screenshot "https://example.com" /tmp/example.png
```

执行单个 bb-browser 命令：

```bash
python3 /root/.nanobot/workspace/skills/browser-operator/browser_once.py run -- open "https://example.com"
python3 /root/.nanobot/workspace/skills/browser-operator/browser_once.py run -- snapshot -i
python3 /root/.nanobot/workspace/skills/browser-operator/browser_once.py run -- eval "document.title"
python3 /root/.nanobot/workspace/skills/browser-operator/browser_once.py run -- close
```

如果只是一次性执行，并希望结束后释放内存：

```bash
python3 /root/.nanobot/workspace/skills/browser-operator/browser_once.py run --kill-browser-after -- get title
```

## 安装依赖

如果 `check` 显示缺少 Node/npm/Chromium/bb-browser，先不要临时乱装。使用专门脚本：

```bash
bash /root/.nanobot/workspace/skills/browser-operator/setup_bb_browser.sh
```

安装后再次运行 `check`。第一次访问需要登录的网站时，bb-browser 会启动专用 Chrome profile：`~/.bb-browser/browser/`。登录态保存在这个专用 profile 里。

## 触发建议

- 用户说“用浏览器打开 / 帮我截图 / 页面渲染后是什么 / 登录后看一下”时使用。
- 用户说“抓这个链接正文”但普通抓取失败，可以使用 `quick-text` 兜底。
- 需要多步点击时，按 `open -> snapshot -i -> click/fill -> snapshot -> close` 执行。
- 每次多步任务结束必须调用 `close`，必要时再运行 `browser_once.py cleanup` 释放内存。
