import copy
import json
import os
import re
import warnings
from pathlib import Path
from typing import Any, TypeVar, cast, overload

from pydantic import BaseModel, ValidationError
from pydantic_settings import SettingsError

from nanobot.config.errors import ConfigIssue, ConfigLoadError, validation_issues
from nanobot.config.home import get_home_path
from nanobot.config.network import NetworkConfig
from nanobot.config.schema import Config
from nanobot.utils.file_io import write_text_atomic

_current_config_path: Path | None = None
_LEGACY_DEFAULT_KEYS = ("unifiedSession", "unified_session")


class ConfigWriteError(RuntimeError):
    """Raised when saving would drop retained legacy configuration."""


def legacy_config_keys(data: dict[str, Any]) -> dict[str, Any]:
    """Copy legacy values that this release does not apply.

    ``api`` is the removed ``nanobot serve`` block. ``unifiedSession`` and
    ``unified_session`` are the removed shared-session switch. The copies are
    stored and written back unchanged. They do not start a server or merge sessions.
    """
    retained: dict[str, Any] = {}
    if "api" in data:
        retained["api"] = copy.deepcopy(data["api"])
    agents = data.get("agents")
    if isinstance(agents, dict):
        defaults = agents.get("defaults")
        if isinstance(defaults, dict):
            kept = {
                key: copy.deepcopy(defaults[key])
                for key in _LEGACY_DEFAULT_KEYS
                if key in defaults
            }
            if kept:
                retained["agents.defaults"] = kept
    return retained


def _warn_retained_legacy(retained: dict[str, Any]) -> None:
    if not retained:
        return
    names: list[str] = []
    if "api" in retained:
        names.append("api")
    defaults = retained.get("agents.defaults")
    if isinstance(defaults, dict):
        names.extend(f"agents.defaults.{key}" for key in defaults)
    warnings.warn(
        "Retained legacy configuration "
        + ", ".join(names)
        + ". These values are written back unchanged and are not applied: "
        + "nanobot serve has been removed, and unifiedSession does not select a "
        + "shared session. Delete the keys in the file only when you intend to drop them.",
        UserWarning,
        stacklevel=3,
    )


_CREDENTIAL_PROVIDER_CANONS = {("providers", "openaicodex"), ("providers", "xaigrok")}


def _canon_key(key: str) -> str:
    return key.replace("_", "").lower()


def _canon_path(path: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(_canon_key(part) for part in path)


def _is_legacy_canon(canon: tuple[str, ...]) -> bool:
    """Paths owned by the explicit api / unifiedSession retention."""
    if not canon:
        return False
    if canon[0] == "api":
        return True
    return len(canon) >= 3 and canon[:3] == ("agents", "defaults", "unifiedsession")


def _iter_leaves(value: object, path: tuple[str, ...] = ()) -> Any:
    if isinstance(value, dict) and any(isinstance(key, str) for key in value):
        for key, item in value.items():
            if isinstance(key, str):
                yield from _iter_leaves(item, path + (key,))
        return
    yield path, value


def _json_token(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)


def _collapse_equal_aliases(value: object, location: str, path: Path) -> object:
    """Reject different values that share a snake/camel spelling.

    Equal values keep the first spelling so validation sees one field.
    The original document is still what retention compares.
    """
    if isinstance(value, list):
        return [
            _collapse_equal_aliases(item, f"{location}[{index}]", path)
            for index, item in enumerate(value)
        ]
    if not isinstance(value, dict):
        return value
    grouped: dict[str, list[tuple[str, object]]] = {}
    for key, item in value.items():
        if isinstance(key, str):
            grouped.setdefault(_canon_key(key), []).append((key, item))
    for canon, items in grouped.items():
        if len(items) < 2:
            continue
        # Both legacy spellings are retained even when their values differ.
        # They are not one applied setting.
        if location == "agents.defaults" and canon == "unifiedsession":
            continue
        tokens = {_json_token(item) for _, item in items}
        if len(tokens) > 1:
            shown = ", ".join(
                f"{location}.{key}" if location else key for key, _ in items
            )
            raise ConfigLoadError(
                path,
                kind="invalid_schema",
                summary=(
                    f"Conflicting aliases have different values: {shown}. "
                    "Keep one spelling, or make the values identical, before loading."
                ),
            )
    collapsed: dict[str, object] = {}
    seen: set[str] = set()
    for key, item in value.items():
        if not isinstance(key, str):
            collapsed[str(key)] = item
            continue
        canon = _canon_key(key)
        keep_both = location == "agents.defaults" and canon == "unifiedsession"
        if canon in seen and not keep_both:
            continue
        seen.add(canon)
        child = f"{location}.{key}" if location else key
        collapsed[key] = _collapse_equal_aliases(item, child, path)
    return collapsed


def _alias_canons(field_name: str, field: Any) -> set[str]:
    canons = {_canon_key(field_name)}
    for attr in ("alias", "serialization_alias"):
        value = getattr(field, attr, None)
        if isinstance(value, str):
            canons.add(_canon_key(value))
    validation = getattr(field, "validation_alias", None)
    if isinstance(validation, str):
        canons.add(_canon_key(validation))
    for choice in getattr(validation, "choices", ()) or ():
        if isinstance(choice, str):
            canons.add(_canon_key(choice))
    return canons


def _unknown_entries(
    data: object,
    model: Any,
    removed_canons: set[tuple[str, ...]],
    prefix: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    """Keep values a model would ignore, not aliases or migrated keys.

    Dict fields such as model presets and MCP servers own their keys, so
    removing one is an edit. ``extra="allow"`` values already survive in the
    model dump and are not copied again.
    """
    if not isinstance(data, dict) or not isinstance(model, BaseModel):
        return []
    by_canon: dict[str, str] = {}
    for name, field in type(model).model_fields.items():
        for canon in _alias_canons(name, field):
            by_canon.setdefault(canon, name)
    dumped = model.model_dump(mode="json", by_alias=True)
    dumped_canons = {_canon_key(key) for key in dumped} if isinstance(dumped, dict) else set()
    found: list[dict[str, Any]] = []
    for key, value in data.items():
        if not isinstance(key, str):
            continue
        path = prefix + (key,)
        canon = _canon_key(key)
        canon_path = _canon_path(path)
        if canon_path in removed_canons or _is_legacy_canon(canon_path):
            continue
        if canon in by_canon:
            child = getattr(model, by_canon[canon], None)
            if isinstance(child, BaseModel) and isinstance(value, dict):
                found.extend(_unknown_entries(value, child, removed_canons, path))
            elif isinstance(child, dict) and isinstance(value, dict):
                for item_key, item_value in value.items():
                    if not isinstance(item_key, str) or not isinstance(item_value, dict):
                        continue
                    item = child.get(item_key)
                    if isinstance(item, BaseModel):
                        found.extend(_unknown_entries(
                            item_value, item, removed_canons, path + (item_key,),
                        ))
            continue
        if canon in dumped_canons:
            continue
        for leaf_path, leaf_value in _iter_leaves(value, path):
            leaf_canon = _canon_path(leaf_path)
            if leaf_canon in removed_canons or _is_legacy_canon(leaf_canon):
                continue
            found.append({"path": list(leaf_path), "value": copy.deepcopy(leaf_value)})
    return found


def _merge_unknowns(data: dict[str, Any], entries: list[dict[str, Any]]) -> None:
    present = {_canon_path(path) for path, _value in _iter_leaves(data)}
    for entry in entries:
        raw_path = entry.get("path")
        if not isinstance(raw_path, list) or not all(isinstance(part, str) for part in raw_path):
            continue
        path = tuple(raw_path)
        if not path or _canon_path(path) in present:
            continue
        node: dict[str, Any] = data
        for key in path[:-1]:
            child = node.get(key)
            if not isinstance(child, dict):
                child = {}
                node[key] = child
            node = child
        node[path[-1]] = copy.deepcopy(entry.get("value"))
        present.add(_canon_path(path))


def dump_config(config: Config) -> dict[str, Any]:
    """JSON document written by save_config, including retained values.

    ``Config.model_dump()`` still omits ``api``, ``unifiedSession``, and
    unknown nested keys. This function is the lossless save view.
    """
    data = config.model_dump(mode="json", by_alias=True)
    if not isinstance(data, dict):
        return {}
    retained = config._retained_legacy if isinstance(config._retained_legacy, dict) else {}
    _merge_retained_legacy(data, retained)
    unknowns = config._retained_unknowns if isinstance(config._retained_unknowns, list) else []
    _merge_unknowns(data, unknowns)
    return data


def _unmodeled_leaf_canons(existing: dict[str, Any], path: Path) -> set[tuple[str, ...]]:
    """Leaf paths the schema does not represent, plus explicit legacy keys.

    Known settings may change or be removed. Only paths the model would drop
    are protected.
    """
    try:
        collapsed = _collapse_equal_aliases(dict(existing), "", path)
        migrated = _migrate_config(collapsed if isinstance(collapsed, dict) else dict(existing))
    except ConfigLoadError as exc:
        raise ConfigWriteError(str(exc)) from exc
    if isinstance(migrated, dict) and "api" in migrated:
        migrated = {key: value for key, value in migrated.items() if key != "api"}
    try:
        modeled = Config.model_validate(migrated)
    except ValidationError as exc:
        raise ConfigWriteError(
            f"Refusing to write {path} because the existing file could not be compared safely."
        ) from exc
    removed = {
        _canon_path(item_path)
        for item_path, _value in _iter_leaves(existing)
        if _canon_path(item_path) not in {
            _canon_path(migrated_path) for migrated_path, _migrated in _iter_leaves(migrated)
        }
    }
    canons = {
        _canon_path(tuple(entry["path"]))
        for entry in _unknown_entries(existing, modeled, removed)
    }
    for item_path, _value in _iter_leaves(existing):
        canon = _canon_path(item_path)
        if _is_legacy_canon(canon):
            canons.add(canon)
        if len(canon) >= 2 and canon[:2] in _CREDENTIAL_PROVIDER_CANONS:
            canons.discard(canon)
    return canons


def _reject_lossy_write(path: Path, existing: dict[str, Any], written: dict[str, Any]) -> None:
    protected = _unmodeled_leaf_canons(existing, path)
    written_canons = {_canon_path(item_path) for item_path, _value in _iter_leaves(written)}
    missing = []
    for item_path, _value in _iter_leaves(existing):
        canon = _canon_path(item_path)
        if not item_path or canon in written_canons or canon not in protected:
            continue
        missing.append(".".join(item_path))
    if not missing:
        return
    preview = ", ".join(missing[:12])
    if len(missing) > 12:
        preview = f"{preview}, ..."
    raise ConfigWriteError(
        f"Refusing to write {path} because it would drop {preview}. "
        "Load that file with load_config before saving. "
        "api and unifiedSession are kept but not applied: nanobot serve is removed "
        "and unifiedSession does not select a shared session."
    )


def _merge_retained_legacy(data: dict[str, Any], retained: dict[str, Any]) -> None:
    if "api" in retained:
        data["api"] = copy.deepcopy(retained["api"])
    defaults = retained.get("agents.defaults")
    if not isinstance(defaults, dict):
        return
    agents = data.setdefault("agents", {})
    if not isinstance(agents, dict):
        return
    agent_defaults = agents.setdefault("defaults", {})
    if not isinstance(agent_defaults, dict):
        return
    for key, value in defaults.items():
        agent_defaults[key] = copy.deepcopy(value)


def _as_config_object(value: object) -> dict[str, Any] | None:
    return cast(dict[str, Any], value) if isinstance(value, dict) else None


def set_config_path(path: Path) -> None:
    """Set the current config path (used to derive data directory)."""
    global _current_config_path
    _current_config_path = path


def get_config_path() -> Path:
    """Get the configuration file path."""
    if _current_config_path:
        return _current_config_path
    return get_home_path() / "config.json"


def load_config(config_path: Path | None = None) -> Config:
    """
    Load configuration from file or create default.

    Args:
        config_path: Optional path to config file. Uses default if not provided.

    Returns:
        Loaded configuration object.
    """
    path = config_path or get_config_path()

    if not path.exists():
        try:
            config = Config()
        except SettingsError as exc:
            raise ConfigLoadError(
                path,
                kind="invalid_schema",
                summary=(
                    "Environment-based configuration could not be parsed. "
                    "Check that complex NANOBOT_* values use valid JSON."
                ),
            ) from exc
        except ValidationError as exc:
            raise ConfigLoadError(
                path,
                kind="invalid_schema",
                summary="Environment-based configuration is invalid.",
                issues=validation_issues(exc),
            ) from exc
        config.bind_source_path(path)
        _apply_ssrf_whitelist(config)
        return config

    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except json.JSONDecodeError as exc:
        raise ConfigLoadError(
            path,
            kind="invalid_json",
            summary=(
                f"JSON syntax error at line {exc.lineno}, column {exc.colno}: "
                f"{_sentence(exc.msg)}"
            ),
        ) from exc
    except UnicodeDecodeError as exc:
        raise ConfigLoadError(
            path,
            kind="io_error",
            summary="The file is not valid UTF-8.",
        ) from exc
    except OSError as exc:
        detail = exc.strerror or type(exc).__name__
        raise ConfigLoadError(
            path,
            kind="io_error",
            summary=f"Unable to read the file: {_sentence(detail)}",
        ) from exc

    if not isinstance(data, dict):
        root_type = type(data).__name__
        raise ConfigLoadError(
            path,
            kind="invalid_root",
            summary="The top level of config.json must be a JSON object.",
            issues=(
                ConfigIssue(
                    path=(),
                    message=f"Expected an object, but found {root_type}.",
                ),
            ),
        )

    raw = cast(dict[str, Any], data)
    retained = legacy_config_keys(raw)
    # The root model rejects unknown keys. Drop only the retained `api` copy
    # from the validated document; save_config writes that copy back.
    collapsed = _collapse_equal_aliases(dict(raw), "", path)
    migrated = _migrate_config(collapsed if isinstance(collapsed, dict) else dict(raw))
    if isinstance(migrated, dict) and "api" in migrated:
        migrated = {key: value for key, value in migrated.items() if key != "api"}
    data = migrated
    try:
        config = Config.model_validate(data)
    except ValidationError as exc:
        issues = validation_issues(exc)
        raise ConfigLoadError(
            path,
            kind="invalid_schema",
            summary=f"Found {len(issues)} invalid setting(s).",
            issues=issues,
        ) from exc

    config._retained_legacy = retained
    removed = {
        _canon_path(item_path)
        for item_path, _value in _iter_leaves(raw)
        if _canon_path(item_path) not in {
            _canon_path(migrated_path) for migrated_path, _migrated in _iter_leaves(data)
        }
    }
    config._retained_unknowns = _unknown_entries(raw, config, removed)
    _warn_retained_legacy(retained)
    config.bind_source_path(path)
    _apply_ssrf_whitelist(config)
    return config


def _apply_ssrf_whitelist(config: Config) -> None:
    from nanobot.security.network import configure_ssrf_whitelist

    configure_ssrf_whitelist(config.tools.ssrf_whitelist)


def save_config(config: Config, config_path: Path | None = None) -> None:
    """
    Save configuration to file.

    Args:
        config: Configuration to save.
        config_path: Optional path to save to. Uses default if not provided.
    """
    path = config_path or get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = dump_config(config)
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ConfigWriteError(
                f"Refusing to write {path} because the existing file could not be parsed. "
                "A save would risk dropping configuration values."
            ) from exc
        if isinstance(existing, dict):
            _reject_lossy_write(path, existing, data)

    # OAuth credentials live in dedicated token stores. Persist only the
    # non-credential request settings consumed by these provider backends.
    for alias, provider in (
        ("openaiCodex", config.providers.openai_codex),
        ("xaiGrok", config.providers.xai_grok),
    ):
        settings = provider.model_dump(
            mode="json",
            by_alias=True,
            include={"use_proxy", "extra_body"},
            exclude_none=True,
            exclude_unset=True,
        )
        if settings:
            data.setdefault("providers", {})[alias] = settings

    # Temp + replace so a crash mid-write cannot leave a truncated config.json.
    write_text_atomic(path, json.dumps(data, indent=2, ensure_ascii=False))


def merge_missing_defaults(existing: object, defaults: object) -> object:
    """Recursively add missing defaults without replacing configured values."""
    if not isinstance(existing, dict) or not isinstance(defaults, dict):
        return cast(object, existing)

    existing_dict = cast(dict[str, object], existing)
    defaults_dict = cast(dict[str, object], defaults)
    merged = dict(existing_dict)
    for key, value in defaults_dict.items():
        if key not in merged:
            merged[key] = value
        else:
            merged[key] = merge_missing_defaults(merged[key], value)
    return merged


_ENV_REF_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_ConfigValue = TypeVar("_ConfigValue")


def resolve_config_env_vars(
    config: _ConfigValue,
    *,
    config_path: Path | None = None,
) -> _ConfigValue:
    """Return a config or config subtree with ``${VAR}`` references resolved.

    Walks in place so fields declared with ``exclude=True`` survive;
    returns the same instance when no references are present.
    Raises ``ConfigLoadError`` if a referenced variable is not set.
    """
    missing = tuple(_missing_env_issues(config))
    if missing:
        raise ConfigLoadError(
            config_path or get_config_path(),
            kind="missing_env",
            summary=f"Found {len(missing)} missing environment variable reference(s).",
            issues=missing,
        )
    return _resolve_in_place(config)


@overload
def resolve_env_refs(value: str) -> str: ...


@overload
def resolve_env_refs(value: object) -> object: ...


def resolve_env_refs(value: object) -> object:
    """Resolve ``${VAR}`` references in a single string, leniently.

    Unlike :func:`resolve_config_env_vars` (which walks a whole ``Config`` and
    raises on a missing variable), this resolves one value and returns an empty
    string if any reference is unset. It is meant for individual, lazily consumed
    fields — e.g. a transcription provider's ``api_key`` or ``api_base`` — so a
    missing variable degrades to "not configured" instead of producing a partial
    value. Non-string input is returned unchanged.
    """
    if not isinstance(value, str):
        return value
    names = _ENV_REF_PATTERN.findall(value)
    if any(name not in os.environ for name in names):
        return ""
    return _ENV_REF_PATTERN.sub(lambda m: os.environ[m.group(1)], value)


def _resolve_in_place(obj: Any) -> Any:
    if isinstance(obj, NetworkConfig):
        proxy = obj.resolve_environment()
        return obj.model_copy(update={"proxy": proxy}) if proxy != obj.proxy else obj
    if isinstance(obj, str):
        new = _ENV_REF_PATTERN.sub(_env_replace, obj)
        return new if new != obj else obj
    if isinstance(obj, BaseModel):
        updates: dict[str, Any] = {}
        for name in type(obj).model_fields:
            old = getattr(obj, name)
            new = _resolve_in_place(old)
            if new is not old:
                updates[name] = new
        extras = obj.__pydantic_extra__
        new_extras: dict[str, Any] | None = None
        if extras:
            resolved = {k: _resolve_in_place(v) for k, v in extras.items()}
            if any(resolved[k] is not extras[k] for k in extras):
                new_extras = resolved
        if not updates and new_extras is None:
            return obj
        copy = obj.model_copy(update=updates) if updates else obj.model_copy()
        if new_extras is not None:
            copy.__pydantic_extra__ = new_extras
        return copy
    if isinstance(obj, dict):
        object_dict = cast(dict[str, Any], obj)
        resolved = {key: _resolve_in_place(value) for key, value in object_dict.items()}
        return (
            resolved
            if any(resolved[key] is not object_dict[key] for key in object_dict)
            else cast(object, obj)
        )
    if isinstance(obj, list):
        object_list = cast(list[Any], obj)
        resolved = [_resolve_in_place(value) for value in object_list]
        return (
            resolved
            if any(new is not old for new, old in zip(resolved, object_list))
            else cast(object, obj)
        )
    return obj


def _missing_env_issues(
    obj: Any,
    path: tuple[str | int, ...] = (),
) -> list[ConfigIssue]:
    if isinstance(obj, str):
        return [
            ConfigIssue(
                path=path,
                message=f"Environment variable '{name}' is not set.",
            )
            for name in dict.fromkeys(_ENV_REF_PATTERN.findall(obj))
            if name not in os.environ
        ]
    if isinstance(obj, BaseModel):
        issues: list[ConfigIssue] = []
        for name, field in type(obj).model_fields.items():
            alias = field.serialization_alias or field.alias or name
            part = alias
            issues.extend(_missing_env_issues(getattr(obj, name), (*path, part)))
        for name, value in (obj.__pydantic_extra__ or {}).items():
            issues.extend(_missing_env_issues(value, (*path, name)))
        return issues
    if isinstance(obj, dict):
        object_dict = cast(dict[str | int, Any], obj)
        issues = []
        for name, value in object_dict.items():
            part = name
            issues.extend(_missing_env_issues(value, (*path, part)))
        return issues
    if isinstance(obj, list):
        issues = []
        for index, value in enumerate(cast(list[Any], obj)):
            issues.extend(_missing_env_issues(value, (*path, index)))
        return issues
    return []


def _resolve_env_vars(obj: object) -> object:
    if isinstance(obj, str):
        return _ENV_REF_PATTERN.sub(_env_replace, obj)
    if isinstance(obj, dict):
        return {
            key: _resolve_env_vars(value)
            for key, value in cast(dict[str, object], obj).items()
        }
    if isinstance(obj, list):
        return [_resolve_env_vars(value) for value in cast(list[object], obj)]
    return obj


def _env_replace(match: re.Match[str]) -> str:
    name = match.group(1)
    value = os.environ.get(name)
    if value is None:
        raise ValueError(
            f"Environment variable '{name}' referenced in config is not set"
        )
    return value


def _migrate_config(data: dict[str, Any]) -> dict[str, Any]:
    tools_value = data.get("tools", {})
    if not isinstance(tools_value, dict):
        return data
    tools = cast(dict[str, Any], tools_value)
    exec_cfg = _as_config_object(tools.get("exec", {}))
    if (
        exec_cfg is not None
        and "restrictToWorkspace" in exec_cfg
        and "restrictToWorkspace" not in tools
    ):
        tools["restrictToWorkspace"] = exec_cfg.pop("restrictToWorkspace")

    # Move tools.myEnabled / tools.mySet → tools.my.{enable, allowSet}.
    # The old flat keys shipped in the initial MyTool landing; wrapping them in a
    # sub-config keeps `web` / `exec` / `my` symmetric and gives room to grow.
    if "myEnabled" in tools or "mySet" in tools:
        my_cfg = tools.get("my")
        if my_cfg is None:
            my_cfg = {}
            tools["my"] = my_cfg
        if not isinstance(my_cfg, dict):
            return data
        my_cfg = cast(dict[str, Any], my_cfg)
        if "myEnabled" in tools and "enable" not in my_cfg:
            my_cfg["enable"] = tools.pop("myEnabled")
        else:
            tools.pop("myEnabled", None)
        if "mySet" in tools and "allowSet" not in my_cfg:
            my_cfg["allowSet"] = tools.pop("mySet")
        else:
            tools.pop("mySet", None)

    return data


def _sentence(message: str) -> str:
    message = message.strip()
    if message and message[-1] not in ".!?":
        message += "."
    return message
