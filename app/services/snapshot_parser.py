from __future__ import annotations

import json
from typing import Any


def _parse_json_payload(raw: str | None) -> tuple[Any, str | None]:
    if raw is None:
        return None, None
    text = str(raw).strip()
    if text == "":
        return None, None
    try:
        return json.loads(text), None
    except json.JSONDecodeError as exc:
        return None, f"parse_failed: {exc.msg}"


def _to_node_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [n for n in payload if isinstance(n, dict)]
    if isinstance(payload, dict):
        nodes = payload.get("nodes")
        if isinstance(nodes, list):
            return [n for n in nodes if isinstance(n, dict)]
    return []


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, (list, dict, str)):
        return len(value) == 0
    return False


def section_status(collected: bool, parse_error: str | None, value: Any) -> str:
    if not collected:
        return "Not collected"
    if parse_error:
        return "Parse failed"
    if _is_empty(value):
        return "Empty"
    return "OK"


def normalize_snapshot_payload(
    *,
    connection_type: str,
    connection_target: str,
    source: dict[str, Any],
    raw: dict[str, str | None],
) -> dict[str, Any]:
    info_payload, info_err = _parse_json_payload(raw.get("info_no_node"))
    nodes_payload, nodes_err = _parse_json_payload(raw.get("nodes"))
    config_payload, config_err = _parse_json_payload(raw.get("config"))
    channels_payload, channels_err = _parse_json_payload(raw.get("channels"))
    module_payload, module_err = _parse_json_payload(raw.get("module_config"))

    parse_errors: list[str] = []
    for key, err in (
        ("info_no_node", info_err),
        ("nodes", nodes_err),
        ("config", config_err),
        ("channels", channels_err),
        ("module_config", module_err),
    ):
        if err:
            parse_errors.append(f"{key}: {err}")

    local_info = info_payload if isinstance(info_payload, dict) else {}
    nodes = _to_node_list(nodes_payload)
    config = config_payload if isinstance(config_payload, dict) else {}
    channels = channels_payload if isinstance(channels_payload, (dict, list)) else {}
    module_config = module_payload if isinstance(module_payload, dict) else {}

    normalized = {
        "source": {
            "connection_type": connection_type,
            "connection_target": connection_target,
            "node_id": source.get("source_node_id"),
            "long_name": source.get("source_node_long_name"),
            "short_name": source.get("source_node_short_name"),
            "label": source.get("source_node_label"),
        },
        "local_info": local_info,
        "config": config,
        "channels": channels,
        "module_config": module_config,
        "nodes": nodes,
        "raw": {
            "info_no_node": raw.get("info_no_node") or "",
            "nodes": raw.get("nodes") or "",
            "config": raw.get("config") or "",
            "channels": raw.get("channels") or "",
            "module_config": raw.get("module_config") or "",
        },
        "parse_errors": parse_errors,
        "warnings": [],
        "section_status": {
            "local_info": section_status(raw.get("info_no_node") is not None, info_err, local_info),
            "config": section_status(raw.get("config") is not None, config_err, config),
            "channels": section_status(raw.get("channels") is not None, channels_err, channels),
            "module_config": section_status(raw.get("module_config") is not None, module_err, module_config),
            "nodes": section_status(raw.get("nodes") is not None, nodes_err, nodes),
        },
    }
    return normalized
