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
