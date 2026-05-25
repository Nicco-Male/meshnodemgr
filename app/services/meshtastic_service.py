from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from app.services.serial_service import list_serial_ports
from app.services.snapshot_parser import normalize_snapshot_payload


LOGGER = logging.getLogger("meshnodemgr.meshtastic")
SENSITIVE_KEYS = ("psk", "key", "private", "secret", "token", "passwd", "password")
RAW_MAX_DEBUG = 4000


@dataclass
class ConnectionProfile:
    type: str
    serial_port: str | None = None
    host: str | None = None
    port: int | None = None


def build_api_error(error: str, details: str, hint: str) -> dict[str, Any]:
    return {"ok": False, "error": f"{error}: {details}", "details": details, "hint": hint}


def _safe_json(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool, dict, list)):
        return value
    return str(value)


def _normalize_source(local_node: dict[str, Any] | None) -> dict[str, Any]:
    local_node = local_node or {}
    user = local_node.get("user") if isinstance(local_node.get("user"), dict) else {}
    node_id = user.get("id") or local_node.get("node_id")
    long_name = user.get("longName") or local_node.get("long_name") or local_node.get("name")
    short_name = user.get("shortName") or local_node.get("short_name")
    hw_model = user.get("hwModel") or local_node.get("hw_model")
    node_num = local_node.get("num") or local_node.get("node_num")
    label = " - ".join([p for p in [short_name, long_name] if p]) or long_name or short_name or str(node_id or node_num or "unknown-source")
    return {"source_node_id": node_id, "source_node_num": node_num, "source_node_long_name": long_name, "source_node_short_name": short_name, "source_node_hw_model": hw_model, "source_node_label": label}


def _slug(text: str, max_len: int = 80) -> str:
    n = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    n = re.sub(r"[^A-Za-z0-9_-]+", "_", n).strip("_-")
    return n[:max_len] or "unknown-source"


def _snapshot_name_from_source(source: dict[str, Any], timestamp: str) -> str:
    base = source.get("source_node_long_name") or source.get("source_node_short_name") or source.get("source_node_id") or source.get("source_node_num") or "unknown-source"
    return f"{_slug(str(base))}_{timestamp}_export-config.txt"


def test_connection(profile: ConnectionProfile) -> dict[str, Any]:
    if profile.type == "serial":
        ports = list_serial_ports()
        if not profile.serial_port:
            return build_api_error("Serial port is required", "missing serial port", "Select a serial port from the list.") | {"available_ports": ports}
    target = profile.serial_port if profile.type == "serial" else f"{profile.host}:{profile.port}"
    LOGGER.info("STEP test_connection | type=%s | target=%s", profile.type, target)
    return {"ok": True, "type": profile.type, "target": target}


def _mask_sensitive(text: str) -> str:
    masked = text or ""
    patterns = [
        r"(?i)(\b(?:psk|key|private|secret|token|passwd|password)\b\s*[=:]\s*)([^\s,;\]\}]+)",
        r'(?i)("(?:psk|key|private|secret|token|passwd|password)"\s*:\s*")([^"]+)(")',
    ]
    for pat in patterns:
        masked = re.sub(pat, lambda m: f"{m.group(1)}***" + (m.group(3) if len(m.groups()) >= 3 else ""), masked)
    return masked


def run_meshtastic_cli(step_name: str, args: list[str], connection: ConnectionProfile) -> dict[str, Any]:
    cmd = ["meshtastic"]
    if connection.type == "serial":
        cmd += ["--port", connection.serial_port or ""]
        target = connection.serial_port or ""
    else:
        cmd += ["--host", connection.host or "", "--port", str(connection.port or "")]
        target = connection.host or ""
    cmd += args
    LOGGER.info("CLI run | step=%s | command_name=%s | connection_type=%s | target=%s | command=%s", step_name, " ".join(args), connection.type, target, _mask_sensitive(" ".join(cmd)))
    t0 = time.perf_counter()
    try:
        cp = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=25)
        duration_ms = int((time.perf_counter() - t0) * 1000)
        LOGGER.info("CLI result | step=%s | return_code=%s | stdout_bytes=%s | stderr_bytes=%s | duration_ms=%s", step_name, cp.returncode, len(cp.stdout.encode("utf-8")), len(cp.stderr.encode("utf-8")), duration_ms)
        return {"ok": cp.returncode == 0, "step": step_name, "command": cmd, "exit_code": cp.returncode, "duration_ms": duration_ms, "stdout": cp.stdout or "", "stderr": cp.stderr or "", "error": None if cp.returncode == 0 else "command_failed"}
    except Exception as exc:
        duration_ms = int((time.perf_counter() - t0) * 1000)
        LOGGER.error("CLI failed | step=%s | error=%s | duration_ms=%s", step_name, _mask_sensitive(str(exc)), duration_ms)
        return {"ok": False, "step": step_name, "command": cmd, "exit_code": None, "duration_ms": duration_ms, "stdout": "", "stderr": str(exc), "error": str(exc)}


def _normalize_nodes(raw_nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for node in raw_nodes:
        user = node.get("user", {}) if isinstance(node, dict) else {}
        out.append({"node_id": node.get("id") or user.get("id"), "node_num": node.get("num"), "long_name": user.get("longName"), "short_name": user.get("shortName"), "hw_model": user.get("hwModel"), "role": user.get("role"), "snr": node.get("snr"), "raw": _safe_json(node)})
    return out


def run_local_backup(profile: ConnectionProfile) -> dict[str, Any]:
    now = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    export_step = run_meshtastic_cli("full_backup_export_config", ["--export-config"], profile)
    if not export_step.get("ok"):
        raise RuntimeError("export-config command failed")
    export_text = (export_step.get("stdout") or "").strip()
    if not export_text:
        raise RuntimeError("export-config produced empty output")

    local_step = run_meshtastic_cli("full_backup_local_info", ["--info", "--no-node"], profile)
    local_info = {}
    if local_step.get("ok") and local_step.get("stdout", "").strip():
        try:
            local_info = json.loads(local_step["stdout"])
        except Exception:
            local_info = {}
    source = _normalize_source(_safe_json(local_info))

    backup_dir = Path("data") / "backups" / f"{now}-local"
    backup_dir.mkdir(parents=True, exist_ok=True)
    export_filename = _snapshot_name_from_source(source, now)
    export_path = backup_dir / export_filename
    export_path.write_text(export_text + "\n", encoding="utf-8")
    LOGGER.info("CLI file | step=full_backup_export_config | output_path=%s", str(export_path))

    target = profile.serial_port if profile.type == "serial" else f"{profile.host}:{profile.port}"
    normalized = normalize_snapshot_payload(connection_type=profile.type, connection_target=target, source=source, raw={"info_no_node": local_step.get("stdout") if local_step.get("ok") else None, "nodes": None, "config": None, "channels": None, "module_config": None, "export_config": str(export_path)})
    normalized["status"] = "ok"
    normalized["snapshot_time"] = now
    normalized["node_count"] = 0

    metadata = {"timestamp": now, "connection": _safe_json(profile.__dict__), "export_file": str(export_path)}
    (backup_dir / "metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    (backup_dir / "normalized.json").write_text(json.dumps(normalized, indent=2, ensure_ascii=False), encoding="utf-8")

    return {"normalized": normalized, "backup_dir": str(backup_dir), "raw_path": str(backup_dir / "metadata.json"), "normalized_path": str(backup_dir / "normalized.json"), "export_path": str(export_path)}


def persist_discovery_snapshot(profile: ConnectionProfile, read: dict[str, Any]) -> dict[str, str]:
    now = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    source = read.get("source_node") or {}
    backup_dir = Path("data") / "backups" / f"{now}-nodes"
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = profile.serial_port if profile.type == "serial" else f"{profile.host}:{profile.port}"
    raw_map = {"info_no_node": None, "nodes": json.dumps(read.get("nodes_raw") or [], ensure_ascii=False), "config": None, "channels": None, "module_config": None, "export_config": None}
    normalized = normalize_snapshot_payload(connection_type=profile.type, connection_target=target, source=source, raw=raw_map)
    normalized["status"] = "partial" if normalized.get("nodes") else "failed"
    normalized["snapshot_time"] = now
    normalized["node_count"] = len(normalized.get("nodes", []))
    (backup_dir / "metadata.json").write_text(json.dumps({"timestamp": now}, indent=2), encoding="utf-8")
    (backup_dir / "normalized.json").write_text(json.dumps(normalized, indent=2), encoding="utf-8")
    return {"raw_path": str(backup_dir / "metadata.json"), "normalized_path": str(backup_dir / "normalized.json"), "backup_dir": str(backup_dir)}


def read_local_node(profile: ConnectionProfile) -> dict[str, Any]:
    step = run_meshtastic_cli("local_info", ["--info", "--no-node"], profile)
    if not step.get("ok"):
        raise RuntimeError(step.get("error") or "local_info_failed")
    parsed = {}
    if step.get("stdout", "").strip():
        try:
            parsed = json.loads(step["stdout"])
        except Exception:
            parsed = {}
    source = _normalize_source(_safe_json(parsed))
    return {"ok": True, "source_node": source, "local_device_info": parsed, "command_log": {"command": " ".join(step.get("command") or []), "duration_ms": step.get("duration_ms"), "exit_code": step.get("exit_code"), "step_error": step.get("error")}}


def read_discovered_nodes(profile: ConnectionProfile) -> dict[str, Any]:
    nodes_step = run_meshtastic_cli("nodes", ["--nodes"], profile)
    if not nodes_step.get("ok"):
        raise RuntimeError(nodes_step.get("error") or "nodes_failed")
    payload = []
    if nodes_step.get("stdout", "").strip():
        try:
            parsed = json.loads(nodes_step["stdout"])
            payload = parsed if isinstance(parsed, list) else parsed.get("nodes", []) if isinstance(parsed, dict) else []
        except Exception:
            payload = []
    nodes = _normalize_nodes([n for n in payload if isinstance(n, dict)])
    return {"ok": True, "source_node": {}, "node_count": len(nodes), "nodes": nodes, "nodes_raw": payload}
