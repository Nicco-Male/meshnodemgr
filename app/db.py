from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

DB_PATH = Path("data") / "meshnodemgr.db"

MANAGEMENT_STATES = (
    "discovered",
    "pending_management",
    "remote_read_requested",
    "remote_read_ok",
    "remote_read_failed",
    "human_verified",
    "managed",
    "drift_detected",
)


def init_db() -> Path:
    """Create runtime data dir and initialize SQLite schema."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS connections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                type TEXT NOT NULL CHECK(type IN ('serial', 'tcp')),
                serial_port TEXT,
                host TEXT,
                port INTEGER,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                connection_type TEXT NOT NULL,
                connection_target TEXT NOT NULL,
                status TEXT NOT NULL,
                raw_path TEXT NOT NULL,
                normalized_path TEXT NOT NULL,
                local_node_id TEXT,
                local_node_name TEXT,
                node_count INTEGER NOT NULL DEFAULT 0,
                verified INTEGER NOT NULL DEFAULT 0,
                verified_at TEXT,
                verification_note TEXT,
                rejected INTEGER NOT NULL DEFAULT 0,
                rejected_at TEXT,
                rejected_reason TEXT,
                source_node_short_name TEXT,
                source_node_hw_model TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS nodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_id INTEGER NOT NULL,
                node_num INTEGER,
                node_id TEXT,
                short_name TEXT,
                long_name TEXT,
                hw_model TEXT,
                role TEXT,
                last_heard INTEGER,
                snr REAL,
                raw_json TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(snapshot_id) REFERENCES snapshots(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS managed_nodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                node_id TEXT NOT NULL UNIQUE,
                node_num INTEGER,
                short_name TEXT,
                long_name TEXT,
                hw_model TEXT,
                role TEXT,
                management_state TEXT NOT NULL DEFAULT 'pending_management',
                state_reason TEXT,
                planned_remote_read INTEGER NOT NULL DEFAULT 1,
                remote_read_last_error TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS remote_reads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                node_id TEXT NOT NULL,
                gateway_connection_type TEXT NOT NULL,
                gateway_connection_target TEXT NOT NULL,
                status TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 1,
                timeout_seconds INTEGER NOT NULL DEFAULT 8,
                error TEXT,
                raw_path TEXT NOT NULL,
                normalized_path TEXT NOT NULL,
                verified INTEGER NOT NULL DEFAULT 0,
                verified_at TEXT,
                verification_note TEXT,
                rejected INTEGER NOT NULL DEFAULT 0,
                rejected_at TEXT,
                rejected_reason TEXT,
                source_node_short_name TEXT,
                source_node_hw_model TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS drift_checks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_id INTEGER NOT NULL,
                baseline_snapshot_id INTEGER,
                drift_detected INTEGER NOT NULL DEFAULT 0,
                summary TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(snapshot_id) REFERENCES snapshots(id),
                FOREIGN KEY(baseline_snapshot_id) REFERENCES snapshots(id)
            )
            """
        )
        conn.commit()

    return DB_PATH


def list_connections() -> list[dict[str, Any]]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT id, name, type, serial_port, host, port, enabled, created_at, updated_at
            FROM connections ORDER BY updated_at DESC, id DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def create_snapshot_record(payload: dict[str, Any]) -> int:
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(
            """
            INSERT INTO snapshots (
                connection_type, connection_target, status, raw_path, normalized_path,
                local_node_id, local_node_name, node_count, verified, source_node_short_name, source_node_hw_model
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
            """,
            (
                payload["connection_type"],
                payload["connection_target"],
                payload["status"],
                payload["raw_path"],
                payload["normalized_path"],
                payload.get("local_node_id"),
                payload.get("local_node_name"),
                payload.get("node_count", 0),
                payload.get("source_node_short_name"),
                payload.get("source_node_hw_model"),
            ),
        )
        snapshot_id = int(cur.lastrowid)
        conn.commit()
    return snapshot_id


def insert_snapshot_nodes(snapshot_id: int, nodes: list[dict[str, Any]]) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        for node in nodes:
            conn.execute(
                """
                INSERT INTO nodes (
                    snapshot_id, node_num, node_id, short_name, long_name,
                    hw_model, role, last_heard, snr, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    node.get("node_num"),
                    node.get("node_id"),
                    node.get("short_name"),
                    node.get("long_name"),
                    node.get("hw_model"),
                    node.get("role"),
                    node.get("last_heard"),
                    node.get("snr"),
                    json.dumps(node.get("raw", {}), ensure_ascii=False),
                ),
            )
        conn.commit()


def list_nodes(snapshot_id: int | None = None) -> list[dict[str, Any]]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        if snapshot_id is None:
            rows = conn.execute(
                """
                SELECT n.*, s.created_at AS snapshot_created_at
                FROM nodes n
                JOIN snapshots s ON s.id = n.snapshot_id
                ORDER BY n.id DESC
                """
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT n.*, s.created_at AS snapshot_created_at
                FROM nodes n
                JOIN snapshots s ON s.id = n.snapshot_id
                WHERE n.snapshot_id = ?
                ORDER BY n.id
                """,
                (snapshot_id,),
            ).fetchall()
    return [dict(row) for row in rows]


def mark_node_as_managed(node_id: str) -> bool:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        node = conn.execute(
            """
            SELECT node_id, node_num, short_name, long_name, hw_model, role
            FROM nodes
            WHERE node_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (node_id,),
        ).fetchone()
        if not node:
            return False

        conn.execute(
            """
            INSERT INTO managed_nodes (
                node_id, node_num, short_name, long_name, hw_model, role,
                management_state, state_reason, planned_remote_read, remote_read_last_error,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'pending_management', ?, 1, NULL, CURRENT_TIMESTAMP)
            ON CONFLICT(node_id) DO UPDATE SET
                node_num=excluded.node_num,
                short_name=excluded.short_name,
                long_name=excluded.long_name,
                hw_model=excluded.hw_model,
                role=excluded.role,
                management_state='pending_management',
                state_reason=excluded.state_reason,
                planned_remote_read=1,
                remote_read_last_error=NULL,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                node["node_id"],
                node["node_num"],
                node["short_name"],
                node["long_name"],
                node["hw_model"],
                node["role"],
                "Remote read planned only; no remote command sent yet.",
            ),
        )
        conn.commit()
    return True


def unmanage_node(node_id: str) -> bool:
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute("DELETE FROM managed_nodes WHERE node_id = ?", (node_id,))
        conn.commit()
    return cur.rowcount > 0


def list_managed_nodes() -> list[dict[str, Any]]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT id, node_id, node_num, short_name, long_name, hw_model, role,
                   management_state, state_reason, planned_remote_read,
                   remote_read_last_error, created_at, updated_at
            FROM managed_nodes
            ORDER BY updated_at DESC, id DESC
            """
        ).fetchall()
    return [dict(row) for row in rows if row["management_state"] in MANAGEMENT_STATES]


def list_snapshots() -> list[dict[str, Any]]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT id, connection_type, connection_target, status, raw_path,
                   normalized_path, local_node_id, local_node_name, node_count,
                   verified, verified_at, verification_note, rejected, rejected_at, rejected_reason,
                   source_node_short_name, source_node_hw_model, created_at
            FROM snapshots
            ORDER BY id DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def get_snapshot(snapshot_id: int) -> dict[str, Any] | None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT id, connection_type, connection_target, status, raw_path,
                   normalized_path, local_node_id, local_node_name, node_count,
                   verified, verified_at, verification_note, rejected, rejected_at, rejected_reason,
                   source_node_short_name, source_node_hw_model, created_at
            FROM snapshots WHERE id = ?
            """,
            (snapshot_id,),
        ).fetchone()
    return dict(row) if row else None


def verify_snapshot(snapshot_id: int) -> bool:
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(
            "UPDATE snapshots SET verified = 1, verified_at = CURRENT_TIMESTAMP WHERE id = ?",
            (snapshot_id,),
        )
        conn.commit()
    return cur.rowcount > 0


def create_remote_read_record(payload: dict[str, Any]) -> int:
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(
            """
            INSERT INTO remote_reads (
                node_id, gateway_connection_type, gateway_connection_target,
                status, attempts, timeout_seconds, error, raw_path, normalized_path, verified
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                payload["node_id"],
                payload["gateway_connection_type"],
                payload["gateway_connection_target"],
                payload["status"],
                payload.get("attempts", 1),
                payload.get("timeout_seconds", 8),
                payload.get("error"),
                payload["raw_path"],
                payload["normalized_path"],
            ),
        )
        remote_read_id = int(cur.lastrowid)
        conn.commit()
    return remote_read_id


def list_remote_reads(node_id: str | None = None) -> list[dict[str, Any]]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        if node_id:
            rows = conn.execute(
                """
                SELECT id, node_id, gateway_connection_type, gateway_connection_target, status,
                       attempts, timeout_seconds, error, raw_path, normalized_path, verified,
                       verified_at, created_at
                FROM remote_reads
                WHERE node_id = ?
                ORDER BY id DESC
                """,
                (node_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, node_id, gateway_connection_type, gateway_connection_target, status,
                       attempts, timeout_seconds, error, raw_path, normalized_path, verified,
                       verified_at, created_at
                FROM remote_reads
                ORDER BY id DESC
                """
            ).fetchall()
    return [dict(row) for row in rows]


def verify_remote_read(remote_read_id: int) -> bool:
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(
            """
            UPDATE remote_reads
            SET verified = 1,
                verified_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (remote_read_id,),
        )
        conn.commit()
    return cur.rowcount > 0


def update_managed_node_remote_state(node_id: str, ok: bool, error: str | None = None) -> None:
    state = "remote_read_ok" if ok else "remote_read_failed"
    reason = "Remote read completed. Pending human verification." if ok else "Remote read failed."
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            UPDATE managed_nodes
            SET management_state = ?,
                state_reason = ?,
                remote_read_last_error = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE node_id = ?
            """,
            (state, reason, error, node_id),
        )
        conn.commit()

def ensure_snapshot_columns() -> None:
    columns = {
        "verification_note": "TEXT",
        "rejected": "INTEGER NOT NULL DEFAULT 0",
        "rejected_at": "TEXT",
        "rejected_reason": "TEXT",
        "source_node_short_name": "TEXT",
        "source_node_hw_model": "TEXT",
    }
    with sqlite3.connect(DB_PATH) as conn:
        existing = {r[1] for r in conn.execute("PRAGMA table_info(snapshots)").fetchall()}
        for col, ddl in columns.items():
            if col not in existing:
                conn.execute(f"ALTER TABLE snapshots ADD COLUMN {col} {ddl}")
        conn.commit()


def reject_snapshot(snapshot_id: int, reason: str | None = None) -> bool:
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute("UPDATE snapshots SET rejected = 1, rejected_at = CURRENT_TIMESTAMP, rejected_reason = ? WHERE id = ?", (reason, snapshot_id))
        conn.commit()
    return cur.rowcount > 0


def delete_snapshot(snapshot_id: int) -> bool:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM nodes WHERE snapshot_id = ?", (snapshot_id,))
        cur = conn.execute("DELETE FROM snapshots WHERE id = ?", (snapshot_id,))
        conn.commit()
    return cur.rowcount > 0


def delete_snapshots_unverified() -> list[int]:
    with sqlite3.connect(DB_PATH) as conn:
        ids = [int(r[0]) for r in conn.execute("SELECT id FROM snapshots WHERE verified = 0").fetchall()]
        if ids:
            conn.executemany("DELETE FROM nodes WHERE snapshot_id = ?", [(i,) for i in ids])
            conn.executemany("DELETE FROM snapshots WHERE id = ?", [(i,) for i in ids])
            conn.commit()
    return ids


def delete_snapshots_failed_or_empty() -> list[int]:
    with sqlite3.connect(DB_PATH) as conn:
        ids = [int(r[0]) for r in conn.execute("SELECT id FROM snapshots WHERE status = 'failed' OR (node_count = 0 AND verified = 0)").fetchall()]
        if ids:
            conn.executemany("DELETE FROM nodes WHERE snapshot_id = ?", [(i,) for i in ids])
            conn.executemany("DELETE FROM snapshots WHERE id = ?", [(i,) for i in ids])
            conn.commit()
    return ids
