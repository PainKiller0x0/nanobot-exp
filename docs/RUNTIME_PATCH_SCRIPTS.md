# Runtime Patch Scripts

These scripts keep `nanobot` core close to upstream by applying runtime changes via generated glue files.

## Scripts

- `scripts/apply_slim_profile.sh`
- `scripts/apply_reflexio_glue.sh`
- `scripts/memory_report.sh`
- `scripts/apply_runtime_profiles.sh`
- `scripts/rollback_runtime_profiles.sh`
- `scripts/apply_wechat_rss_rs.sh`

## 1) Container Slim Profile

Generate low-risk runtime tuning overlays:

```bash
scripts/apply_slim_profile.sh
```

Outputs:

- `~/.nanobot/runtime-slim.env`
- `./docker-compose.slim.yml`

Apply during maintenance window:

```bash
docker compose -f docker-compose.yml -f docker-compose.slim.yml up -d nanobot-gateway nanobot-api
```

## 2) Reflexio Glue Profile

Generate reflexio runtime env and compose override:

```bash
scripts/apply_reflexio_glue.sh --url http://127.0.0.1:8081
```

Outputs:

- `~/.nanobot/reflexio.env` (shell)
- `~/.nanobot/reflexio.compose.env` (compose)
- `./docker-compose.reflexio.yml`

Apply during maintenance window:

```bash
docker compose -f docker-compose.yml -f docker-compose.reflexio.yml up -d nanobot-gateway nanobot-api
```

## 3) Runtime Wrapper

Generate both profiles in one command:

```bash
scripts/apply_runtime_profiles.sh
```

Apply both immediately:

```bash
scripts/apply_runtime_profiles.sh --apply
```

## 4) Memory Report

```bash
scripts/memory_report.sh
```

Shows host/container/process memory in one report.

## 5) WeChat RSS Rust Migration (Guarded)

```bash
scripts/apply_wechat_rss_rs.sh
```

Behavior:

- Builds a local Rust image (`wechat-rss-rs:local`).
- Refuses to migrate if Rust app still looks like a placeholder (`Hello, world!`) unless `--force` is set.
- Supports `--apply` for live switch with backup container and rollback path.

Example:

```bash
scripts/apply_wechat_rss_rs.sh --apply
```

## Rollback

Use base compose only:

```bash
scripts/rollback_runtime_profiles.sh
```

Optional cleanup of generated overlay files:

```bash
scripts/rollback_runtime_profiles.sh --clean-files
```

The generated files are overlays and can be deleted safely.