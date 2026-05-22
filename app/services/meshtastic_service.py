from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from app.services.meshtastic_cli import run_meshtastic_remote_read
from app.services.serial_service import list_serial_ports


@dataclass
class ConnectionProfile:
    type: str
    serial_port: str | None = None
    host: str | None = None
    port: int | None = None


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


def _connect(profile: ConnectionProfile):
    if profile.type == "tcp":
        from meshtastic.tcp_interface import TCPInterface

        return TCPInterface(hostname=profile.host, portNumber=profile.port)
    from meshtastic.serial_interface import SerialInterface

    return SerialInterface(devPath=profile.serial_port)


def test_connection(profile: ConnectionProfile) -> dict[str, Any]:
    if profile.type == "serial":
        ports = list_serial_ports()
        if not profile.serial_port:
            return {"ok": False, "error": "missing_serial_port", "available_ports": ports}
        if profile.serial_port not in ports:
            return {"ok": False, "error": "serial_port_not_found", "available_ports": ports}
    if profile.type == "tcp" and (not profile.host or not profile.port):
        return {"ok": False, "error": "missing_tcp_host_or_port"}

    iface = None
    try:
        iface = _connect(profile)
        target = profile.serial_port if profile.type == "serial" else f"{profile.host}:{profile.port}"
        return {"ok": True, "type": profile.type, "target": target}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        if iface is not None:
            try:
                iface.close()
            except Exception:
                pass


def _normalize_nodes(raw_nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for node in raw_nodes:
        user = node.get("user", {}) if isinstance(node, dict) else {}
        position = node.get("position", {}) if isinstance(node, dict) else {}
        out.append(
            {
                "node_id": node.get("id") or node.get("node_id") or user.get("id"),
                "node_num": node.get("num") or node.get("node_num"),
                "long_name": user.get("longName") or node.get("long_name"),
                "short_name": user.get("shortName") or node.get("short_name"),
                "hw_model": user.get("hwModel") or node.get("hw_model"),
                "last_heard": node.get("lastHeard") or node.get("last_heard") or position.get("time"),
                "role": user.get("role") or node.get("role"),
                "snr": node.get("snr"),
                "raw": _safe_json(node),
            }
        )
    return out


def _read_all(profile: ConnectionProfile) -> dict[str, Any]:
    iface = _connect(profile)
    try:
        local_node = _safe_json(getattr(iface, "localNode", None))
        local_info = _safe_json(getattr(iface, "getMyNodeInfo", lambda: None)())
        config = _safe_json(getattr(getattr(iface, "localNode", None), "localConfig", None))
        channels = _safe_json(getattr(getattr(iface, "localNode", None), "channels", None))
        nodes_obj = _safe_json(getattr(iface, "nodes", {}))
        nodes_raw = list(nodes_obj.values()) if isinstance(nodes_obj, dict) else (nodes_obj if isinstance(nodes_obj, list) else [])
        return {
            "local_info": local_info,
            "local_node": local_node,
            "config_raw": config,
            "channels_raw": channels,
            "nodes_raw": _safe_json(nodes_raw),
            "normalized_nodes": _normalize_nodes(nodes_raw),
        }
    finally:
        iface.close()


def run_local_backup(profile: ConnectionProfile) -> dict[str, Any]:
    now = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    backup_dir = Path("data") / "backups" / f"{now}-local"
    backup_dir.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []

    try:
        read = _read_all(profile)
        status = "ok"
    except Exception as exc:
        read = {"local_info": None, "local_node": None, "config_raw": None, "channels_raw": None, "nodes_raw": [], "normalized_nodes": []}
        errors.append(str(exc))
        status = "failed"

    metadata = {
        "timestamp": now,
        "connection": _safe_json(profile.__dict__),
        "status": status,
        "errors": errors,
    }
    normalized = {
        "snapshot_time": now,
        "connection_type": profile.type,
        "connection_target": profile.serial_port if profile.type == "serial" else f"{profile.host}:{profile.port}",
        "local_node": _safe_json(read.get("local_info") or read.get("local_node") or {}),
        "node_count": len(read["normalized_nodes"]),
        "nodes": read["normalized_nodes"],
        "status": status,
        "errors": errors,
    }
    (backup_dir / "local_info.json").write_text(json.dumps(read["local_info"], indent=2, ensure_ascii=False), encoding="utf-8")
    (backup_dir / "config_raw.json").write_text(json.dumps(read["config_raw"], indent=2, ensure_ascii=False), encoding="utf-8")
    (backup_dir / "channels_raw.json").write_text(json.dumps(read["channels_raw"], indent=2, ensure_ascii=False), encoding="utf-8")
    (backup_dir / "nodes_raw.json").write_text(json.dumps(read["nodes_raw"], indent=2, ensure_ascii=False), encoding="utf-8")
    (backup_dir / "normalized.json").write_text(json.dumps(normalized, indent=2, ensure_ascii=False), encoding="utf-8")
    (backup_dir / "metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"normalized": normalized, "backup_dir": str(backup_dir), "raw_path": str(backup_dir / "metadata.json"), "normalized_path": str(backup_dir / "normalized.json")}


def read_local_node(profile: ConnectionProfile) -> dict[str, Any]:
    return _read_all(profile)


def read_discovered_nodes(profile: ConnectionProfile) -> dict[str, Any]:
    read = _read_all(profile)
    return {"nodes": read["normalized_nodes"], "nodes_raw": read["nodes_raw"]}


def run_remote_read_only(node_id: str, profile: ConnectionProfile, timeout_seconds: int = 8, retries: int = 2) -> dict[str, Any]:
    connection_test = test_connection(profile)
    now = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    attempts: list[dict[str, Any]] = []

    if not connection_test.get("ok"):
        final_error = str(connection_test.get("error", "connection_unavailable"))
        remote_config = None
    else:
        final_error = "unknown_error"
        remote_config = None
        for idx in range(1, max(retries, 1) + 1):
            result = run_meshtastic_remote_read(node_id=node_id, port=profile.serial_port or "", timeout_seconds=timeout_seconds)
            attempts.append({"attempt": idx, "ok": result.ok, "error": result.error, "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr})
            if result.ok:
                final_error = ""
                remote_config = result.info if result.info else {"raw_stdout": result.stdout}
                break
            final_error = str(result.error or "command_failed")

    raw_payload = {"timestamp": now, "node_id": node_id, "gateway": profile.__dict__, "attempts": attempts, "error": final_error or None, "remote_config": remote_config}
    normalized = {"snapshot_time": now, "node_id": node_id, "gateway_connection_type": profile.type, "gateway_connection_target": connection_test.get("target") or "unavailable", "status": "ok" if remote_config is not None else "failed", "verified": False, "errors": [] if remote_config is not None else [final_error], "remote_config_summary": {"key_count": len(remote_config.keys()) if isinstance(remote_config, dict) else 0, "keys": sorted(remote_config.keys())[:20] if isinstance(remote_config, dict) else []} if remote_config is not None else None}
    backups_dir = Path("data") / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    base_filename = f"remote_read_{node_id}_{now}_{profile.type}"
    raw_path = backups_dir / f"{base_filename}_raw.json"
    normalized_path = backups_dir / f"{base_filename}_normalized.json"
    raw_path.write_text(json.dumps(raw_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    normalized_path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"raw": raw_payload, "normalized": normalized, "raw_path": str(raw_path), "normalized_path": str(normalized_path), "attempts": len(attempts)}
