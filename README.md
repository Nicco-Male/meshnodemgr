# PiAns Mesh Node Manager

Portable Meshtastic node manager designed to run first on Raspberry Pi Zero W / Raspberry Pi OS Lite.

## New: Backup and Inventory Workflow (v1)

This release adds the first real workflow for local backup and inventory collection, while keeping startup resilient with no connected device.

### What is included

- Connection profile support:
  - Serial via `/dev/ttyACM*` and `/dev/ttyUSB*`
  - TCP/Wi-Fi via host/IP + port
- Meshtastic service layer under `app/services/meshtastic_service.py`
- Local backup flow:
  - reads connection availability
  - prepares local node/config/node-db extraction structure
  - saves raw JSON + normalized JSON under `data/backups/`
  - writes snapshot metadata and discovered node rows to SQLite
- Human verification workflow:
  - snapshots are unverified by default
  - `POST /api/snapshots/{snapshot_id}/verify` marks a snapshot verified
- Mobile-friendly UI section for:
  - choosing connection type
  - testing connection
  - running local backup
  - browsing and filtering discovered nodes

> Note: this version intentionally does **not** perform remote write/apply and does **not** automatically modify any Meshtastic node.

## UI dashboard (lightweight, mobile-first)

- Modern dark dashboard theme with Meshtastic-inspired green accents.
- Mobile-first responsive card/grid layout for phone and desktop.
- Static assets served locally from `app/static/styles.css` and `app/static/app.js`.
- No React/Node/Tailwind/Bootstrap/CDN; no frontend build step required.

## API endpoints

- `GET /api/connections`
- `POST /api/connections/test`
- `POST /api/backups/local`
- `GET /api/nodes`
- `GET /api/snapshots`
- `GET /api/snapshots/{snapshot_id}`
- `POST /api/snapshots/{snapshot_id}/verify`

## SQLite tables

- `connections`
- `nodes`
- `snapshots`
- `drift_checks`

## Run manually

    cd /home/nicco/meshnodemgr
    source .venv/bin/activate
    uvicorn app.main:app --host 0.0.0.0 --port 8080

## Architecture notes

- Hardware access stays isolated in `app/services/`.
- App startup does not require Meshtastic hardware.
- Runtime artifacts remain under `data/` and `logs/`.
- UI remains lightweight (no Docker/React/Node/Tailwind).
