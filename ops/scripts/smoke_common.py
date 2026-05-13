#!/usr/bin/env python3
"""Shared helpers for nanobot-exp smoke scripts.

Keep this module dependency-free: smoke checks should run on a freshly booted
server without importing Nanobot or installing test-only packages.
"""

from __future__ import annotations

import json
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str = ""
    data: dict[str, Any] = field(default_factory=dict)


def parse_json(text: str) -> Any:
    if not text.strip():
        return None
    try:
        return json.loads(text)
    except Exception:
        return {"raw": text[:500]}


def short(value: Any, limit: int = 160) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return text[:limit] + ("..." if len(text) > limit else "")


def http_json(
    method: str,
    url: str,
    body: Any = None,
    headers: dict[str, str] | None = None,
    timeout: float = 20.0,
) -> tuple[int, dict[str, str], Any, float]:
    data = None
    req_headers = dict(headers or {})
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req_headers.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", "replace")
            return resp.status, {k.lower(): v for k, v in resp.headers.items()}, parse_json(text), time.time() - started
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", "replace")
        return exc.code, {k.lower(): v for k, v in exc.headers.items()}, parse_json(text), time.time() - started
    except Exception as exc:
        return 0, {}, {"error": str(exc)}, time.time() - started


def get_json(url: str, timeout: float = 12.0) -> tuple[int, dict[str, str], Any, float]:
    return http_json("GET", url, timeout=timeout)


def post_json(
    url: str,
    body: Any,
    headers: dict[str, str] | None = None,
    timeout: float = 45.0,
) -> tuple[int, dict[str, str], Any, float]:
    return http_json("POST", url, body=body, headers=headers, timeout=timeout)


def get_simple(url: str, timeout: float = 12.0) -> tuple[int, Any, float]:
    status, _headers, data, elapsed = get_json(url, timeout=timeout)
    return status, data, elapsed


def post_simple(url: str, body: Any, timeout: float = 45.0) -> tuple[int, Any, float]:
    status, _headers, data, elapsed = post_json(url, body=body, timeout=timeout)
    return status, data, elapsed


def add_result(
    results: list[CheckResult],
    name: str,
    ok: bool,
    detail: str = "",
    data: dict[str, Any] | None = None,
) -> None:
    results.append(CheckResult(name, ok, detail, data or {}))


def run_command(args: list[str], timeout: float = 20.0) -> tuple[int, str, float]:
    started = time.time()
    try:
        proc = subprocess.run(args, text=True, capture_output=True, timeout=timeout)
        return proc.returncode, (proc.stdout + proc.stderr).strip(), time.time() - started
    except Exception as exc:
        return 99, str(exc), time.time() - started


def run_proc(args: list[str], timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, timeout=timeout)
