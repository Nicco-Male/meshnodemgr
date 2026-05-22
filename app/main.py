from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import glob
import socket
import subprocess
import os
from datetime import datetime

app = FastAPI(title="PiAns Mesh Node Manager")


def shell(cmd: list[str]) -> str:
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, timeout=5)
        return out.decode(errors="replace").strip()
    except Exception as e:
        return f"ERR: {e}"


def serial_ports():
    ports = []
    ports.extend(glob.glob("/dev/ttyACM*"))
    ports.extend(glob.glob("/dev/ttyUSB*"))
    return sorted(ports)


@app.get("/")
def index():
    hostname = socket.gethostname()
    ports = serial_ports()

    ports_html = "".join(f"<li>{p}</li>" for p in ports) or "<li>Nessuna porta seriale trovata</li>"

    return HTMLResponse(f"""
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
      padding: 24px;
    }}
    .card {{
      background: #182026;
      border: 1px solid #2d3a42;
      border-radius: 18px;
      padding: 20px;
      margin-bottom: 16px;
      box-shadow: 0 10px 30px rgba(0,0,0,.25);
    }}
    h1 {{
      margin-top: 0;
      color: #67d391;
    }}
    code {{
      background: #0b0f12;
      padding: 3px 6px;
      border-radius: 6px;
    }}
    .ok {{ color: #67d391; }}
    .warn {{ color: #ffc857; }}
  </style>
</head>
<body>
  <div class="card">
    <h1>PiAns Mesh Node Manager</h1>
    <p>Controller portatile Meshtastic.</p>
    <p>Hostname: <code>{hostname}</code></p>
    <p>Ora: <code>{datetime.now().isoformat(timespec="seconds")}</code></p>
  </div>

  <div class="card">
    <h2>USB / seriale</h2>
    <ul>{ports_html}</ul>
    <p class="warn">Il nodo Meshtastic non è ancora collegato: normale per ora.</p>
  </div>

  <div class="card">
    <h2>Prossimi moduli</h2>
    <ul>
      <li>Inventory nodi</li>
      <li>Backup configurazioni</li>
      <li>Profili YAML</li>
      <li>Playbook tipo Ansible</li>
      <li>Remote admin</li>
    </ul>
  </div>
</body>
</html>
""")


@app.get("/api/status")
def status():
    return {
        "hostname": socket.gethostname(),
        "serial_ports": serial_ports(),
        "meshtastic_help": shell(["/home/nicco/meshnodemgr/.venv/bin/meshtastic", "--help"])[:500],
        "time": datetime.now().isoformat(timespec="seconds"),
    }
