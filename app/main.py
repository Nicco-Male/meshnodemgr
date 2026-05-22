from __future__ import annotations

import json
import socket
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.db import create_snapshot_record, ensure_snapshot_columns, get_snapshot, init_db, insert_snapshot_nodes, list_nodes, list_snapshots, reject_snapshot, verify_snapshot
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
    delete_failed: bool = True
    delete_empty_partial: bool = True
    delete_old_format: bool = False
    delete_orphans: bool = True
    older_than_days: int | None = None
    dry_run: bool = True


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


@app.get('/api/status')
def api_status():
    return {"ok": True, "service": "meshnodemgr", "hostname": socket.gethostname()}

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
    old = list(backups.glob('snapshot_*.json'))
    snaps = list_snapshots()
    failed = [s for s in snaps if s.get('status')=='failed']
    empty_partial = [s for s in snaps if s.get('status')=='partial' and int(s.get('node_count') or 0)==0]
    referenced = {Path(s['normalized_path']) for s in snaps if s.get('normalized_path')} | {Path(s['raw_path']) for s in snaps if s.get('raw_path')}
    orphan_files = [p for p in backups.rglob('*.json') if p not in referenced and not p.name.endswith('meshnodemgr.db')]
    orphan_db = [s for s in snaps if s.get('normalized_path') and not Path(s['normalized_path']).exists()]
    size = sum(p.stat().st_size for p in old + orphan_files if p.exists())
    return {"old_format_snapshots": [str(p) for p in old], "failed_snapshots": failed, "empty_partial_snapshots": empty_partial, "orphan_files": [str(p) for p in orphan_files], "orphan_db_records": orphan_db, "total_reclaimable_size": size, "counts": {"old_format": len(old), "failed": len(failed), "empty_partial": len(empty_partial), "orphan_files": len(orphan_files), "orphan_db": len(orphan_db)}}

@app.get('/api/maintenance/cleanup-preview')
def cleanup_preview():
    return {"ok": True, "preview": _cleanup_preview()}

@app.post('/api/maintenance/cleanup')
def cleanup(payload: CleanupPayload):
    preview = _cleanup_preview()
    deleted = []
    if payload.dry_run:
        return {"ok": True, "dry_run": True, "preview": preview, "deleted": []}
    if payload.delete_old_format:
        for fp in preview['old_format_snapshots']:
            p=Path(fp); p.unlink(missing_ok=True); deleted.append(fp)
    if payload.delete_orphans:
        for fp in preview['orphan_files']:
            p=Path(fp); p.unlink(missing_ok=True); deleted.append(fp)
    return {"ok": True, "dry_run": False, "deleted": deleted, "preview": preview}
