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


def _preview_text(text: str, debug: bool) -> str:
    safe = _mask_sensitive(text)
    if debug and len(safe) <= RAW_MAX_DEBUG:
        return safe
    if debug and len(safe) > RAW_MAX_DEBUG:
        return f"{safe[:1500]}\n... [truncated total={len(safe)}] ...\n{safe[-1500:]}"
    if len(safe) <= 400:
        return safe
    return f"{safe[:200]} ... {safe[-200:]}"


def run_meshtastic_cli(step_name: str, args: list[str], connection: ConnectionProfile) -> dict[str, Any]:
    cmd = ["meshtastic"]
    if connection.type == "serial":
        cmd += ["--port", connection.serial_port or ""]
        target = f"serial:{connection.serial_port or ''}"
    else:
        cmd += ["--host", connection.host or "", "--port", str(connection.port or "")]
        target = f"tcp:{connection.host or ''}:{connection.port or ''}"
    cmd += args
    debug_mode = os.getenv("MESHNODEMGR_DEBUG") == "1"
    cmd_str = _mask_sensitive(" ".join(cmd))
    LOGGER.info("STEP %s | start | connection_type=%s | target=%s | command=%s | started_at=%s", step_name, connection.type, target, cmd_str, datetime.utcnow().isoformat() + "Z")
    t0 = time.perf_counter()
    started_at = datetime.utcnow().isoformat() + "Z"
    try:
        cp = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=25)
        duration_ms = int((time.perf_counter() - t0) * 1000)
        stdout = cp.stdout or ""
        stderr = cp.stderr or ""
        ended_at = datetime.utcnow().isoformat() + "Z"
        LOGGER.info("STEP %s | done | started_at=%s | ended_at=%s | duration_ms=%s | return_code=%s", step_name, started_at, ended_at, duration_ms, cp.returncode)
        LOGGER.debug("STEP %s | stdout_preview(first_%s)=%s", step_name, RAW_MAX_DEBUG, _preview_text(stdout[:RAW_MAX_DEBUG], True))
        LOGGER.debug("STEP %s | stderr_preview(first_%s)=%s", step_name, RAW_MAX_DEBUG, _preview_text(stderr[:RAW_MAX_DEBUG], True))
        return {"ok": cp.returncode == 0, "step": step_name, "command": cmd, "exit_code": cp.returncode, "duration_ms": duration_ms, "stdout": stdout, "stderr": stderr, "error": None if cp.returncode == 0 else "command_failed"}
    except Exception as exc:
        duration_ms = int((time.perf_counter() - t0) * 1000)
        err = _mask_sensitive(str(exc))
        LOGGER.error("STEP %s | failed | started_at=%s | duration_ms=%s | error=%s", step_name, started_at, duration_ms, err)
        return {"ok": False, "step": step_name, "command": cmd, "exit_code": None, "duration_ms": duration_ms, "stdout": "", "stderr": err, "error": err}


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
    profile_view = {"type": profile.type, "serial_port": profile.serial_port if profile.type == "serial" else None, "host": profile.host if profile.type == "tcp" else None, "port": profile.port if profile.type == "tcp" else None}
    LOGGER.info("BACKUP local | start | profile=%s", _mask_sensitive(json.dumps(profile_view, ensure_ascii=False)))
    steps = {
        "local_info_raw": run_meshtastic_cli("full_backup_local_info", ["--info", "--no-node"], profile),
        "nodes_raw": run_meshtastic_cli("full_backup_nodes", ["--nodes"], profile),
        "config_raw": {"ok": False, "command": ["not-executed"], "exit_code": None, "duration_ms": 0, "stdout": "", "stderr": "", "error": "not_implemented_yet"},
        "channels_raw": {"ok": False, "command": ["not-executed"], "exit_code": None, "duration_ms": 0, "stdout": "", "stderr": "", "error": "not_implemented_yet"},
        "module_config_raw": {"ok": False, "command": ["not-executed"], "exit_code": None, "duration_ms": 0, "stdout": "", "stderr": "", "error": "not_implemented_yet"},
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
    LOGGER.info("STEP parser_result | local_info=%s | nodes=%s", normalized.get("section_status", {}).get("local_info"), normalized.get("section_status", {}).get("nodes"))
    LOGGER.info("STEP parser_counts | local_info_keys=%s | node_count=%s | parse_errors=%s", len((normalized.get("local_info") or {}).keys()), len(normalized.get("nodes") or []), len(normalized.get("parse_errors") or []))
    statuses = normalized.get("section_status", {})
    ok_count = sum(1 for v in statuses.values() if v == "OK")
    normalized["status"] = "ok" if ok_count == len(statuses) else "partial" if ok_count > 0 else "failed"
    normalized["snapshot_time"] = now
    normalized["node_count"] = len(normalized.get("nodes", []))
    logs = _build_logs(steps, normalized)
    normalized["command_logs"] = logs
    for item in logs:
        LOGGER.info("STEP section=%s | status=%s | reason=%s | command=%s | exit_code=%s", item["section"], item.get("section_saved"), item.get("section_reason") or item.get("step_error") or "none", item.get("command"), item.get("exit_code"))
    metadata = {"timestamp": now, "connection": _safe_json(profile.__dict__), "command_logs": logs}
    command_summary = [
        {"step": "full_backup_local_info", "command": _mask_sensitive(" ".join(steps["local_info_raw"].get("command") or [])), "return_code": steps["local_info_raw"].get("exit_code"), "duration": steps["local_info_raw"].get("duration_ms"), "stdout_len": len(steps["local_info_raw"].get("stdout") or ""), "stderr_len": len(steps["local_info_raw"].get("stderr") or ""), "parser_status": normalized.get("section_status", {}).get("local_info")},
        {"step": "full_backup_nodes", "command": _mask_sensitive(" ".join(steps["nodes_raw"].get("command") or [])), "return_code": steps["nodes_raw"].get("exit_code"), "duration": steps["nodes_raw"].get("duration_ms"), "stdout_len": len(steps["nodes_raw"].get("stdout") or ""), "stderr_len": len(steps["nodes_raw"].get("stderr") or ""), "parser_status": normalized.get("section_status", {}).get("nodes")},
    ]
    for filename, payload in {
        "local_info_stdout.txt": steps["local_info_raw"].get("stdout") or "",
        "local_info_stderr.txt": steps["local_info_raw"].get("stderr") or "",
        "nodes_stdout.txt": steps["nodes_raw"].get("stdout") or "",
        "nodes_stderr.txt": steps["nodes_raw"].get("stderr") or "",
        "command_summary.json": command_summary,
        "metadata.json": metadata,
        "normalized.json": normalized,
    }.items():
        (backup_dir / filename).write_text(payload if isinstance(payload, str) else json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    useful = any(statuses.get(k) == "OK" for k in ("local_info", "nodes"))
    if not useful:
        LOGGER.warning("STEP snapshot_save | skipped | reason=no_useful_data | backup_dir=%s | details=%s", backup_dir, json.dumps(logs, ensure_ascii=False)[:RAW_MAX_DEBUG])
        raise RuntimeError("No useful data collected. Step errors: " + "; ".join([f"{l['section']}:{l.get('section_reason') or l.get('step_error') or l.get('parser_error') or 'empty'}" for l in logs]))
    LOGGER.info("BACKUP local | end | backup_dir=%s | status=%s | node_count=%s", backup_dir, normalized["status"], normalized["node_count"])
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
    step = run_meshtastic_cli("local_info", ["--info", "--no-node"], profile)
    parsed = {}
    perr = None
    if step.get("ok") and step.get("stdout", "").strip():
        try: parsed = json.loads(step["stdout"])
        except Exception as exc: perr = str(exc)
    source = _normalize_source(_safe_json(parsed))
    LOGGER.info("STEP parser_result | local_info_parser=%s", "ok" if not perr else f"error:{perr}")
    return {"ok": True, "source_node": source, "command_log": {"command": " ".join(step.get("command") or []), "duration_ms": step.get("duration_ms"), "exit_code": step.get("exit_code"), "parser_error": perr, "step_error": step.get("error")}}


def read_discovered_nodes(profile: ConnectionProfile) -> dict[str, Any]:
    info_step = run_meshtastic_cli("local_info", ["--info", "--no-node"], profile)
    nodes_step = run_meshtastic_cli("nodes", ["--nodes"], profile)
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
    LOGGER.info("STEP parser_result | nodes_parser=%s | node_count=%s", "ok" if payload else "empty_or_parse_error", len(nodes))
    return {"ok": True, "source_node": source, "node_count": len(nodes), "nodes": nodes, "nodes_raw": payload}
