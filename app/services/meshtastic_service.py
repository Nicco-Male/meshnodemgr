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


def test_connection(profile: ConnectionProfile) -> dict[str, Any]:
    if profile.type == "serial":
        ports = list_serial_ports()
        if not profile.serial_port:
            return {"ok": False, "error": "missing_serial_port", "available_ports": ports}
        if profile.serial_port not in ports:
            return {"ok": False, "error": "serial_port_not_found", "available_ports": ports}
        return {"ok": True, "type": "serial", "target": profile.serial_port}

    if profile.type == "tcp":
        if not profile.host or not profile.port:
            return {"ok": False, "error": "missing_tcp_host_or_port"}
        return {"ok": True, "type": "tcp", "target": f"{profile.host}:{profile.port}"}

    return {"ok": False, "error": "invalid_connection_type"}


def run_local_backup(profile: ConnectionProfile) -> dict[str, Any]:
    connection_test = test_connection(profile)
    now = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

    raw_payload: dict[str, Any] = {
        "timestamp": now,
        "connection": profile.__dict__,
        "connection_test": connection_test,
        "local_node_info": None,
        "local_config": None,
        "known_nodes": [],
        "errors": [],
    }

    if not connection_test.get("ok"):
        raw_payload["errors"].append("connection_unavailable")
    else:
        raw_payload["errors"].append("meshtastic_runtime_not_implemented")

    normalized_nodes: list[dict[str, Any]] = []
    normalized = {
        "snapshot_time": now,
        "connection_type": profile.type,
        "connection_target": connection_test.get("target") or "unavailable",
        "local_node": {
            "node_id": None,
            "short_name": None,
            "long_name": None,
        },
        "node_count": len(normalized_nodes),
        "nodes": normalized_nodes,
        "status": "partial" if raw_payload["errors"] else "ok",
        "errors": raw_payload["errors"],
    }

    backups_dir = Path("data") / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    base_filename = f"snapshot_{now}_{profile.type}"
    raw_path = backups_dir / f"{base_filename}_raw.json"
    normalized_path = backups_dir / f"{base_filename}_normalized.json"

    raw_path.write_text(json.dumps(raw_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    normalized_path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "raw": raw_payload,
        "normalized": normalized,
        "raw_path": str(raw_path),
        "normalized_path": str(normalized_path),
    }


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
            attempts.append(
                {
                    "attempt": idx,
                    "ok": result.ok,
                    "error": result.error,
                    "returncode": result.returncode,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                }
            )
            if result.ok:
                final_error = ""
                remote_config = result.info if result.info else {"raw_stdout": result.stdout}
                break
            final_error = str(result.error or "command_failed")

    raw_payload = {
        "timestamp": now,
        "node_id": node_id,
        "gateway": profile.__dict__,
        "attempts": attempts,
        "error": final_error or None,
        "remote_config": remote_config,
    }
    normalized = {
        "snapshot_time": now,
        "node_id": node_id,
        "gateway_connection_type": profile.type,
        "gateway_connection_target": connection_test.get("target") or "unavailable",
        "status": "ok" if remote_config is not None else "failed",
        "verified": False,
        "errors": [] if remote_config is not None else [final_error],
        "remote_config_summary": {
            "key_count": len(remote_config.keys()) if isinstance(remote_config, dict) else 0,
            "keys": sorted(remote_config.keys())[:20] if isinstance(remote_config, dict) else [],
        }
        if remote_config is not None
        else None,
    }
    backups_dir = Path("data") / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    base_filename = f"remote_read_{node_id}_{now}_{profile.type}"
    raw_path = backups_dir / f"{base_filename}_raw.json"
    normalized_path = backups_dir / f"{base_filename}_normalized.json"
    raw_path.write_text(json.dumps(raw_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    normalized_path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "raw": raw_payload,
        "normalized": normalized,
        "raw_path": str(raw_path),
        "normalized_path": str(normalized_path),
        "attempts": len(attempts),
    }
