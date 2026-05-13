import json

from nanobot.agent.capability_registry import (
    configured_registry_path,
    enabled_capabilities,
    group_by_category,
    load_capabilities,
)


def test_load_capabilities_reads_registry_file(tmp_path) -> None:
    path = tmp_path / "capabilities.json"
    path.write_text(
        json.dumps(
            [
                {"id": "ops", "category": "运维", "enabled": True},
                {"id": "disabled", "enabled": False},
                "bad",
                42,
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    items = load_capabilities(path)

    assert [item["id"] for item in items] == ["ops", "disabled"]
    assert [item["id"] for item in enabled_capabilities(items)] == ["ops"]


def test_load_capabilities_ignores_missing_or_invalid_file(tmp_path) -> None:
    assert load_capabilities(tmp_path / "missing.json") == []

    path = tmp_path / "invalid.json"
    path.write_text("{bad", encoding="utf-8")
    assert load_capabilities(path) == []


def test_configured_registry_path_prefers_env(tmp_path) -> None:
    configured = tmp_path / "custom.json"
    assert configured_registry_path(env={"CAPABILITY_REGISTRY_CONFIG": str(configured)}) == configured


def test_group_by_category_defaults_to_other() -> None:
    grouped = group_by_category([
        {"id": "a", "category": "运维"},
        {"id": "b"},
    ])

    assert [item["id"] for item in grouped["运维"]] == ["a"]
    assert [item["id"] for item in grouped["其他"]] == ["b"]
