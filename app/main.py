from __future__ import annotations

import json
import socket
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.db import create_snapshot_record, delete_snapshot, delete_snapshots_failed_or_empty, delete_snapshots_unverified, ensure_snapshot_columns, get_snapshot, init_db, insert_snapshot_nodes, list_nodes, list_snapshots, reject_snapshot, verify_snapshot
from app.services.serial_service import list_serial_ports
from app.services.meshtastic_service import ConnectionProfile, build_api_error, read_discovered_nodes, read_local_node, run_local_backup, test_connection

app = FastAPI(title="PiAns Mesh Node Manager")
app.mount("/static", StaticFiles(directory=Path(__file__).resolve().parent / "static"), name="static")

class ConnectionTestRequest(BaseModel):
    type: str = Field(pattern="^(serial|tcp)$")
    port: str | None = None
    host: str | None = None
    tcp_port: int | None = None

class VerifyPayload(BaseModel):
    note: str | None = None

class CleanupPayload(BaseModel):
    mode: str = Field(default="preview", pattern="^(preview|single|unverified|failed_or_empty|older_than_days)$")
    snapshot_id: int | None = None
    older_than_days: int | None = None
    confirm: bool = False


def _to_profile(payload: ConnectionTestRequest) -> ConnectionProfile:
    return ConnectionProfile(type=payload.type, serial_port=payload.port if payload.type == "serial" else None, host=payload.host if payload.type == "tcp" else None, port=payload.tcp_port if payload.type == "tcp" else None)

@app.on_event("startup")
def on_startup() -> None:
    init_db(); ensure_snapshot_columns()

@app.get("/")
def index() -> HTMLResponse:
    hostname = socket.gethostname(); ports = list_serial_ports()
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
      <article class="card span-12">
        <h2>Connection & status</h2>
        <div class="stat"><span>Detected serial ports</span><strong>{len(ports)}</strong></div>
        <label>Connection type</label><select id="conn-type"><option value="serial">serial</option><option value="tcp">tcp</option></select>
        <div id="serial-group"><label>Serial port</label><select id="serial-port"><option value="">Select serial port</option>{port_options}</select></div>
        <div id="tcp-host-group" class="hidden"><label>TCP host</label><input id="tcp-host" placeholder="192.168.1.50"></div>
        <div id="tcp-port-group" class="hidden"><label>TCP port</label><input id="tcp-port" value="4403"></div>
        <div class="actions"><button id="test-connection">Test connection</button><button id="read-local">Read local node</button><button id="read-discovered">Read discovered nodes</button><button id="run-backup" class="primary">Run full local backup</button></div>
        <div id="op-state" class="muted">Idle</div>
        <div id="connection-status" class="status-box">Ready.</div>
        <div id="backup-status" class="status-box">No backup running.</div>
      </article>
      <article class="card span-6"><h2>Local node summary</h2><div id="local-node-summary" class="muted"></div></article>
      <article class="card span-6"><h2>Snapshots / verification</h2><div class="actions"><button id="cleanup-unverified">Delete unverified</button><button id="cleanup-empty">Delete failed/empty</button></div><div id="snap-state"></div></article>

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



@app.get('/snapshots/{snapshot_id}')
def snapshot_review_page(snapshot_id: int) -> HTMLResponse:
    return HTMLResponse(_render_snapshot_review_html(snapshot_id))


def _render_snapshot_review_html(snapshot_id: int) -> str:
    return f"""<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><title>Snapshot #{snapshot_id}</title><link rel='stylesheet' href='/static/styles.css'></head><body><main class='container'><header class='header'><div><h1>Snapshot review #{snapshot_id}</h1><div class='muted'>Human verification required</div></div><a href='/' class='badge'>Back</a></header><section class='card'><div id='review-root'>Loading...</div></section></main><script>window.SNAPSHOT_ID={snapshot_id}</script><script src='/static/app.js'></script></body></html>"""

@app.get('/api/status')
def api_status():
    return {"ok": True, "service": "meshnodemgr", "hostname": socket.gethostname()}


@app.get('/api/connections')
def api_connections():
    ports = list_serial_ports()
    return {"ok": True, "serial_ports": ports, "count": len(ports)}
@app.post('/api/connections/test')
def api_test_connection(payload: ConnectionTestRequest):
    return test_connection(_to_profile(payload))

@app.post('/api/nodes/read-local')
def api_read_local(payload: ConnectionTestRequest):
    try:
        return read_local_node(_to_profile(payload))
    except Exception as exc:
        return build_api_error('Read local node failed', str(exc), 'Verify connection settings and try again.')

@app.post('/api/nodes/read-discovered')
def api_read_discovered(payload: ConnectionTestRequest):
    try:
        profile = _to_profile(payload); result = read_discovered_nodes(profile)
        snap_id = create_snapshot_record({"connection_type": profile.type, "connection_target": profile.serial_port if profile.type=='serial' else f"{profile.host}:{profile.port}", "status": "nodes_read", "raw_path": "", "normalized_path": "", "local_node_id": result['source_node'].get('source_node_id') or str(result['source_node'].get('source_node_num') or ''), "local_node_name": result['source_node'].get('source_node_label'), "node_count": result['node_count'], "source_node_short_name": result['source_node'].get('source_node_short_name'), "source_node_hw_model": result['source_node'].get('source_node_hw_model')})
        insert_snapshot_nodes(snap_id, result['nodes'])
        result['snapshot_id']=snap_id
        return result
    except Exception as exc:
        return build_api_error('Read discovered nodes failed', str(exc), 'Check device connectivity and retry.')

@app.post('/api/backups/local')
def api_backup_local(payload: ConnectionTestRequest):
    try:
        result = run_local_backup(_to_profile(payload)); n=result['normalized']; s=n['source_node']
        snap_id=create_snapshot_record({"connection_type": n['connection_type'], "connection_target": n['connection_target'], "status": n['status'], "raw_path": result['raw_path'], "normalized_path": result['normalized_path'], "local_node_id": s.get('source_node_id') or str(s.get('source_node_num') or ''), "local_node_name": s.get('source_node_label') or s.get('source_node_long_name') or s.get('source_node_short_name'), "node_count": n['node_count'], "source_node_short_name": s.get('source_node_short_name'), "source_node_hw_model": s.get('source_node_hw_model')})
        insert_snapshot_nodes(snap_id, n['nodes'])
        return {"ok": True, "snapshot_id": snap_id, "snapshot": get_snapshot(snap_id), "backup": result}
    except Exception as exc:
        return build_api_error('Backup failed', str(exc), 'Try a connection test first, then retry backup.')

@app.get('/api/snapshots')
def api_snapshots():
    return {"ok": True, "items": list_snapshots()}

@app.get('/api/snapshots/{snapshot_id}')
def api_snapshot_detail(snapshot_id: int):
    snapshot=get_snapshot(snapshot_id)
    if not snapshot: raise HTTPException(status_code=404, detail='snapshot_not_found')
    normalized_path=snapshot.get('normalized_path'); normalized={}
    if normalized_path and Path(normalized_path).exists():
        normalized=json.loads(Path(normalized_path).read_text(encoding='utf-8'))
    return {"ok": True, "snapshot": snapshot, "nodes": list_nodes(snapshot_id=snapshot_id), "normalized": normalized}

@app.post('/api/snapshots/{snapshot_id}/verify')
def api_verify_snapshot(snapshot_id: int, payload: VerifyPayload):
    if not verify_snapshot(snapshot_id): raise HTTPException(status_code=404, detail='snapshot_not_found')
    return {"ok": True, "snapshot": get_snapshot(snapshot_id)}

@app.post('/api/snapshots/{snapshot_id}/reject')
def api_reject_snapshot(snapshot_id: int, payload: VerifyPayload):
    if not reject_snapshot(snapshot_id, payload.note): raise HTTPException(status_code=404, detail='snapshot_not_found')
    return {"ok": True, "snapshot": get_snapshot(snapshot_id)}

def _cleanup_preview():
    backups = Path('data/backups'); backups.mkdir(parents=True, exist_ok=True)
    snaps = list_snapshots()
    unverified = [s for s in snaps if int(s.get('verified') or 0) == 0]
    failed_or_empty = [s for s in snaps if s.get('status') == 'failed' or (int(s.get('node_count') or 0) == 0 and int(s.get('verified') or 0) == 0)]
    return {"counts": {"all": len(snaps), "unverified": len(unverified), "failed_or_empty": len(failed_or_empty)}}

@app.post('/api/snapshots/cleanup')
def cleanup(payload: CleanupPayload):
    if payload.mode == 'preview':
        return {"ok": True, "preview": _cleanup_preview()}
    if not payload.confirm:
        raise HTTPException(status_code=400, detail='confirmation_required')
    deleted_ids: list[int] = []
    if payload.mode == 'single' and payload.snapshot_id:
        if delete_snapshot(payload.snapshot_id):
            deleted_ids = [payload.snapshot_id]
    elif payload.mode == 'unverified':
        deleted_ids = delete_snapshots_unverified()
    elif payload.mode == 'failed_or_empty':
        deleted_ids = delete_snapshots_failed_or_empty()
    elif payload.mode == 'older_than_days' and payload.older_than_days is not None:
        cutoff = datetime.utcnow().timestamp() - (payload.older_than_days * 86400)
        for s in list_snapshots():
            created = datetime.fromisoformat((s.get('created_at') or '').replace(' ', 'T')).timestamp() if s.get('created_at') else 0
            if created and created < cutoff and delete_snapshot(int(s['id'])):
                deleted_ids.append(int(s['id']))
    for snap in deleted_ids:
        for fp in [Path('data/backups') / str(snap)]:
            if fp.exists() and fp.is_dir():
                import shutil; shutil.rmtree(fp, ignore_errors=True)
    return {"ok": True, "deleted_ids": deleted_ids, "preview": _cleanup_preview()}
