#!/usr/bin/env bash
set -euo pipefail

# Fast smoke regression suite for nanobot-exp.
# Goal: catch wiring regressions in under a minute before full CI.

cd "$(dirname "$0")/.."

if [[ -f "uv.lock" ]] && command -v uv >/dev/null 2>&1; then
  RUN=(uv run)
  echo "[smoke] using uv run"
else
  RUN=()
  echo "[smoke] using system python"
fi

run_py() {
  if [[ ${#RUN[@]} -gt 0 ]]; then
    "${RUN[@]}" python -c "$1"
  else
    python3 -c "$1"
  fi
}

run_cmd() {
  if [[ ${#RUN[@]} -gt 0 ]]; then
    "${RUN[@]}" "$@"
  else
    "$@"
  fi
}

run_pytest() {
  if [[ ${#RUN[@]} -gt 0 ]]; then
    "${RUN[@]}" pytest -q "$@"
  else
    python3 -m pytest -q "$@"
  fi
}

echo "[smoke] 1/4 import nanobot package"
run_py "import nanobot"

echo "[smoke] 2/4 cli help"
run_cmd nanobot --help >/dev/null

echo "[smoke] 3/4 extension installer help"
bash scripts/install_extentions.sh --help >/dev/null

echo "[smoke] 4/4 minimal regression tests"
run_pytest \
  tests/cli/test_safe_file_history.py \
  tests/config/test_config_paths.py \
  tests/test_package_version.py

echo "[smoke] all checks passed"