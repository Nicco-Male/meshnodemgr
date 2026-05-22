from __future__ import annotations

import socket
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
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
from app.services.meshtastic_service import ConnectionProfile, run_local_backup, run_remote_read_only, test_connection
from app.services.serial_service import list_serial_ports

app = FastAPI(title="PiAns Mesh Node Manager")


class ConnectionTestRequest(BaseModel):
    type: str = Field(pattern="^(serial|tcp)$")
    serial_port: str | None = None
    host: str | None = None
    port: int | None = None


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
    template = """<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>
<title>PiAns Mesh Node Manager</title><style>
body{{font-family:system-ui,sans-serif;background:#101418;color:#e8f0f2;margin:0;padding:16px}} .container{{max-width:760px;margin:0 auto}}
.card{{background:#182026;border:1px solid #2d3a42;border-radius:14px;padding:14px;margin-bottom:12px}}
input,select,button{{width:100%;max-width:420px;margin:6px 0;padding:9px;border-radius:8px;border:1px solid #2d3a42;background:#0b0f12;color:#e8f0f2}}
button{{background:#22303a}} pre{{white-space:pre-wrap;background:#0b0f12;padding:10px;border-radius:8px;border:1px solid #2d3a42}}
.list{{max-height:260px;overflow:auto}} .node-row{{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:6px 0;border-bottom:1px solid #2d3a42}}
.muted{{opacity:0.7;font-size:0.9em}}
</style></head><body><main class='container'>
<section class='card'><h1>PiAns Mesh Node Manager</h1><p>__HOST__ · __NOW__</p></section>
<section class='card'><h2>Backup & Inventory</h2>
<label>Tipo connessione</label><select id='conn-type'><option value='serial'>Seriale</option><option value='tcp'>TCP/Wi-Fi</option></select>
<label>Porta seriale</label><select id='serial-port'><option value=''>Seleziona</option>__PORT_OPTIONS__</select>
<label>Host/IP TCP</label><input id='tcp-host' placeholder='192.168.1.50'>
<label>Porta TCP</label><input id='tcp-port' placeholder='4403' value='4403'>
<button id='test-connection'>Test connessione</button><button id='run-backup'>Run local backup</button>
<pre id='workflow-output'>Pronto.</pre></section>
<section class='card'><h2>Nodi scoperti</h2><input id='node-search' placeholder='Cerca per id/nome/modello'>
<div class='list'><ul id='node-list'></ul></div></section>
<section class='card'><h2>Nodi gestiti</h2><div class='list'><ul id='managed-node-list'></ul></div></section>
<section class='card'><h2>Remote Admin Read (solo lettura)</h2>
<label>Node ID gestito</label><input id='remote-node-id' placeholder='!abcd1234'>
<label>Timeout secondi</label><input id='remote-timeout' type='number' value='8'>
<label>Retry</label><input id='remote-retries' type='number' value='2'>
<button id='remote-read'>Request remote read</button>
<button id='remote-verify'>Human verification</button>
<pre id='remote-output'>Nessuna lettura remota.</pre>
</section>
</main><script>
function body(){const t=document.getElementById('conn-type').value;return {type:t,serial_port:document.getElementById('serial-port').value||null,host:document.getElementById('tcp-host').value||null,port:Number(document.getElementById('tcp-port').value)||null};}
async function loadNodes(){const res=await fetch('/api/nodes');const d=await res.json();window.__nodes=d.items||[];await loadManagedNodes();renderNodes();}
async function loadManagedNodes(){const res=await fetch('/api/managed-nodes');const d=await res.json();window.__managed=(d.items||[]).reduce((acc,n)=>{acc[n.node_id]=n;return acc;},{});renderManagedNodes();}
function renderNodes(){const q=(document.getElementById('node-search').value||'').toLowerCase();const ul=document.getElementById('node-list');ul.innerHTML='';(window.__nodes||[]).filter(n=>JSON.stringify(n).toLowerCase().includes(q)).forEach(n=>{const li=document.createElement('li');const managed=window.__managed?.[n.node_id];const state=managed?managed.management_state:'discovered';li.innerHTML=`<div class='node-row'><div><strong>${n.long_name||n.short_name||'unknown'}</strong><div class='muted'>${n.node_id||'n/a'} · stato: ${state}</div></div><button data-node='${n.node_id}'>${managed?'Unmanage':'Manage'}</button></div>`;ul.appendChild(li);});if(!ul.innerHTML){ul.innerHTML='<li>Nessun nodo</li>'}}
function renderManagedNodes(){const ul=document.getElementById('managed-node-list');ul.innerHTML='';const items=Object.values(window.__managed||{});items.forEach(n=>{const li=document.createElement('li');li.textContent=`${n.long_name||n.short_name||'unknown'} (${n.node_id}) · ${n.management_state}`;ul.appendChild(li);});if(!ul.innerHTML){ul.innerHTML='<li>Nessun nodo gestito</li>';}}
document.getElementById('node-list').addEventListener('click',async(e)=>{if(e.target.tagName!=='BUTTON'){return;}const nodeId=e.target.getAttribute('data-node');if(!nodeId){return;}const managed=window.__managed?.[nodeId];const endpoint=managed?`/api/nodes/${nodeId}/unmanage`:`/api/nodes/${nodeId}/manage`;await fetch(endpoint,{method:'POST'});await loadManagedNodes();renderNodes();});
document.getElementById('node-search').addEventListener('input',renderNodes);
document.getElementById('test-connection').addEventListener('click',async()=>{const o=document.getElementById('workflow-output');o.textContent='Testing...';const r=await fetch('/api/connections/test',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body())});o.textContent=JSON.stringify(await r.json(),null,2);});
document.getElementById('run-backup').addEventListener('click',async()=>{const o=document.getElementById('workflow-output');o.textContent='Backup...';const r=await fetch('/api/backups/local',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body())});o.textContent=JSON.stringify(await r.json(),null,2);loadNodes();});
document.getElementById('remote-read').addEventListener('click',async()=>{const o=document.getElementById('remote-output');const nodeId=(document.getElementById('remote-node-id').value||'').trim();if(!nodeId){o.textContent='Inserire node id';return;}o.textContent='Remote read in corso...';const r=await fetch(`/api/nodes/${encodeURIComponent(nodeId)}/remote-read`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({connection:body(),timeout_seconds:Number(document.getElementById('remote-timeout').value)||8,retries:Number(document.getElementById('remote-retries').value)||2})});o.textContent=JSON.stringify(await r.json(),null,2);});
document.getElementById('remote-verify').addEventListener('click',async()=>{const o=document.getElementById('remote-output');const parsed=JSON.parse(o.textContent||'{}');const id=parsed?.remote_read_id;if(!id){o.textContent='Nessun remote_read_id da verificare';return;}const r=await fetch(`/api/remote-reads/${id}/verify`,{method:'POST'});o.textContent=JSON.stringify(await r.json(),null,2);});
loadNodes();</script></body></html>"""
    return template.replace("__HOST__", hostname).replace("__NOW__", now_iso).replace("__PORT_OPTIONS__", port_options)


@app.get("/api/connections")
def connections() -> dict[str, object]:
    items = list_connections()
    return {"count": len(items), "items": items}


@app.post("/api/connections/test")
def api_test_connection(payload: ConnectionTestRequest) -> dict[str, object]:
    return test_connection(ConnectionProfile(**payload.model_dump()))


@app.post("/api/backups/local")
def api_backup_local(payload: ConnectionTestRequest) -> dict[str, object]:
    result = run_local_backup(ConnectionProfile(**payload.model_dump()))
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
