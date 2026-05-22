# PiAns Mesh Node Manager

Portable Meshtastic node manager designed to run first on Raspberry Pi Zero W / Raspberry Pi OS Lite.

Goal: provide an Ansible-like configuration manager for Meshtastic nodes.

## Current status

- FastAPI web UI running on port 8080.
- App starts even with no connected `/dev/ttyACM*` or `/dev/ttyUSB*` device.
- Serial detection isolated in `app/services/serial_service.py`.
- Lightweight SQLite initialization in `app/db.py` with `inventory` table creation.
- Runtime database stored under `data/` (git-ignored).

## API endpoints

- `GET /api/status`
- `GET /api/serial/ports`
- `GET /api/inventory`

## Run manually

    cd /home/nicco/meshnodemgr
    source .venv/bin/activate
    uvicorn app.main:app --host 0.0.0.0 --port 8080

## Systemd service checks

    sudo systemctl status meshnodemgr
    sudo journalctl -u meshnodemgr -f

## Architecture notes

- Keep hardware access in service modules (`app/services/`).
- Keep startup resilient when no Meshtastic USB hardware is connected.
- Keep runtime files in `data/` and `logs/` only.
- Keep UI lightweight and phone-friendly.
