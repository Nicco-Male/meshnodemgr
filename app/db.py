from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path("data") / "meshnodemgr.db"


def init_db() -> Path:
    """Create runtime data dir and initialize lightweight SQLite schema."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                node_id TEXT,
                profile TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()

    return DB_PATH


def fetch_inventory() -> list[dict[str, str | int | None]]:
    """Return inventory rows as a list of dictionaries."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, name, node_id, profile, created_at FROM inventory ORDER BY id"
        ).fetchall()

    return [dict(row) for row in rows]
