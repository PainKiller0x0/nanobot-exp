# Memory-RS Architecture

`memory-rs` is Nanobot's local, resource-light memory service. It keeps long
recall outside the core Nanobot loop so upstream updates do not overwrite the
feature.

## Data boundaries

- Confirmed memory: explicit preferences, decisions, and facts. A user message
  beginning with `记住` writes here immediately.
- Candidate memory: stable-looking preferences or decisions extracted from a
  completed user turn. Candidates stay in the review inbox until accepted.
- Episodes: compact user/assistant turn pairs for local retrieval.
- Knowledge index: knowledge-inbox titles, summaries, metadata, and keywords
  only. Article bodies are never copied into the memory database.

Each row has scope, source, channel, session key, timestamp, confidence, and
status. Default and Guangzhou deployments use different scopes and databases.

## Retrieval and safety

The Rust service uses SQLite and local Chinese character n-grams. Retrieval is
local and should remain under 50 ms; no embedding API or LLM is called on the
chat hot path.

The Python `AgentHook` queries only on the first agent iteration and appends at
most seven results to the latest user message as an explicitly *untrusted*
reference block. It never places recalled content in the system prompt. Tool
output, webpage content, and article bodies are not candidates for persona
memory. Recording happens in a background task and failures are ignored so a
memory outage cannot delay a reply.

## Operations

- Service: `memory-rs.service`, loopback only on `127.0.0.1:8105`.
- Public dashboard route: `/memory/` through the existing LOF/Caddy path.
- Knowledge sync: `memory-knowledge-sync.timer` every 15 minutes.
- Upgrade check: `ops/scripts/install-memory-bridge.py --check` validates the
  upstream hook anchors before a Nanobot restart.
- Rollback: `ops/scripts/rollback-memory-rs.py`; add `--restore-legacy` only
  when the old Reflexio service and dashboard registry must be restored.

The legacy Reflexio database is retained read-only at
`/root/.nanobot/data/reflexio/reflexio.db` and imported with source label
`legacy-reflexio`.
