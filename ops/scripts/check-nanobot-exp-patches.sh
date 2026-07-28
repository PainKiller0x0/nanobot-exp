#!/usr/bin/env bash
set -euo pipefail

REPO="${1:-/root/nanobot}"
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

check 'nanobot/config/schema.py' 'delivery_channel: str | None = None' 'heartbeat delivery_channel schema'
check 'nanobot/config/schema.py' 'delivery_chat_id: str | None = None' 'heartbeat delivery_chat_id schema'
check 'nanobot/cli/commands.py' 'fixed_channel=hb_cfg.delivery_channel' 'heartbeat fixed target routing'
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
check 'nanobot/exp/agent/memory_bridge.py' 'class MemoryHook' 'memory-rs bridge source'

if ! git -C "$REPO" ls-files --error-unmatch nanobot/exp/agent/memory_bridge.py >/dev/null 2>&1; then
  printf "MISS memory-rs bridge source is not tracked by git\n" >&2
  fail=1
else
  printf "ok   memory-rs bridge source is tracked\n"
fi
check 'nanobot/cli/commands.py' 'build_memory_hook' 'memory-rs hook composition'
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
exit "$fail"
