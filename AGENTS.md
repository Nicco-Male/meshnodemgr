# AGENTS.md

## Project

PiAns Mesh Node Manager is a lightweight web-based Meshtastic node configuration manager.

It targets Raspberry Pi Zero W first, so keep the project lightweight.

## Main constraints

- Primary target: Raspberry Pi OS Lite 32-bit on Raspberry Pi Zero W.
- Avoid Docker for the first version.
- Avoid heavy frontend build systems unless explicitly requested.
- Prefer Python, FastAPI, SQLite, YAML and systemd.
- Keep memory and CPU usage low.
- Do not commit runtime data, backups, logs, secrets or virtual environments.
- Do not assume a Meshtastic device is connected during development.
- The app must still start when no /dev/ttyACM* or /dev/ttyUSB* device exists.

## Current run command

    uvicorn app.main:app --host 0.0.0.0 --port 8080

## Python environment

Use a virtual environment:

    python3 -m venv .venv
    source .venv/bin/activate
    python -m pip install -r requirements.txt

## Repository layout

- app/: FastAPI application.
- config/: non-secret example configuration.
- profiles/: Meshtastic desired-state YAML profiles.
- playbooks/: playbook-style YAML actions.
- data/: runtime database/backups, ignored by git.
- logs/: runtime logs, ignored by git.

## Development rules

- Keep functions small and readable.
- Prefer explicit error handling.
- UI must be usable from a phone.
- Every backend endpoint should fail gracefully.
- Hardware access must be isolated behind a service/module layer.
- Do not hardcode /dev/ttyACM0; scan available serial ports.
- Add comments only where they explain non-obvious behavior.

## Review guidelines

- Check that the app starts without Meshtastic hardware connected.
- Check that no secrets or runtime data are committed.
- Check that Raspberry Pi Zero W constraints are respected.
- Check that systemd paths match /home/nicco/meshnodemgr.
