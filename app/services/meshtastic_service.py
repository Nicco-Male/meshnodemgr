from __future__ import annotations

import json
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


def test_connection(profile: ConnectionProfile) -> dict[str, Any]:
    if profile.type == "serial":
        ports = list_serial_ports()
        if not profile.serial_port:
            return build_api_error("Serial port is required", "missing serial port", "Select a serial port from the list.") | {"available_ports": ports}
    target = profile.serial_port if profile.type == "serial" else f"{profile.host}:{profile.port}"
    return {"ok": True, "type": profile.type, "target": target}


def _run_cli_step(profile: ConnectionProfile, args: list[str]) -> dict[str, Any]:
    cmd = ["meshtastic"]
    if profile.type == "serial":
        cmd += ["--port", profile.serial_port or ""]
    else:
        cmd += ["--host", profile.host or "", "--port", str(profile.port or "")]
    cmd += args
    t0 = time.perf_counter()
    try:
        cp = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=25)
        return {"ok": cp.returncode == 0, "command": cmd, "exit_code": cp.returncode, "duration_ms": int((time.perf_counter()-t0)*1000), "stdout": cp.stdout or "", "stderr": cp.stderr or "", "error": None if cp.returncode == 0 else "command_failed"}
    except Exception as exc:
        return {"ok": False, "command": cmd, "exit_code": None, "duration_ms": int((time.perf_counter()-t0)*1000), "stdout": "", "stderr": str(exc), "error": str(exc)}


def _normalize_nodes(raw_nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for node in raw_nodes:
        user = node.get("user", {}) if isinstance(node, dict) else {}
        out.append({"node_id": node.get("id") or user.get("id"), "node_num": node.get("num"), "long_name": user.get("longName"), "short_name": user.get("shortName"), "hw_model": user.get("hwModel"), "role": user.get("role"), "snr": node.get("snr"), "raw": _safe_json(node)})
    return out


def _snippet(text: str, size: int = 160) -> tuple[str, str]:
    t = (text or "").strip()
    return (t[:size], t[-size:]) if len(t) > size else (t, t)


def _build_logs(steps: dict[str, dict[str, Any]], normalized: dict[str, Any]) -> list[dict[str, Any]]:
    map_sec = {"local_info_raw": "local_info", "nodes_raw": "nodes", "config_raw": "config", "channels_raw": "channels", "module_config_raw": "module_config"}
    logs = []
    for key, sec in map_sec.items():
        st = steps[key]
        h, t = _snippet(st.get("stdout") or "")
        eh, et = _snippet(st.get("stderr") or "")
        logs.append({"section": sec, "command": " ".join(st.get("command") or []), "duration_ms": st.get("duration_ms"), "exit_code": st.get("exit_code"), "output_head": h, "output_tail": t, "stderr_head": eh, "stderr_tail": et, "parser_error": next((e for e in normalized.get("parse_errors", []) if sec in e or (sec=="local_info" and "info_no_node" in e)), None), "section_saved": normalized.get("section_status", {}).get(sec), "section_reason": normalized.get("section_reasons", {}).get(sec), "step_error": st.get("error")})
    return logs


def run_local_backup(profile: ConnectionProfile) -> dict[str, Any]:
    now = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    steps = {
        "local_info_raw": _run_cli_step(profile, ["--info", "--no-node"]),
        "nodes_raw": _run_cli_step(profile, ["--nodes"]),
        "config_raw": {"ok": False, "command": [], "exit_code": None, "duration_ms": 0, "stdout": "", "stderr": "", "error": "not_collected_in_current_cli_flow"},
        "channels_raw": {"ok": False, "command": [], "exit_code": None, "duration_ms": 0, "stdout": "", "stderr": "", "error": "not_collected_in_current_cli_flow"},
        "module_config_raw": {"ok": False, "command": [], "exit_code": None, "duration_ms": 0, "stdout": "", "stderr": "", "error": "not_collected_in_current_cli_flow"},
    }
    raw = {
        "local_info_raw": steps["local_info_raw"].get("stdout") if steps["local_info_raw"].get("ok") else None,
        "nodes_raw": steps["nodes_raw"].get("stdout") if steps["nodes_raw"].get("ok") else None,
        "config_raw": None,
        "channels_raw": None,
        "module_config_raw": None,
    }
    local_info = {}
    if raw["local_info_raw"]:
        try: local_info = json.loads(raw["local_info_raw"])
        except Exception: local_info = {}
    source = _normalize_source(_safe_json(local_info))
    folder_name = f"{now}-{_slug(source.get('source_node_short_name') or '')}-{_slug(source.get('source_node_long_name') or '')}".strip("-")
    backup_dir = Path("data") / "backups" / (folder_name or f"{now}-unknown-source")
    backup_dir.mkdir(parents=True, exist_ok=True)
    raw_map = {"info_no_node": raw["local_info_raw"], "nodes": raw["nodes_raw"], "config": raw["config_raw"], "channels": raw["channels_raw"], "module_config": raw["module_config_raw"]}
    target = profile.serial_port if profile.type == "serial" else f"{profile.host}:{profile.port}"
    normalized = normalize_snapshot_payload(connection_type=profile.type, connection_target=target, source=source, raw=raw_map)
    statuses = normalized.get("section_status", {})
    ok_count = sum(1 for v in statuses.values() if v == "OK")
    normalized["status"] = "ok" if ok_count == len(statuses) else "partial" if ok_count > 0 else "failed"
    normalized["snapshot_time"] = now
    normalized["node_count"] = len(normalized.get("nodes", []))
    logs = _build_logs(steps, normalized)
    normalized["command_logs"] = logs
    metadata = {"timestamp": now, "connection": _safe_json(profile.__dict__), "command_logs": logs}
    for filename, payload in {
        "local_info_stdout.json": raw["local_info_raw"],
        "local_info_stderr.txt": steps["local_info_raw"].get("stderr") or "",
        "nodes_stdout.json": raw["nodes_raw"],
        "nodes_stderr.txt": steps["nodes_raw"].get("stderr") or "",
        "metadata.json": metadata,
        "normalized.json": normalized,
    }.items():
        (backup_dir / filename).write_text(payload if isinstance(payload, str) else json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    useful = any(statuses.get(k) == "OK" for k in ("local_info", "nodes"))
    if not useful:
        raise RuntimeError("No useful data collected. Step errors: " + "; ".join([f"{l['section']}:{l.get('section_reason') or l.get('step_error') or l.get('parser_error') or 'empty'}" for l in logs]))
    return {"normalized": normalized, "backup_dir": str(backup_dir), "raw_path": str(backup_dir / "metadata.json"), "normalized_path": str(backup_dir / "normalized.json")}


def persist_discovery_snapshot(profile: ConnectionProfile, read: dict[str, Any]) -> dict[str, str]:
    now = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    source = read.get("source_node") or {}
    folder_name = f"{now}-{_slug(source.get('source_node_short_name') or "")}-{_slug(source.get('source_node_long_name') or "")}".strip("-")
    backup_dir = Path("data") / "backups" / (folder_name or f"{now}-unknown-source")
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = profile.serial_port if profile.type == "serial" else f"{profile.host}:{profile.port}"
    raw_map = {"info_no_node": json.dumps(read.get("source_node") or {}, ensure_ascii=False), "nodes": json.dumps(read.get("nodes_raw") or [], ensure_ascii=False), "config": None, "channels": None, "module_config": None}
    normalized = normalize_snapshot_payload(connection_type=profile.type, connection_target=target, source=source, raw=raw_map)
    normalized["status"] = "partial" if normalized.get("nodes") else "failed"
    normalized["snapshot_time"] = now
    normalized["node_count"] = len(normalized.get("nodes", []))
    (backup_dir / "metadata.json").write_text(json.dumps({"timestamp": now}, indent=2), encoding="utf-8")
    (backup_dir / "normalized.json").write_text(json.dumps(normalized, indent=2), encoding="utf-8")
    return {"raw_path": str(backup_dir / "metadata.json"), "normalized_path": str(backup_dir / "normalized.json"), "backup_dir": str(backup_dir)}


def read_local_node(profile: ConnectionProfile) -> dict[str, Any]:
    step = _run_cli_step(profile, ["--info", "--no-node"])
    parsed = {}
    perr = None
    if step.get("ok") and step.get("stdout", "").strip():
        try: parsed = json.loads(step["stdout"])
        except Exception as exc: perr = str(exc)
    source = _normalize_source(_safe_json(parsed))
    return {"ok": True, "source_node": source, "command_log": {"command": " ".join(step.get("command") or []), "duration_ms": step.get("duration_ms"), "exit_code": step.get("exit_code"), "parser_error": perr, "step_error": step.get("error")}}


def read_discovered_nodes(profile: ConnectionProfile) -> dict[str, Any]:
    info_step = _run_cli_step(profile, ["--info", "--no-node"])
    nodes_step = _run_cli_step(profile, ["--nodes"])
    source = {}
    if info_step.get("ok") and info_step.get("stdout", "").strip():
        try: source = _normalize_source(_safe_json(json.loads(info_step["stdout"])))
        except Exception: source = {}
    payload = []
    if nodes_step.get("ok") and nodes_step.get("stdout", "").strip():
        try:
            parsed = json.loads(nodes_step["stdout"])
            payload = parsed if isinstance(parsed, list) else parsed.get("nodes", []) if isinstance(parsed, dict) else []
        except Exception:
            payload = []
    nodes = _normalize_nodes([n for n in payload if isinstance(n, dict)])
    return {"ok": True, "source_node": source, "node_count": len(nodes), "nodes": nodes, "nodes_raw": payload}
