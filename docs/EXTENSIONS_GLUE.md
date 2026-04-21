# Extensions Glue Install

Keep `nanobot` core clean and install custom extensions at deployment time.

## Script

Use this installer:

```bash
scripts/install_extentions.sh
```

## Recommended Pinning

Use `--ref` with a release tag or commit SHA for stable deploys.

```bash
scripts/install_extentions.sh \
  --repo git@github.com:YOUR_ORG/nanobot-extensions.git \
  --ref v0.3.1 \
  --modules extensions.reflexio

source ~/.nanobot/extensions.env
cat ~/.nanobot/extensions.lock
```

## What it does

1. Pulls extension source into `~/.nanobot/extensions-runtime/src`.
2. Resolves `--ref` as branch/tag/commit.
3. If the repo is a Python package, runs editable install.
4. Generates `~/.nanobot/extensions.env` with runtime exports.
5. Generates `~/.nanobot/extensions.lock` with resolved commit metadata.

## Output Variables

The env file can include:

- `PYTHONPATH`
- `NANOBOT_PROVIDER_FAILOVER_MODULE` (auto when `extensions/provider_failover` exists)
- `NANOBOT_EXTENSION_MODULES` (when `--modules` is provided)
- `NANOBOT_EXTENSIONS_REPO`
- `NANOBOT_EXTENSIONS_REF`
- `NANOBOT_EXTENSIONS_COMMIT`
- `NANOBOT_EXTENSIONS_VERSION`

## Service / Docker usage

- Systemd/shell startup: `source ~/.nanobot/extensions.env` before running nanobot.
- Docker Compose: add this file as `env_file` or copy exports into `environment`.

## Rollback

Reinstall to a previous tag/commit:

```bash
scripts/install_extentions.sh \
  --repo git@github.com:YOUR_ORG/nanobot-extensions.git \
  --ref <old_tag_or_commit>
```

## Split principle

- Keep core runtime files in `nanobot/` as close to upstream as possible.
- Keep custom logic in an external extensions repository.
- Connect core and custom logic at deployment time via `scripts/install_extentions.sh`.
