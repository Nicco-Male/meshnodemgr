from __future__ import annotations

from glob import glob


SERIAL_PATTERNS = ("/dev/ttyACM*", "/dev/ttyUSB*")


def list_serial_ports() -> list[str]:
    """Return detected serial devices in stable order."""
    ports: list[str] = []
    for pattern in SERIAL_PATTERNS:
        ports.extend(glob(pattern))
    return sorted(ports)
