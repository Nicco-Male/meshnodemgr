# PiAns Mesh Node Manager

Portable Meshtastic node manager designed to run first on Raspberry Pi Zero W / Raspberry Pi OS Lite.

Goal: provide an Ansible-like configuration manager for Meshtastic nodes.

## Current status

- FastAPI web UI running on port 8080.
- USB/serial port detection.
- Local Meshtastic CLI dependency.
- Basic project skeleton.

## Target architecture

- Raspberry Pi connected via USB to a local Meshtastic node.
- Phone connected to the Raspberry via Wi-Fi/hotspot.
- Web UI for inventory, backups, profiles and playbooks.
- Future support for Meshtastic remote administration.

## Run manually

    cd ~/meshnodemgr
    source .venv/bin/activate
    uvicorn app.main:app --host 0.0.0.0 --port 8080

## Systemd service

    sudo systemctl status meshnodemgr
    sudo journalctl -u meshnodemgr -f

## Project priorities

1. Detect local USB Meshtastic node.
2. Read local node info.
3. Build node inventory.
4. Backup node configuration.
5. Store desired profiles in YAML.
6. Show config diff.
7. Apply profiles locally.
8. Add remote admin support.
9. Add hotspot setup.
10. Build nicer mobile UI.
