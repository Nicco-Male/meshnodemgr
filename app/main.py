from __future__ import annotations

import socket
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.db import (
    create_snapshot_record,
    create_remote_read_record,
    get_snapshot,
    init_db,
    insert_snapshot_nodes,
    list_connections,
    list_managed_nodes,
    list_nodes,
    list_remote_reads,
    list_snapshots,
    mark_node_as_managed,
    unmanage_node,
    update_managed_node_remote_state,
    verify_snapshot,
    verify_remote_read,
)
from app.services.discovery_service import discover_playbooks, discover_profiles
from app.services.meshtastic_service import ConnectionProfile, read_discovered_nodes, read_local_node, run_local_backup, run_remote_read_only, test_connection
from app.services.serial_service import list_serial_ports

app = FastAPI(title="PiAns Mesh Node Manager")
app.mount("/static", StaticFiles(directory=Path(__file__).resolve().parent / "static"), name="static")


class ConnectionTestRequest(BaseModel):
    type: str = Field(pattern="^(serial|tcp)$")
    port: str | None = None
    host: str | None = None
    tcp_port: int | None = None


def _to_profile(payload: ConnectionTestRequest) -> ConnectionProfile:
    return ConnectionProfile(type=payload.type, serial_port=payload.port if payload.type == "serial" else None, host=payload.host if payload.type == "tcp" else None, port=payload.tcp_port if payload.type == "tcp" else None)


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/")
def index() -> HTMLResponse:
    hostname = socket.gethostname()
    ports = list_serial_ports()
    base_dir = Path(__file__).resolve().parents[1]
    discover_profiles(base_dir=base_dir)
    discover_playbooks(base_dir=base_dir)
    return HTMLResponse(_render_index_html(hostname=hostname, ports=ports, now_iso=datetime.now().isoformat(timespec="seconds")))



def _render_index_html(hostname: str, ports: list[str], now_iso: str) -> str:
    port_options = "".join(f"<option value='{p}'>{p}</option>" for p in ports)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PiAns Mesh Node Manager</title>
  <link rel="stylesheet" href="/static/styles.css">
</head>
<body>
  <main class="container">
    <header class="header">
      <div><h1>PiAns Mesh Node Manager</h1><div class="muted">Meshtastic dashboard</div></div>
      <div class="muted">{hostname} · {now_iso}</div>
    </header>

    <section class="grid">
      <article class="card span-4"><h2>Connection status</h2><div class="stat"><span>Detected serial ports</span><strong>{len(ports)}</strong></div><div id="connection-status" class="status-box">Ready.</div></article>
      <article class="card span-4"><h2>Local node backup</h2><div class="stat"><span>Discovered nodes</span><strong id="count-nodes">0</strong></div><div id="backup-status" class="status-box">No backup running.</div><div id="local-node-summary" class="muted"></div></article>
      <article class="card span-4"><h2>Snapshots / verification</h2><div id="snap-state"></div></article>

      <article class="card span-6">
        <h2>Connection panel</h2>
        <label>Connection type</label><select id="conn-type"><option value="serial">serial</option><option value="tcp">tcp</option></select>
        <div id="serial-group"><label>Serial port</label><select id="serial-port"><option value="">Select serial port</option>{port_options}</select></div>
        <div id="tcp-host-group" class="hidden"><label>TCP host</label><input id="tcp-host" placeholder="192.168.1.50"></div>
        <div id="tcp-port-group" class="hidden"><label>TCP port</label><input id="tcp-port" value="4403"></div>
        <div class="actions"><button id="test-connection">Test connection</button><button id="read-local">Read local node</button><button id="read-discovered">Read discovered nodes</button><button id="run-backup" class="primary">Run full local backup</button></div>
      </article>

      <article class="card span-6">
        <h2>Discovered nodes</h2>
        <label>Search</label><input id="node-search" placeholder="Search by id, name, model">
        <div class="list" id="node-list"></div>
      </article>

      <article class="card span-12"><h2>Management state</h2><p class="muted">Use Manage/Unmanage on discovered nodes to update state.</p></article>
    </section>
  </main>
  <script src="/static/app.js"></script>
</body>
</html>"""


@app.get("/api/connections")
def connections() -> dict[str, object]:
    items = list_connections()
    return {"count": len(items), "items": items}


@app.post("/api/connections/test")
def api_test_connection(payload: ConnectionTestRequest) -> dict[str, object]:
    return test_connection(_to_profile(payload))



@app.post("/api/nodes/read-local")
def api_read_local(payload: ConnectionTestRequest) -> dict[str, object]:
    return {"ok": True, "result": read_local_node(_to_profile(payload))}


@app.post("/api/nodes/read-discovered")
def api_read_discovered(payload: ConnectionTestRequest) -> dict[str, object]:
    profile = _to_profile(payload)
    result = read_discovered_nodes(profile)
    snapshot_id = create_snapshot_record({"connection_type": profile.type, "connection_target": profile.serial_port if profile.type == "serial" else f"{profile.host}:{profile.port}", "status": "nodes_read", "raw_path": "", "normalized_path": "", "local_node_id": None, "local_node_name": None, "node_count": len(result["nodes"])})
    insert_snapshot_nodes(snapshot_id=snapshot_id, nodes=result["nodes"])
    return {"ok": True, "snapshot_id": snapshot_id, "count": len(result["nodes"])}


@app.post("/api/backups/local")
def api_backup_local(payload: ConnectionTestRequest) -> dict[str, object]:
    result = run_local_backup(_to_profile(payload))
    normalized = result["normalized"]
    snapshot_id = create_snapshot_record(
        {
            "connection_type": normalized["connection_type"],
            "connection_target": normalized["connection_target"],
            "status": normalized["status"],
            "raw_path": result["raw_path"],
            "normalized_path": result["normalized_path"],
            "local_node_id": normalized["local_node"]["node_id"],
            "local_node_name": normalized["local_node"]["long_name"],
            "node_count": normalized["node_count"],
        }
    )
    insert_snapshot_nodes(snapshot_id=snapshot_id, nodes=normalized["nodes"])
    return {"ok": True, "snapshot_id": snapshot_id, "snapshot": get_snapshot(snapshot_id), "backup": result}


@app.get("/api/nodes")
def api_nodes(snapshot_id: int | None = Query(default=None)) -> dict[str, object]:
    items = list_nodes(snapshot_id=snapshot_id)
    return {"count": len(items), "items": items}


@app.post("/api/nodes/{node_id}/manage")
def api_manage_node(node_id: str) -> dict[str, object]:
    if not mark_node_as_managed(node_id=node_id):
        raise HTTPException(status_code=404, detail="node_not_found")
    return {"ok": True, "node": node_id, "management_state": "pending_management"}


@app.post("/api/nodes/{node_id}/unmanage")
def api_unmanage_node(node_id: str) -> dict[str, object]:
    if not unmanage_node(node_id=node_id):
        raise HTTPException(status_code=404, detail="managed_node_not_found")
    return {"ok": True, "node": node_id, "management_state": "discovered"}


@app.get("/api/managed-nodes")
def api_managed_nodes() -> dict[str, object]:
    items = list_managed_nodes()
    return {"count": len(items), "items": items}


class RemoteReadRequest(BaseModel):
    connection: ConnectionTestRequest
    timeout_seconds: int = 8
    retries: int = 2


@app.post("/api/nodes/{node_id}/remote-read")
def api_remote_read(node_id: str, payload: RemoteReadRequest) -> dict[str, object]:
    result = run_remote_read_only(
        node_id=node_id,
        profile=ConnectionProfile(**payload.connection.model_dump()),
        timeout_seconds=max(1, payload.timeout_seconds),
        retries=max(1, payload.retries),
    )
    normalized = result["normalized"]
    remote_read_id = create_remote_read_record(
        {
            "node_id": node_id,
            "gateway_connection_type": normalized["gateway_connection_type"],
            "gateway_connection_target": normalized["gateway_connection_target"],
            "status": normalized["status"],
            "attempts": result["attempts"],
            "timeout_seconds": max(1, payload.timeout_seconds),
            "error": normalized["errors"][0] if normalized["errors"] else None,
            "raw_path": result["raw_path"],
            "normalized_path": result["normalized_path"],
        }
    )
    update_managed_node_remote_state(
        node_id=node_id,
        ok=normalized["status"] == "ok",
        error=normalized["errors"][0] if normalized["errors"] else None,
    )
    return {"ok": normalized["status"] == "ok", "remote_read_id": remote_read_id, "result": result}


@app.get("/api/remote-reads")
def api_remote_reads(node_id: str | None = Query(default=None)) -> dict[str, object]:
    items = list_remote_reads(node_id=node_id)
    return {"count": len(items), "items": items}


@app.post("/api/remote-reads/{remote_read_id}/verify")
def api_verify_remote_read(remote_read_id: int) -> dict[str, object]:
    if not verify_remote_read(remote_read_id):
        raise HTTPException(status_code=404, detail="remote_read_not_found")
    items = list_remote_reads()
    selected = next((i for i in items if i["id"] == remote_read_id), None)
    return {"ok": True, "remote_read": selected}


@app.get("/api/snapshots")
def api_snapshots() -> dict[str, object]:
    items = list_snapshots()
    return {"count": len(items), "items": items}


@app.get("/api/snapshots/{snapshot_id}")
def api_snapshot_detail(snapshot_id: int) -> dict[str, object]:
    snapshot = get_snapshot(snapshot_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail="snapshot_not_found")
    return {"snapshot": snapshot, "nodes": list_nodes(snapshot_id=snapshot_id)}


@app.post("/api/snapshots/{snapshot_id}/verify")
def api_verify_snapshot(snapshot_id: int) -> dict[str, object]:
    if not verify_snapshot(snapshot_id):
        raise HTTPException(status_code=404, detail="snapshot_not_found")
    return {"ok": True, "snapshot": get_snapshot(snapshot_id)}
