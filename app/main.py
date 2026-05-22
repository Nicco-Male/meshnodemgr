from __future__ import annotations

import socket
from datetime import datetime

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse

from app.db import fetch_inventory, init_db
from app.services.meshtastic_cli import run_meshtastic_info
from app.services.serial_service import list_serial_ports

app = FastAPI(title="PiAns Mesh Node Manager")


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/")
def index() -> HTMLResponse:
    hostname = socket.gethostname()
    ports = list_serial_ports()

    ports_html = "".join(f"<li><code>{p}</code></li>" for p in ports)
    if not ports_html:
        ports_html = "<li>Nessuna porta seriale trovata</li>"

    return HTMLResponse(
        f"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>PiAns Mesh Node Manager</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body {{
      font-family: system-ui, sans-serif;
      background: #101418;
      color: #e8f0f2;
      margin: 0;
      padding: 16px;
    }}
    .container {{
      max-width: 680px;
      margin: 0 auto;
    }}
    .card {{
      background: #182026;
      border: 1px solid #2d3a42;
      border-radius: 14px;
      padding: 16px;
      margin-bottom: 12px;
      box-shadow: 0 8px 24px rgba(0,0,0,.25);
    }}
    h1 {{ margin: 0 0 8px; color: #67d391; font-size: 1.4rem; }}
    h2 {{ margin: 0 0 8px; font-size: 1.1rem; }}
    code {{ background: #0b0f12; padding: 2px 6px; border-radius: 6px; }}
    ul {{ padding-left: 18px; margin: 8px 0; }}
    .warn {{ color: #ffc857; }}
  </style>
</head>
<body>
  <main class="container">
    <section class="card">
      <h1>PiAns Mesh Node Manager</h1>
      <p>Hostname: <code>{hostname}</code></p>
      <p>Ora: <code>{datetime.now().isoformat(timespec="seconds")}</code></p>
    </section>

    <section class="card">
      <h2>USB / seriale</h2>
      <ul>{ports_html}</ul>
      <label for="port-select">Porta seriale</label>
      <select id="port-select" style="display:block;width:100%;max-width:340px;margin:8px 0;padding:8px;border-radius:8px;background:#0b0f12;color:#e8f0f2;border:1px solid #2d3a42;">
        <option value="">Seleziona una porta</option>
        {"".join(f'<option value="{p}">{p}</option>' for p in ports)}
      </select>
      <button id="read-info" style="padding:8px 12px;border-radius:8px;border:1px solid #2d3a42;background:#22303a;color:#e8f0f2;">Leggi info nodo locale</button>
      <pre id="node-info" style="white-space:pre-wrap;background:#0b0f12;border:1px solid #2d3a42;border-radius:8px;padding:10px;margin-top:10px;min-height:64px;">Nessuna richiesta inviata.</pre>
      <p class="warn">Nessun nodo collegato è uno stato valido: l'app rimane operativa.</p>
    </section>

    <section class="card">
      <h2>API</h2>
      <ul>
        <li><code>/api/status</code></li>
        <li><code>/api/serial/ports</code></li>
        <li><code>/api/inventory</code></li>
        <li><code>/api/meshtastic/info?port=/dev/ttyACM0</code></li>
      </ul>
    </section>
  </main>
  <script>
    const btn = document.getElementById("read-info");
    const output = document.getElementById("node-info");
    const select = document.getElementById("port-select");

    btn?.addEventListener("click", async () => {{
      const port = select?.value || "";
      if (!port) {{
        output.textContent = "Seleziona prima una porta seriale.";
        return;
      }}

      output.textContent = "Lettura info in corso...";
      try {{
        const response = await fetch(`/api/meshtastic/info?port=${{encodeURIComponent(port)}}`);
        const data = await response.json();
        output.textContent = JSON.stringify(data, null, 2);
      }} catch (err) {{
        output.textContent = `Errore richiesta: ${{String(err)}}`;
      }}
    }});
  </script>
</body>
</html>
"""
    )


@app.get("/api/status")
def status() -> dict[str, str | bool | int]:
    ports = list_serial_ports()
    return {
        "hostname": socket.gethostname(),
        "time": datetime.now().isoformat(timespec="seconds"),
        "port": 8080,
        "serial_device_count": len(ports),
        "meshtastic_connected": len(ports) > 0,
    }


@app.get("/api/serial/ports")
def serial_ports() -> dict[str, list[str] | int]:
    ports = list_serial_ports()
    return {"count": len(ports), "ports": ports}




@app.get("/api/meshtastic/info")
def meshtastic_info(port: str = Query(default="", description="Serial port path")) -> dict[str, object]:
    result = run_meshtastic_info(port=port)
    if not result.ok:
        return {
            "ok": False,
            "port": result.port,
            "error": result.error,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "command": result.command,
            "timeout_seconds": result.timeout_seconds,
        }

    return {
        "ok": True,
        "port": result.port,
        "returncode": result.returncode,
        "command": result.command,
        "timeout_seconds": result.timeout_seconds,
        "info": result.info,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }

@app.get("/api/inventory")
def inventory() -> dict[str, list[dict[str, str | int | None]] | int]:
    rows = fetch_inventory()
    return {"count": len(rows), "items": rows}
