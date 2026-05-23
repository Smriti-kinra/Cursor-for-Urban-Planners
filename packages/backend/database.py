"""SQLite connection + schema management.

Single source of truth for the artifacts DB path. Anchors to the backend
directory regardless of CWD so the HTTP CRUD router and the LLM's
`create_artifact` tool always hit the same file.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

_BACKEND_DIR = Path(__file__).parent
DB_PATH = Path(os.environ.get("CURSOR_URBAN_DB", str(_BACKEND_DIR / "cursor_urban.db")))


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=5.0)
    conn.row_factory = sqlite3.Row
    # WAL allows concurrent reads while a write is in progress.
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
    except sqlite3.DatabaseError:
        pass
    return conn


# Ordered list of migrations. Index = target user_version. Each migration
# brings the DB from version (i) to version (i+1).
_MIGRATIONS: list[str] = [
    # 0 → 1 : initial schema
    """
    CREATE TABLE IF NOT EXISTS artifacts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        content TEXT NOT NULL,
        artifact_type TEXT NOT NULL DEFAULT 'note',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """,
]


def init_db() -> None:
    conn = get_connection()
    try:
        current = conn.execute("PRAGMA user_version").fetchone()[0]
        for version, sql in enumerate(_MIGRATIONS, start=1):
            if version > current:
                conn.executescript(sql)
                conn.execute(f"PRAGMA user_version = {version}")
                conn.commit()
    finally:
        conn.close()
