# Runtime Patch Scripts

These scripts keep `nanobot` core close to upstream by applying runtime changes via generated glue files.

## Scripts

- `scripts/apply_slim_profile.sh`
- `scripts/apply_reflexio_glue.sh`
- `scripts/memory_report.sh`

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

## 3) Memory Report

```bash
scripts/memory_report.sh
```

Shows host/container/process memory in one report.

## Rollback

Use base compose only:

```bash
docker compose -f docker-compose.yml up -d nanobot-gateway nanobot-api
```

The generated files are overlays and can be deleted safely.