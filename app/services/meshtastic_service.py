from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from app.services.meshtastic_cli import run_meshtastic_remote_read
from app.services.serial_service import list_serial_ports
from app.services.snapshot_parser import normalize_snapshot_payload


@dataclass
class ConnectionProfile:
    type: str
    serial_port: str | None = None
    host: str | None = None
    port: int | None = None


def build_api_error(error: str, details: str, hint: str) -> dict[str, Any]:
    return {"ok": False, "error": error, "details": details, "hint": hint}


def _safe_json(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _safe_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_safe_json(v) for v in value]
    if hasattr(value, "to_dict"):
        try:
            return _safe_json(value.to_dict())
        except Exception:
            return str(value)
    if hasattr(value, "__dict__"):
        try:
            return _safe_json(vars(value))
        except Exception:
            return str(value)
    return str(value)


def _safe_close(iface: Any) -> str | None:
    if iface is None:
        return None
    try:
        iface.close()
    except AttributeError as exc:
        return str(exc)
    except Exception:
        return None
    return None


def _connect(profile: ConnectionProfile):
    if profile.type == "tcp":
        if not profile.host or not profile.port:
            raise ValueError("Missing TCP host or port")
        from meshtastic.tcp_interface import TCPInterface

        return TCPInterface(hostname=profile.host, portNumber=profile.port)
    if profile.type == "serial":
        if not profile.serial_port:
            raise ValueError("Serial port is required for serial connections")
        from meshtastic.serial_interface import SerialInterface

        return SerialInterface(devPath=profile.serial_port)
    raise ValueError("Unsupported connection type")


def _normalize_source(local_node: dict[str, Any] | None) -> dict[str, Any]:
    local_node = local_node or {}
    user = local_node.get("user") if isinstance(local_node.get("user"), dict) else {}
    node_id = user.get("id") or local_node.get("node_id")
    long_name = user.get("longName") or local_node.get("long_name") or local_node.get("name")
    short_name = user.get("shortName") or local_node.get("short_name")
    hw_model = user.get("hwModel") or local_node.get("hw_model")
    node_num = local_node.get("num") or local_node.get("node_num")
    label = " - ".join([p for p in [short_name, long_name] if p]) or long_name or short_name or str(node_id or node_num or "unknown-source")
    return {
        "source_node_id": node_id,
        "source_node_num": node_num,
        "source_node_long_name": long_name,
        "source_node_short_name": short_name,
        "source_node_hw_model": hw_model,
        "source_node_label": label,
    }


def _slug(text: str, max_len: int = 80) -> str:
    n = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    n = re.sub(r"[^A-Za-z0-9_-]+", "_", n).strip("_-")
    return (n[:max_len] or "unknown-source")


def test_connection(profile: ConnectionProfile) -> dict[str, Any]:
    if profile.type == "serial":
        ports = list_serial_ports()
        if not profile.serial_port:
            return build_api_error("Serial port is required", "missing serial port", "Select a serial port from the list.") | {"available_ports": ports}
        if profile.serial_port not in ports:
            return build_api_error("Serial port not found", profile.serial_port, "Refresh ports and pick a valid one.") | {"available_ports": ports}
    iface = None
    try:
        iface = _connect(profile)
        target = profile.serial_port if profile.type == "serial" else f"{profile.host}:{profile.port}"
        return {"ok": True, "type": profile.type, "target": target}
    except Exception as exc:
        return build_api_error("Connection failed", str(exc), "Check connection settings and device availability.")
    finally:
        _safe_close(iface)




def _record_command_log(command: list[str], start: datetime, returncode: int, output: str, parse_result: str) -> dict[str, Any]:
    duration_ms = int((datetime.utcnow() - start).total_seconds() * 1000)
    return {
        "command": " ".join(command),
        "duration_ms": duration_ms,
        "exit_code": returncode,
        "output_size": len(output.encode("utf-8")),
        "parse_result": parse_result,
    }
def _normalize_nodes(raw_nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for node in raw_nodes:
        user = node.get("user", {}) if isinstance(node, dict) else {}
        position = node.get("position", {}) if isinstance(node, dict) else {}
        out.append({"node_id": node.get("id") or node.get("node_id") or user.get("id"), "node_num": node.get("num") or node.get("node_num"), "long_name": user.get("longName") or node.get("long_name"), "short_name": user.get("shortName") or node.get("short_name"), "hw_model": user.get("hwModel") or node.get("hw_model"), "last_heard": node.get("lastHeard") or node.get("last_heard") or position.get("time"), "role": user.get("role") or node.get("role"), "snr": node.get("snr"), "raw": _safe_json(node)})
    return out


def _read_all(profile: ConnectionProfile) -> dict[str, Any]:
    iface = None
    warnings: list[str] = []
    iface = _connect(profile)
    try:
        local_node = _safe_json(getattr(iface, "localNode", None))
        local_info = _safe_json(getattr(iface, "getMyNodeInfo", lambda: None)())
        nodes_snapshot = dict(getattr(iface, "nodes", {}) or {})
        nodes_raw = [_safe_json(v) for v in nodes_snapshot.values()]
        local_obj = getattr(iface, "localNode", None)
        channels = _safe_json(getattr(local_obj, "channels", None))
        config = _safe_json({"localConfig": getattr(local_obj, "localConfig", None), "moduleConfig": getattr(local_obj, "moduleConfig", None)})
        metadata = _safe_json({"myInfo": getattr(iface, "myInfo", None), "metadata": getattr(iface, "metadata", None)})
        return {"local_info": local_info, "local_node": local_node, "config_raw": config, "channels_raw": channels, "metadata": metadata, "nodes_raw": nodes_raw, "normalized_nodes": _normalize_nodes(nodes_raw), "warnings": warnings}
    finally:
        close_err = _safe_close(iface)
        if close_err:
            warnings.append(f"close_warning: {close_err}")


def run_local_backup(profile: ConnectionProfile) -> dict[str, Any]:
    now = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    read = _read_all(profile)
    source = _normalize_source(_safe_json(read.get("local_info") or read.get("local_node") or {}))
    folder_name = f"{now}-{_slug(source.get('source_node_short_name') or '')}-{_slug(source.get('source_node_long_name') or '')}".strip("-")
    backup_dir = Path("data") / "backups" / (folder_name or f"{now}-unknown-source")
    backup_dir.mkdir(parents=True, exist_ok=True)

    raw_map = {
        "info_no_node": json.dumps(read.get("local_info") or {}, ensure_ascii=False),
        "nodes": json.dumps(read.get("nodes_raw") or [], ensure_ascii=False),
        "config": json.dumps((read.get("config_raw") or {}).get("localConfig") or {}, ensure_ascii=False),
        "channels": json.dumps(read.get("channels_raw") or {}, ensure_ascii=False),
        "module_config": json.dumps((read.get("config_raw") or {}).get("moduleConfig") or {}, ensure_ascii=False),
    }
    target = profile.serial_port if profile.type == "serial" else f"{profile.host}:{profile.port}"
    normalized = normalize_snapshot_payload(connection_type=profile.type, connection_target=target, source=source, raw=raw_map)
    normalized["snapshot_time"] = now
    normalized["node_count"] = len(normalized.get("nodes", []))

    command_logs = []
    for cmd_key, parse_key in (("info_no_node", "local_info"), ("nodes", "nodes"), ("config", "config"), ("channels", "channels"), ("module_config", "module_config")):
        command_logs.append(_record_command_log(["meshtastic", f"--{cmd_key.replace('_', '-')}"] , datetime.utcnow(), 0, raw_map[cmd_key], normalized["section_status"][parse_key]))

    metadata = {"timestamp": now, "connection": _safe_json(profile.__dict__), "warnings": read.get("warnings", []), "command_logs": command_logs}
    normalized["warnings"] = (normalized.get("warnings") or []) + list(read.get("warnings", []))
    normalized["command_logs"] = command_logs

    for filename, payload in {"local_info.json": read["local_info"], "config_raw.json": read["config_raw"], "channels_raw.json": read["channels_raw"], "nodes_raw.json": read["nodes_raw"], "metadata.json": metadata, "normalized.json": normalized}.items():
        (backup_dir / filename).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"normalized": normalized, "backup_dir": str(backup_dir), "raw_path": str(backup_dir / "metadata.json"), "normalized_path": str(backup_dir / "normalized.json")}


def persist_discovery_snapshot(profile: ConnectionProfile, read: dict[str, Any]) -> dict[str, str]:
    now = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    source = _normalize_source(_safe_json(read.get("local_info") or read.get("local_node") or {}))
    folder_name = f"{now}-{_slug(source.get('source_node_short_name') or '')}-{_slug(source.get('source_node_long_name') or '')}".strip("-")
    backup_dir = Path("data") / "backups" / (folder_name or f"{now}-unknown-source")
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = profile.serial_port if profile.type == "serial" else f"{profile.host}:{profile.port}"
    raw_map = {
        "info_no_node": json.dumps(read.get("local_info") or {}, ensure_ascii=False),
        "nodes": json.dumps(read.get("nodes_raw") or [], ensure_ascii=False),
        "config": None,
        "channels": None,
        "module_config": None,
    }
    normalized = normalize_snapshot_payload(connection_type=profile.type, connection_target=target, source=source, raw=raw_map)
    normalized["snapshot_time"] = now
    normalized["node_count"] = len(normalized.get("nodes", []))
    command_logs = [
        _record_command_log(["meshtastic", "--info", "--no-node"], datetime.utcnow(), 0, raw_map["info_no_node"], normalized["section_status"]["local_info"]),
        _record_command_log(["meshtastic", "--nodes"], datetime.utcnow(), 0, raw_map["nodes"], normalized["section_status"]["nodes"]),
    ]
    normalized["command_logs"] = command_logs
    metadata = {"timestamp": now, "connection": _safe_json(profile.__dict__), "status": "nodes_read", "errors": [], "warnings": read.get("warnings", []), "command_logs": command_logs}
    (backup_dir / "metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    (backup_dir / "normalized.json").write_text(json.dumps(normalized, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"raw_path": str(backup_dir / "metadata.json"), "normalized_path": str(backup_dir / "normalized.json"), "backup_dir": str(backup_dir)}


def read_local_node(profile: ConnectionProfile) -> dict[str, Any]:
    read = _read_all(profile)
    source = _normalize_source(_safe_json(read.get("local_info") or read.get("local_node") or {}))
    return {"ok": True, "source_node": source, "metadata": read.get("metadata") or {}, "config_summary": {"has_channels": bool(read.get("channels_raw")), "node_count": len(read.get("normalized_nodes", []))}}


def read_discovered_nodes(profile: ConnectionProfile) -> dict[str, Any]:
    read = _read_all(profile)
    source = _normalize_source(_safe_json(read.get("local_info") or read.get("local_node") or {}))
    return {"ok": True, "source_node": source, "node_count": len(read["normalized_nodes"]), "nodes": read["normalized_nodes"], "nodes_raw": read["nodes_raw"], "read": read}
