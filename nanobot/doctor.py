"""Nanobot doctor checks and low-risk repairs.

This module intentionally stays independent from the gateway runtime. The CLI can
import it quickly, and tests can run it without starting channels or providers.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nanobot.config.loader import get_config_path, load_config, set_config_path
from nanobot.config.schema import Config
from nanobot.utils.helpers import sync_workspace_templates

STATUS_ORDER = {"fail": 0, "warn": 1, "fixed": 2, "ok": 3, "info": 4}


@dataclass
class DoctorCheck:
    area: str
    name: str
    status: str
    detail: str
    hint: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "area": self.area,
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
            "hint": self.hint,
        }


@dataclass
class DoctorReport:
    checks: list[DoctorCheck] = field(default_factory=list)
    repairs: list[str] = field(default_factory=list)
    stable_point: str | None = None

    @property
    def has_failures(self) -> bool:
        return any(check.status == "fail" for check in self.checks)

    @property
    def summary(self) -> dict[str, int]:
        out = {"ok": 0, "warn": 0, "fail": 0, "fixed": 0, "info": 0}
        for check in self.checks:
            out[check.status] = out.get(check.status, 0) + 1
        return out

    def add(self, area: str, name: str, status: str, detail: str, hint: str = "") -> None:
        self.checks.append(DoctorCheck(area, name, status, detail, hint))

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": not self.has_failures,
            "summary": self.summary,
            "repairs": self.repairs,
            "stable_point": self.stable_point,
            "checks": [check.as_dict() for check in self.checks],
        }


def run_doctor(
    *,
    config_path: str | Path | None = None,
    workspace: str | Path | None = None,
    repair: bool = False,
    deep: bool = False,
    probe_external: bool | None = None,
    stable_dir: str | Path | None = None,
    repo_path: str | Path | None = None,
) -> DoctorReport:
    """Run doctor checks.

    ``repair`` only performs low-risk changes: create missing runtime dirs, tighten
    config file permissions, remove known-deprecated keys after writing a backup,
    and write an Ark Lite stable point. It never restarts services or deletes data.
    """

    report = DoctorReport()
    cfg_path = Path(config_path).expanduser().resolve() if config_path else get_config_path()
    if config_path:
        set_config_path(cfg_path)

    raw_config: dict[str, Any] | None = None
    config = Config()
    if not cfg_path.exists():
        report.add(
            "config",
            "config file",
            "warn",
            f"Config not found: {cfg_path}",
            "Run `nanobot onboard` or pass `--config`.",
        )
    else:
        try:
            raw_config = json.loads(cfg_path.read_text(encoding="utf-8"))
            config = load_config(cfg_path)
            report.add("config", "config file", "ok", f"Loaded {cfg_path}")
        except json.JSONDecodeError as exc:
            report.add(
                "config",
                "config file",
                "fail",
                f"Invalid JSON in {cfg_path}: {exc}",
                "Fix the JSON syntax or restore from a backup before starting gateway.",
            )
        except Exception as exc:  # pragma: no cover - defensive guard for pydantic/runtime surprises
            report.add("config", "config file", "fail", f"Could not load config: {exc}")

    if raw_config is not None:
        _check_deprecated_config(report, cfg_path, raw_config, repair)
        _check_config_permissions(report, cfg_path, repair)

    workspace_path = Path(workspace).expanduser() if workspace else Path(config.workspace_path).expanduser()
    _check_workspace(report, workspace_path, repair)
    _check_runtime_dirs(report, cfg_path.parent, repair)
    _check_provider(report, config)
    _check_cron_store(report, workspace_path)
    _check_gateway_pid(report, cfg_path.parent)

    if probe_external is None:
        probe_external = os.environ.get("NANOBOT_DOCTOR_SKIP_EXTERNAL") not in {"1", "true", "yes"}
    if probe_external:
        _check_sidecars(report, deep=deep)
        _check_systemd(report)
    else:
        report.add("runtime", "external probes", "info", "Skipped external probes")

    if repair:
        stable_path = _write_stable_point(
            report,
            cfg_path=cfg_path,
            workspace_path=workspace_path,
            stable_dir=Path(stable_dir).expanduser() if stable_dir else cfg_path.parent / "doctor",
            repo_path=Path(repo_path).expanduser() if repo_path else None,
        )
        report.stable_point = str(stable_path)
        report.repairs.append(f"Wrote Ark Lite stable point: {stable_path}")
        report.add("ark-lite", "stable point", "fixed", f"Wrote {stable_path}")
    else:
        stable_path = (Path(stable_dir).expanduser() if stable_dir else cfg_path.parent / "doctor") / "stable.json"
        if stable_path.exists():
            report.add("ark-lite", "stable point", "ok", f"Existing stable point: {stable_path}")
        else:
            report.add(
                "ark-lite",
                "stable point",
                "warn",
                "No Ark Lite stable point recorded yet",
                "Run `nanobot doctor --repair` after a known-good deployment.",
            )

    report.checks.sort(key=lambda item: (STATUS_ORDER.get(item.status, 9), item.area, item.name))
    return report


def _backup_file(path: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    backup = path.with_name(f"{path.name}.bak.{stamp}")
    shutil.copy2(path, backup)
    return backup


def _check_deprecated_config(report: DoctorReport, cfg_path: Path, raw: dict[str, Any], repair: bool) -> None:
    defaults = raw.get("agents", {}).get("defaults", {})
    if "memoryWindow" not in defaults:
        report.add("config", "deprecated keys", "ok", "No known deprecated keys found")
        return
    if not repair:
        report.add(
            "config",
            "deprecated keys",
            "warn",
            "Found agents.defaults.memoryWindow, which is no longer used",
            "Run `nanobot doctor --repair` to remove it after a backup.",
        )
        return
    backup = _backup_file(cfg_path)
    defaults.pop("memoryWindow", None)
    cfg_path.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    report.repairs.append(f"Removed agents.defaults.memoryWindow (backup: {backup})")
    report.add("config", "deprecated keys", "fixed", f"Removed memoryWindow; backup at {backup}")


def _check_config_permissions(report: DoctorReport, cfg_path: Path, repair: bool) -> None:
    if os.name == "nt":
        report.add("security", "config permissions", "info", "Skipped POSIX permission check on Windows")
        return
    mode = stat.S_IMODE(cfg_path.stat().st_mode)
    if mode & 0o077 == 0:
        report.add("security", "config permissions", "ok", f"Config permissions are {mode:o}")
        return
    if repair:
        os.chmod(cfg_path, 0o600)
        report.repairs.append(f"chmod 600 {cfg_path}")
        report.add("security", "config permissions", "fixed", "Config permissions tightened to 600")
    else:
        report.add(
            "security",
            "config permissions",
            "warn",
            f"Config permissions are {mode:o}; group/world bits are set",
            "Run `nanobot doctor --repair` to chmod 600.",
        )


def _check_workspace(report: DoctorReport, workspace_path: Path, repair: bool) -> None:
    if not workspace_path.exists():
        if repair:
            workspace_path.mkdir(parents=True, exist_ok=True)
            sync_workspace_templates(workspace_path)
            report.repairs.append(f"Created workspace {workspace_path}")
            report.add("workspace", "workspace path", "fixed", f"Created {workspace_path}")
        else:
            report.add(
                "workspace",
                "workspace path",
                "warn",
                f"Workspace missing: {workspace_path}",
                "Run `nanobot doctor --repair` or `nanobot onboard`.",
            )
            return
    else:
        report.add("workspace", "workspace path", "ok", f"Workspace exists: {workspace_path}")

    try:
        probe = workspace_path / ".nanobot_doctor_write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        report.add("workspace", "writable", "ok", "Workspace is writable")
    except Exception as exc:
        report.add("workspace", "writable", "fail", f"Workspace is not writable: {exc}")


def _check_runtime_dirs(report: DoctorReport, data_dir: Path, repair: bool) -> None:
    for name in ("logs", "cron", "media", "doctor"):
        path = data_dir / name
        if path.exists():
            report.add("runtime", f"{name} dir", "ok", str(path))
        elif repair:
            path.mkdir(parents=True, exist_ok=True)
            report.repairs.append(f"Created {path}")
            report.add("runtime", f"{name} dir", "fixed", f"Created {path}")
        else:
            report.add("runtime", f"{name} dir", "warn", f"Missing {path}")


def _check_provider(report: DoctorReport, config: Config) -> None:
    try:
        from nanobot.providers.registry import find_by_name

        model = config.agents.defaults.model
        provider_name = config.get_provider_name(model)
        provider = config.get_provider(model)
        spec = find_by_name(provider_name) if provider_name else None
        if not provider_name:
            report.add("provider", "model route", "warn", f"Could not resolve provider for model {model}")
            return
        if provider and provider.api_key:
            report.add("provider", "credentials", "ok", f"{provider_name} configured for {model}")
            return
        if spec and (spec.is_oauth or spec.is_local or spec.is_direct):
            report.add("provider", "credentials", "ok", f"{provider_name} does not require a stored API key")
            return
        report.add(
            "provider",
            "credentials",
            "warn",
            f"{provider_name} for {model} has no API key in config",
            "If this route goes through OBP or env vars, this can be fine; otherwise configure provider credentials.",
        )
    except Exception as exc:
        report.add("provider", "model route", "warn", f"Could not inspect provider route: {exc}")


def _check_cron_store(report: DoctorReport, workspace_path: Path) -> None:
    path = workspace_path / "cron" / "jobs.json"
    if not path.exists():
        report.add("cron", "job store", "info", f"No workspace cron store at {path}")
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        jobs = data if isinstance(data, list) else data.get("jobs", []) if isinstance(data, dict) else []
        enabled = sum(1 for job in jobs if isinstance(job, dict) and job.get("enabled", True))
        report.add("cron", "job store", "ok", f"{enabled}/{len(jobs)} jobs enabled")
    except Exception as exc:
        report.add("cron", "job store", "warn", f"Could not parse cron store: {exc}")


def _check_gateway_pid(report: DoctorReport, data_dir: Path) -> None:
    candidates = [data_dir / "gateway.pid", data_dir / "gateway_main.pid"]
    found = [p for p in candidates if p.exists()]
    if not found:
        report.add("gateway", "pid file", "info", "No gateway pid file found")
        return
    for path in found:
        try:
            pid = int(path.read_text(encoding="utf-8").strip())
            os.kill(pid, 0)
            report.add("gateway", path.name, "ok", f"PID {pid} is alive")
        except ProcessLookupError:
            report.add("gateway", path.name, "warn", f"Stale PID file: {path}")
        except Exception as exc:
            report.add("gateway", path.name, "warn", f"Could not inspect {path}: {exc}")


def _probe_json(url: str, timeout: float = 1.5) -> tuple[dict[str, Any] | None, str | None]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8")), None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        return None, str(exc)


def _check_sidecars(report: DoctorReport, *, deep: bool) -> None:
    data, err = _probe_json("http://127.0.0.1:8093/api/sidecars", timeout=3.0 if deep else 1.5)
    if err:
        report.add("sidecar", "manager", "info", f"8093 sidecar manager not reachable: {err}")
        return
    summary = data.get("summary", {}) if isinstance(data, dict) else {}
    unhealthy = int(summary.get("unhealthy") or 0)
    total = int(summary.get("total") or 0)
    if unhealthy:
        names = []
        for item in data.get("items", []):
            if not item.get("ok"):
                names.append(str(item.get("id") or item.get("name") or "unknown"))
        report.add("sidecar", "manager", "warn", f"{unhealthy}/{total} sidecars unhealthy: {', '.join(names[:6])}")
    else:
        report.add("sidecar", "manager", "ok", f"{total} sidecars healthy")

    jobs, jobs_err = _probe_json("http://127.0.0.1:8093/api/notify-jobs", timeout=3.0 if deep else 1.5)
    if jobs_err:
        report.add("notify", "jobs", "info", f"Notify sidecar not reachable: {jobs_err}")
        return
    details = jobs.get("job_details", []) if isinstance(jobs, dict) else []
    errors = [job for job in details if job.get("status", {}).get("last_status") == "error"]
    enabled = sum(1 for job in details if job.get("enabled", True))
    if errors:
        report.add("notify", "jobs", "warn", f"{len(errors)} jobs have last_status=error")
    else:
        report.add("notify", "jobs", "ok", f"{enabled} enabled jobs inspected")


def _check_systemd(report: DoctorReport) -> None:
    if sys.platform != "linux" or shutil.which("systemctl") is None:
        report.add("runtime", "systemd", "info", "systemd check skipped")
        return
    for service in ("podman-nanobot-cage.service", "lof-sidecar.service"):
        try:
            proc = subprocess.run(
                ["systemctl", "is-active", service],
                text=True,
                capture_output=True,
                timeout=2,
                check=False,
            )
            state = proc.stdout.strip() or proc.stderr.strip() or f"exit {proc.returncode}"
            status = "ok" if proc.returncode == 0 else "warn"
            report.add("runtime", service, status, state)
        except Exception as exc:
            report.add("runtime", service, "info", f"systemctl probe skipped: {exc}")


def _find_git_repo(start: Path) -> Path | None:
    current = start.resolve(strict=False)
    for path in (current, *current.parents):
        if (path / ".git").exists():
            return path
    return None


def _git_value(repo: Path, *args: str) -> str | None:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=repo,
            text=True,
            capture_output=True,
            timeout=3,
            check=False,
        )
        if proc.returncode == 0:
            return proc.stdout.strip()
    except Exception:
        return None
    return None


def _write_stable_point(
    report: DoctorReport,
    *,
    cfg_path: Path,
    workspace_path: Path,
    stable_dir: Path,
    repo_path: Path | None,
) -> Path:
    stable_dir.mkdir(parents=True, exist_ok=True)
    repo = repo_path or _find_git_repo(Path.cwd())
    git_info: dict[str, Any] = {"repo": str(repo) if repo else None}
    if repo:
        git_info.update(
            {
                "commit": _git_value(repo, "rev-parse", "HEAD"),
                "branch": _git_value(repo, "rev-parse", "--abbrev-ref", "HEAD"),
                "dirty": bool(_git_value(repo, "status", "--short")),
            }
        )
    stable = {
        "created_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "config_path": str(cfg_path),
        "workspace_path": str(workspace_path),
        "git": git_info,
        "summary": report.summary,
        "repair_count": len(report.repairs),
    }
    path = stable_dir / "stable.json"
    tmp = stable_dir / f"stable.json.tmp.{int(time.time())}"
    tmp.write_text(json.dumps(stable, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path
