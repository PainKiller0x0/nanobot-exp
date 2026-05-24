"""Safe upstream upgrade workflow for nanobot doctor."""

from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class UpgradeStep:
    name: str
    status: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {"name": self.name, "status": self.status, "detail": self.detail}


@dataclass
class UpgradeReport:
    ok: bool = True
    current_commit: str | None = None
    latest_ref: str | None = None
    backup_branch: str | None = None
    upgrade_branch: str | None = None
    worktree: str | None = None
    deployed: bool = False
    steps: list[UpgradeStep] = field(default_factory=list)

    @property
    def has_failures(self) -> bool:
        return any(step.status == "fail" for step in self.steps)

    def add(self, name: str, status: str, detail: str) -> None:
        if status == "fail":
            self.ok = False
        self.steps.append(UpgradeStep(name=name, status=status, detail=detail))

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok and not self.has_failures,
            "current_commit": self.current_commit,
            "latest_ref": self.latest_ref,
            "backup_branch": self.backup_branch,
            "upgrade_branch": self.upgrade_branch,
            "worktree": self.worktree,
            "deployed": self.deployed,
            "steps": [step.as_dict() for step in self.steps],
        }


class UpgradeError(RuntimeError):
    """Raised when a required upgrade step fails."""


def run_doctor_upgrade(
    *,
    repo_path: str | Path | None = None,
    upstream_remote: str = "official",
    upstream_ref: str = "latest",
    worktree_root: str | Path | None = None,
    run_tests: bool = True,
    deploy: bool = False,
    service: str = "podman-nanobot-cage.service",
    push_remote: str | None = None,
    push_branch: str = "main",
) -> UpgradeReport:
    """Prepare or deploy a safe upstream upgrade.

    The default mode is review-only: it fetches upstream, merges in an isolated
    worktree, runs checks, and leaves the live repo untouched. ``deploy=True``
    fast-forwards the live repo to the tested branch and restarts the service.
    """

    report = UpgradeReport()
    repo = Path(repo_path or Path.cwd()).expanduser().resolve()
    try:
        _ensure_git_repo(repo)
        current = _git(repo, "rev-parse", "--short", "HEAD")
        report.current_commit = current.stdout.strip()
        dirty = _git(repo, "status", "--short").stdout.strip()
        if dirty:
            raise UpgradeError("live repo has uncommitted changes; aborting upgrade")
        report.add("repo", "ok", f"clean at {report.current_commit}")

        fetch = _git(repo, "fetch", upstream_remote, "--tags", timeout=120, check=False)
        if fetch.returncode != 0:
            raise UpgradeError(_format_failure("git fetch", fetch))
        report.add("fetch", "ok", f"fetched {upstream_remote}")

        latest_ref = _resolve_upstream_ref(repo, upstream_ref)
        report.latest_ref = latest_ref
        if _is_ancestor(repo, latest_ref, "HEAD"):
            report.add("upstream", "ok", f"already includes {latest_ref}")
            return report

        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        safe_ref = _safe_ref(latest_ref)
        backup_branch = f"backup/pre-upgrade-{stamp}"
        upgrade_branch = f"upgrade/{safe_ref}-{stamp}"
        root = Path(worktree_root).expanduser() if worktree_root else repo.parent
        worktree = root / f"{repo.name}-upgrade-{safe_ref}-{stamp}"
        report.backup_branch = backup_branch
        report.upgrade_branch = upgrade_branch
        report.worktree = str(worktree)

        _git(repo, "branch", backup_branch, "HEAD")
        report.add("backup", "ok", backup_branch)

        _git(repo, "worktree", "add", "-b", upgrade_branch, str(worktree), "HEAD", timeout=120)
        report.add("worktree", "ok", str(worktree))

        merge = _git(worktree, "merge", "--no-edit", latest_ref, timeout=180, check=False)
        if merge.returncode != 0:
            report.add("merge", "fail", _format_failure("git merge", merge))
            return report
        report.add("merge", "ok", f"merged {latest_ref} into {upgrade_branch}")

        if run_tests:
            _run_check(report, worktree, ["uv", "run", "ruff", "check", "nanobot", "--select", "F"], "lint")
            _run_check(
                report,
                worktree,
                ["uv", "run", "--extra", "dev", "python", "-m", "pytest", "tests/", "-q"],
                "tests",
                timeout=900,
            )
            if report.has_failures:
                return report
        else:
            report.add("tests", "info", "skipped by request")

        if deploy:
            _git(repo, "merge", "--ff-only", upgrade_branch, timeout=120)
            report.deployed = True
            report.add("deploy", "ok", f"fast-forwarded to {upgrade_branch}")
            if push_remote:
                _git(repo, "push", push_remote, f"HEAD:{push_branch}", timeout=180)
                report.add("push", "ok", f"{push_remote} HEAD:{push_branch}")
            if service:
                proc = subprocess.run(
                    ["systemctl", "restart", service],
                    text=True,
                    capture_output=True,
                    timeout=120,
                    check=False,
                )
                if proc.returncode != 0:
                    report.add("restart", "fail", _format_failure("systemctl restart", proc))
                    return report
                report.add("restart", "ok", service)
        else:
            report.add("deploy", "info", "review-only; pass --deploy to fast-forward and restart")
    except UpgradeError as exc:
        report.add("upgrade", "fail", str(exc))
    except Exception as exc:  # pragma: no cover - defensive guard for CLI use
        report.add("upgrade", "fail", f"unexpected error: {exc}")
    report.ok = not report.has_failures
    return report


def _ensure_git_repo(repo: Path) -> None:
    if not (repo / ".git").exists():
        raise UpgradeError(f"not a git repo: {repo}")


def _git(repo: Path, *args: str, timeout: int = 60, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if check and proc.returncode != 0:
        raise UpgradeError(_format_failure("git " + " ".join(args), proc))
    return proc


def _format_failure(name: str, proc: subprocess.CompletedProcess[str]) -> str:
    detail = (proc.stderr or proc.stdout or "").strip()
    return f"{name} failed with exit {proc.returncode}: {detail[:2000]}"


def _resolve_upstream_ref(repo: Path, upstream_ref: str) -> str:
    if upstream_ref != "latest":
        return upstream_ref
    proc = _git(repo, "tag", "--list", "v*", "--sort=-v:refname")
    for line in proc.stdout.splitlines():
        tag = line.strip()
        if tag:
            return tag
    raise UpgradeError("no v* upstream tags found after fetch")


def _is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    proc = _git(repo, "merge-base", "--is-ancestor", ancestor, descendant, check=False)
    return proc.returncode == 0


def _safe_ref(ref: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", ref).strip("-") or "upstream"


def _run_check(
    report: UpgradeReport,
    cwd: Path,
    cmd: list[str],
    name: str,
    *,
    timeout: int = 180,
) -> None:
    started = time.perf_counter()
    proc = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, timeout=timeout, check=False)
    elapsed = time.perf_counter() - started
    if proc.returncode == 0:
        report.add(name, "ok", f"passed in {elapsed:.1f}s")
    else:
        report.add(name, "fail", _format_failure(" ".join(cmd), proc))


__all__ = ["UpgradeReport", "UpgradeStep", "run_doctor_upgrade"]
