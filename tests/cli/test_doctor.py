import json
from pathlib import Path

from typer.testing import CliRunner

from nanobot.cli.commands import app
from nanobot.config.schema import Config
from nanobot.doctor import run_doctor

runner = CliRunner()


def _write_config(path: Path, workspace: Path) -> None:
    config = Config()
    config.agents.defaults.workspace = str(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config.model_dump(mode="json", by_alias=True)), encoding="utf-8")


def test_doctor_reports_missing_workspace_without_repair(tmp_path):
    config_path = tmp_path / "config.json"
    workspace = tmp_path / "workspace"
    _write_config(config_path, workspace)

    report = run_doctor(
        config_path=config_path,
        repair=False,
        probe_external=False,
        stable_dir=tmp_path / "doctor",
        repo_path=tmp_path,
    )

    assert not workspace.exists()
    assert any(c.name == "workspace path" and c.status == "warn" for c in report.checks)


def test_doctor_repair_creates_workspace_and_stable_point(tmp_path):
    config_path = tmp_path / "config.json"
    workspace = tmp_path / "workspace"
    _write_config(config_path, workspace)

    report = run_doctor(
        config_path=config_path,
        repair=True,
        probe_external=False,
        stable_dir=tmp_path / "doctor",
        repo_path=tmp_path,
    )

    assert workspace.exists()
    assert (workspace / "AGENTS.md").exists()
    assert report.stable_point
    assert Path(report.stable_point).exists()
    assert any(c.area == "ark-lite" and c.status == "fixed" for c in report.checks)


def test_doctor_cli_json_uses_config_path(tmp_path):
    config_path = tmp_path / "config.json"
    workspace = tmp_path / "workspace"
    _write_config(config_path, workspace)

    result = runner.invoke(
        app,
        ["doctor", "--config", str(config_path), "--json"],
        env={"NANOBOT_DOCTOR_SKIP_EXTERNAL": "1"},
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert "checks" in payload
    assert any(check["name"] == "workspace path" for check in payload["checks"])


# Doctor upgrade -------------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    import subprocess

    proc = subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    )
    return proc.stdout.strip()


def _init_upstream_repo(path: Path) -> None:
    path.mkdir(parents=True)
    _git(path, "init")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test User")
    (path / "README.md").write_text("v1\n", encoding="utf-8")
    _git(path, "add", ".")
    _git(path, "commit", "-m", "initial")
    _git(path, "tag", "v0.1.0")


def test_doctor_upgrade_reports_up_to_date(tmp_path):
    from nanobot.doctor_upgrade import run_doctor_upgrade

    upstream = tmp_path / "upstream"
    _init_upstream_repo(upstream)
    work = tmp_path / "work"
    _git(tmp_path, "clone", str(upstream), str(work))

    report = run_doctor_upgrade(
        repo_path=work,
        upstream_remote=str(upstream),
        upstream_ref="latest",
        run_tests=False,
    )

    assert not report.has_failures
    assert report.worktree is None
    assert any(step.name == "upstream" and "v0.1.0" in step.detail for step in report.steps)


def test_doctor_upgrade_prepares_review_worktree(tmp_path):
    from nanobot.doctor_upgrade import run_doctor_upgrade

    upstream = tmp_path / "upstream"
    _init_upstream_repo(upstream)
    work = tmp_path / "work"
    _git(tmp_path, "clone", str(upstream), str(work))

    (upstream / "README.md").write_text("v2\n", encoding="utf-8")
    _git(upstream, "add", ".")
    _git(upstream, "commit", "-m", "second")
    _git(upstream, "tag", "v0.2.0")

    report = run_doctor_upgrade(
        repo_path=work,
        upstream_remote=str(upstream),
        upstream_ref="latest",
        worktree_root=tmp_path,
        run_tests=False,
    )

    assert not report.has_failures
    assert report.latest_ref == "v0.2.0"
    assert report.worktree is not None
    assert Path(report.worktree).exists()
    assert not report.deployed
    assert (work / "README.md").read_text(encoding="utf-8") == "v1\n"
    assert (Path(report.worktree) / "README.md").read_text(encoding="utf-8") == "v2\n"


def test_doctor_upgrade_cli_json(tmp_path):
    upstream = tmp_path / "upstream"
    _init_upstream_repo(upstream)
    work = tmp_path / "work"
    _git(tmp_path, "clone", str(upstream), str(work))

    result = runner.invoke(
        app,
        [
            "doctor-upgrade",
            "--repo",
            str(work),
            "--remote",
            str(upstream),
            "--ref",
            "latest",
            "--skip-tests",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["latest_ref"] == "v0.1.0"
