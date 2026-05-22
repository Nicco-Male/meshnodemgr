from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass
class YamlDiscoveryItem:
    filename: str
    path: str
    valid: bool
    kind: str
    name: str | None = None
    description: str | None = None
    errors: list[str] | None = None


def discover_profiles(base_dir: Path) -> list[YamlDiscoveryItem]:
    return _discover_yaml_files(base_dir=base_dir / "profiles", kind="profile")


def discover_playbooks(base_dir: Path) -> list[YamlDiscoveryItem]:
    return _discover_yaml_files(base_dir=base_dir / "playbooks", kind="playbook")


def _discover_yaml_files(base_dir: Path, kind: str) -> list[YamlDiscoveryItem]:
    if not base_dir.exists() or not base_dir.is_dir():
        return []

    items: list[YamlDiscoveryItem] = []
    for path in sorted(base_dir.iterdir()):
        if not path.is_file() or path.suffix.lower() not in {".yaml", ".yml"}:
            continue

        items.append(_parse_yaml_item(path=path, kind=kind))

    return items


def _parse_yaml_item(path: Path, kind: str) -> YamlDiscoveryItem:
    try:
        with path.open("r", encoding="utf-8") as file_handle:
            raw = yaml.safe_load(file_handle)
    except yaml.YAMLError as exc:
        return YamlDiscoveryItem(
            filename=path.name,
            path=str(path),
            kind=kind,
            valid=False,
            errors=[f"Invalid YAML: {exc}"],
        )
    except OSError as exc:
        return YamlDiscoveryItem(
            filename=path.name,
            path=str(path),
            kind=kind,
            valid=False,
            errors=[f"Cannot read file: {exc}"],
        )

    errors = _validate_structure(raw=raw, kind=kind)
    if errors:
        return YamlDiscoveryItem(
            filename=path.name,
            path=str(path),
            kind=kind,
            valid=False,
            errors=errors,
        )

    data: dict[str, Any] = raw
    return YamlDiscoveryItem(
        filename=path.name,
        path=str(path),
        kind=kind,
        valid=True,
        name=str(data.get("name")) if data.get("name") is not None else None,
        description=str(data.get("description")) if data.get("description") is not None else None,
        errors=[],
    )


def _validate_structure(raw: Any, kind: str) -> list[str]:
    errors: list[str] = []

    if not isinstance(raw, dict):
        return ["Top-level YAML must be a mapping/object."]

    _require_string_field(raw, "name", errors)

    if "description" in raw and not isinstance(raw.get("description"), str):
        errors.append("Field 'description' must be a string when provided.")

    if kind == "profile":
        if "config" not in raw:
            errors.append("Profile must contain a 'config' mapping.")
        elif not isinstance(raw.get("config"), dict):
            errors.append("Field 'config' must be a mapping/object.")

    if kind == "playbook":
        if "targets" not in raw:
            errors.append("Playbook must contain a 'targets' list.")
        elif not isinstance(raw.get("targets"), list):
            errors.append("Field 'targets' must be a list.")

        if "tasks" not in raw:
            errors.append("Playbook must contain a 'tasks' list.")
        elif not isinstance(raw.get("tasks"), list):
            errors.append("Field 'tasks' must be a list.")

    return errors


def _require_string_field(raw: dict[str, Any], key: str, errors: list[str]) -> None:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        errors.append(f"Field '{key}' is required and must be a non-empty string.")
