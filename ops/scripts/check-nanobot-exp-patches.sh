#!/usr/bin/env bash
set -euo pipefail

REPO="${1:-/root/nanobot}"
WORKSPACE_ROOT="${NANOBOT_WORKSPACE_ROOT:-/root/.nanobot/workspace}"
fail=0

check() {
  local file="$1" pattern="$2" label="$3"
  if grep -qF "$pattern" "$REPO/$file" 2>/dev/null; then
    printf 'ok   %s\n' "$label"
  else
    printf 'MISS %s (%s)\n' "$label" "$file" >&2
    fail=1
  fi
}

check 'ops/sources/hermes-check/hermes_check.py' 'SIDECAR_STATUS_API' 'HERMES sidecar manager health check'
check 'ops/sources/qdii-monitor/send_qq.py' 'run_fresh_report' 'LOF refresh-before-send wrapper'
check 'ops/systemd/nanobot-llm-warmup.service' 'nanobot.agent.warmup' 'Nanobot LLM warmup systemd unit'
check 'ops/systemd/drop-ins/podman-nanobot-cage.service.d/20-llm-warmup.conf' 'nanobot-llm-warmup.service' 'Nanobot warmup service hook'
check 'nanobot/agent/warmup.py' 'select_warmup_sessions' 'Agent warmup CLI'
check 'nanobot/exp/agent/obp_fallback.py' 'OBPFallbackClient' 'Agent OBP fallback helper'
check 'nanobot/agent/direct_reply.py' 'system_reply.format_memory_report' 'Agent direct reply system seam'
check 'nanobot/agent/direct_reply_intents.py' 'can_direct_ack' 'Agent direct reply intent matcher'
check 'nanobot/agent/system_reply.py' 'format_memory_report' 'Agent direct system reply helper'
check 'nanobot/agent/capability_registry.py' 'load_capabilities' 'Agent capability registry helper'
check 'nanobot/agent/capability_snapshot.py' 'dashboard_snapshot' 'Agent capability dashboard snapshot helper'
check 'nanobot/agent/capability_formatters.py' 'format_today_brief' 'Agent capability reply formatter'
check 'nanobot/agent/inbox_tool.py' 'run_tool' 'Agent knowledge inbox tool runner'
check 'nanobot/agent/inbox_intents.py' 'extract_inbox_intent' 'Agent knowledge inbox intent matcher'
check 'nanobot/agent/memory_client.py' 'save_memory' 'Agent Reflexio memory client helper'
check 'nanobot/agent/memory_intents.py' 'extract_memory_to_save' 'Agent memory intent matcher'
check 'nanobot/agent/memory_formatters.py' 'format_memory_status' 'Agent memory reply formatter'
check 'ops/sources/memory-rs/memory_bridge.py' 'class MemoryHook' 'memory-rs bridge source'

if ! git -C "$REPO" ls-files --error-unmatch ops/sources/memory-rs/memory_bridge.py >/dev/null 2>&1; then
  printf "MISS memory-rs canonical source is not tracked by git\n" >&2
  fail=1
else
  printf "ok   memory-rs canonical source is tracked\n"
fi
if ! cmp -s "$REPO/ops/sources/memory-rs/memory_bridge.py" "$REPO/nanobot/exp/agent/memory_bridge.py"; then
  printf "MISS installed memory bridge differs from canonical source\n" >&2
  fail=1
else
  printf "ok   installed memory bridge matches canonical source\n"
fi
if grep -qF 'from nanobot.exp.agent.memory_bridge import build_memory_hook' "$REPO/nanobot/cli/gateway_runtime.py" 2>/dev/null \
  && grep -qF 'hooks=[_MCPReadinessHook(mcp_provider), build_memory_hook()]' "$REPO/nanobot/cli/gateway_runtime.py" 2>/dev/null; then
  printf "ok   memory-rs gateway hook composition\n"
elif grep -qF 'build_memory_hook' "$REPO/nanobot/cli/commands.py" 2>/dev/null; then
  printf "ok   memory-rs legacy command hook composition\n"
else
  printf "MISS memory-rs hook composition (gateway_runtime.py)\n" >&2
  fail=1
fi
check 'nanobot/channels/qq/runtime.py' 'from nanobot.exp.qq import stream_runtime as qq_stream_runtime' 'QQ downstream helper seam'
check 'nanobot/exp/qq/streaming.py' 'should_stream_text' 'QQ streaming policy helper'
check 'nanobot/exp/qq/stream_runtime.py' 'send_delta' 'QQ streaming runtime helper'
check 'nanobot/exp/qq/article_requests.py' 'parse_yage_selector' 'QQ article request helper'
check 'nanobot/exp/qq/article_handlers.py' 'try_handle_wechat_grounded' 'QQ article intent handler'
check 'nanobot/exp/qq/article_runtime.py' 'run_wechat_signed' 'QQ article runtime adapter'
check 'nanobot/exp/qq/gateway_greeting.py' 'build_restart_greeting' 'QQ gateway greeting helper'
check 'nanobot/exp/qq/local_commands.py' 'run_personal_ops_command' 'QQ local command runner'
check 'nanobot/exp/qq/local_handlers.py' 'try_handle_personal_ops_query' 'QQ local command handler'
check 'nanobot/exp/qq/fast_paths.py' 'match_personal_ops_command' 'QQ fast path helper'
check 'nanobot/exp/qq/signatures.py' 'verify_and_unwrap_signed_payload' 'QQ signed payload helper'
check 'nanobot/exp/qq/signed_delivery.py' 'prepare_outbound_content' 'QQ signed delivery policy'
check 'nanobot/exp/qq/rss_sidecar.py' 'run_client_json' 'QQ RSS sidecar rust adapter'
check 'nanobot/exp/qq/rss_sidecar.py' 'ack_wechat_delivery' 'QQ RSS sidecar ACK adapter'
check 'ops/sources/wechat-rss-rs/src/qq_rss_api.rs' 'wechat_ack' 'RSS sidecar WeChat ACK API'
check 'ops/sources/wechat-rss-rs/src/qq_article_format.rs' 'format_article_push_body' 'RSS sidecar QQ article formatter'
check 'ops/sources/wechat-rss-rs/src/qq_extractive_qa.rs' 'extractive_answer' 'RSS sidecar extractive QA helper'
check 'ops/sources/wechat-rss-rs/src/qq_rss_api.rs' 'yage_ack' 'RSS sidecar Yage ACK API'
check 'ops/sources/homeassistant-climate/homeassistant_climate.py' 'class HomeAssistantClimateControlTool' 'restricted Shenzhen climate bridge source'
check 'ops/sources/homeassistant-climate/SKILL.md' 'home_assistant_shenzhen_climate_control' 'Home Assistant climate skill source'
check 'ops/scripts/install-ha-climate-bridge.py' 'patched_gateway' 'Home Assistant climate bridge installer'
check 'nanobot/exp/agent/homeassistant_climate.py' 'class HomeAssistantClimateControlTool' 'installed Shenzhen climate bridge'
if ! cmp -s "$REPO/ops/sources/homeassistant-climate/homeassistant_climate.py" "$REPO/nanobot/exp/agent/homeassistant_climate.py"; then
  printf "MISS installed climate bridge differs from canonical source\n" >&2
  fail=1
else
  printf "ok   installed climate bridge matches canonical source\n"
fi
if ! cmp -s "$REPO/ops/sources/homeassistant-climate/SKILL.md" "$WORKSPACE_ROOT/skills/home-assistant/SKILL.md"; then
  printf "MISS installed Home Assistant skill differs from canonical source\n" >&2
  fail=1
else
  printf "ok   installed Home Assistant skill matches canonical source\n"
fi
if grep -qF 'from nanobot.exp.agent.homeassistant_climate import (' "$REPO/nanobot/cli/gateway_runtime.py" \
  && grep -qF 'tools.register(HomeAssistantClimateControlTool())' "$REPO/nanobot/cli/gateway_runtime.py"; then
  printf "ok   restricted climate tool gateway registration\n"
else
  printf "MISS restricted climate tool gateway registration\n" >&2
  fail=1
fi
exit "$fail"
