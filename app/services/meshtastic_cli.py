from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from typing import Any


@dataclass
class MeshtasticCliResult:
    ok: bool
    port: str
    command: list[str]
    timeout_seconds: int
    returncode: int | None = None
    info: dict[str, Any] | None = None
    stdout: str = ""
    stderr: str = ""
    error: str | None = None


def run_meshtastic_info(port: str, timeout_seconds: int = 8) -> MeshtasticCliResult:
    command = ["meshtastic", "--port", port, "--info"]

    if not port:
        return MeshtasticCliResult(
            ok=False,
            port=port,
            command=command,
            timeout_seconds=timeout_seconds,
            error="missing_port",
        )

    if not os.path.exists(port):
        return MeshtasticCliResult(
            ok=False,
            port=port,
            command=command,
            timeout_seconds=timeout_seconds,
            error="port_not_found",
        )

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except FileNotFoundError:
        return MeshtasticCliResult(
            ok=False,
            port=port,
            command=command,
            timeout_seconds=timeout_seconds,
            error="meshtastic_cli_not_found",
        )
    except subprocess.TimeoutExpired as exc:
        return MeshtasticCliResult(
            ok=False,
            port=port,
            command=command,
            timeout_seconds=timeout_seconds,
            stdout=exc.stdout or "",
            stderr=exc.stderr or "",
            error="timeout",
        )
    except OSError as exc:
        return MeshtasticCliResult(
            ok=False,
            port=port,
            command=command,
            timeout_seconds=timeout_seconds,
            error=f"os_error:{exc}",
        )

    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()

    if completed.returncode != 0:
        return MeshtasticCliResult(
            ok=False,
            port=port,
            command=command,
            timeout_seconds=timeout_seconds,
            returncode=completed.returncode,
            stdout=stdout,
            stderr=stderr,
            error="command_failed",
        )

    parsed_info: dict[str, Any] | None = None
    if stdout:
        try:
            parsed = json.loads(stdout)
            if isinstance(parsed, dict):
                parsed_info = parsed
        except json.JSONDecodeError:
            parsed_info = None

    return MeshtasticCliResult(
        ok=True,
        port=port,
        command=command,
        timeout_seconds=timeout_seconds,
        returncode=completed.returncode,
        stdout=stdout,
        stderr=stderr,
        info=parsed_info,
    )


def run_meshtastic_remote_read(node_id: str, port: str, timeout_seconds: int = 8) -> MeshtasticCliResult:
    command = ["meshtastic", "--port", port, "--dest", node_id, "--info"]
    if not node_id:
        return MeshtasticCliResult(
            ok=False,
            port=port,
            command=command,
            timeout_seconds=timeout_seconds,
            error="missing_node_id",
        )
    if not port:
        return MeshtasticCliResult(
            ok=False,
            port=port,
            command=command,
            timeout_seconds=timeout_seconds,
            error="missing_port",
        )
    if not os.path.exists(port):
        return MeshtasticCliResult(
            ok=False,
            port=port,
            command=command,
            timeout_seconds=timeout_seconds,
            error="port_not_found",
        )
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout_seconds, check=False)
    except FileNotFoundError:
        return MeshtasticCliResult(
            ok=False,
            port=port,
            command=command,
            timeout_seconds=timeout_seconds,
            error="meshtastic_cli_not_found",
        )
    except subprocess.TimeoutExpired as exc:
        return MeshtasticCliResult(
            ok=False,
            port=port,
            command=command,
            timeout_seconds=timeout_seconds,
            stdout=exc.stdout or "",
            stderr=exc.stderr or "",
            error="timeout",
        )
    except OSError as exc:
        return MeshtasticCliResult(
            ok=False,
            port=port,
            command=command,
            timeout_seconds=timeout_seconds,
            error=f"os_error:{exc}",
        )
    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()
    if completed.returncode != 0:
        return MeshtasticCliResult(
            ok=False,
            port=port,
            command=command,
            timeout_seconds=timeout_seconds,
            returncode=completed.returncode,
            stdout=stdout,
            stderr=stderr,
            error="command_failed",
        )
    parsed_info: dict[str, Any] | None = None
    if stdout:
        try:
            parsed = json.loads(stdout)
            if isinstance(parsed, dict):
                parsed_info = parsed
        except json.JSONDecodeError:
            parsed_info = None
    return MeshtasticCliResult(
        ok=True,
        port=port,
        command=command,
        timeout_seconds=timeout_seconds,
        returncode=completed.returncode,
        stdout=stdout,
        stderr=stderr,
        info=parsed_info,
    )
