from __future__ import annotations

import json
from typing import Any


NOT_COLLECTED = "not_collected"


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
    if isinstance(payload, dict) and isinstance(payload.get("nodes"), list):
        return [n for n in payload["nodes"] if isinstance(n, dict)]
    return []


def normalize_snapshot_payload(
    *,
    connection_type: str,
    connection_target: str,
    source: dict[str, Any],
    raw: dict[str, str | None],
) -> dict[str, Any]:
    info_payload, info_err = _parse_json_payload(raw.get("info_no_node"))
    nodes_payload, nodes_err = _parse_json_payload(raw.get("nodes"))

    local_device_info: Any = info_payload if isinstance(info_payload, dict) else NOT_COLLECTED
    nodes: Any = _to_node_list(nodes_payload) if raw.get("nodes") is not None else NOT_COLLECTED
    export_config: Any = raw.get("export_config") or NOT_COLLECTED

    parse_errors: list[str] = []
    if info_err:
        parse_errors.append(f"info_no_node: {info_err}")
    if nodes_err:
        parse_errors.append(f"nodes: {nodes_err}")

    normalized = {
        "source": {
            "connection_type": connection_type,
            "connection_target": connection_target,
            "node_id": source.get("source_node_id"),
            "long_name": source.get("source_node_long_name"),
            "short_name": source.get("source_node_short_name"),
            "label": source.get("source_node_label"),
        },
        "local_device_info": local_device_info,
        "export_config": export_config,
        "nodes": nodes,
        "config": NOT_COLLECTED,
        "channels": NOT_COLLECTED,
        "module_config": NOT_COLLECTED,
        "raw": {
            "info_no_node": raw.get("info_no_node") if raw.get("info_no_node") is not None else NOT_COLLECTED,
            "nodes": raw.get("nodes") if raw.get("nodes") is not None else NOT_COLLECTED,
            "export_config": raw.get("export_config") if raw.get("export_config") is not None else NOT_COLLECTED,
        },
        "warnings": [],
        "parse_errors": parse_errors,
    }
    return normalized
