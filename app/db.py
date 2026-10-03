import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS recordings (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    error TEXT,
    created_at REAL NOT NULL,
    original_ext TEXT NOT NULL,
    original_size INTEGER DEFAULT 0,
    mp3_size INTEGER DEFAULT 0,
    duration REAL,
    language TEXT,
    text TEXT,
    utterances TEXT,
    words TEXT,
    assembly_id TEXT
);
"""

LIST_FIELDS = (
    "id, name, status, error, created_at, original_ext, original_size, mp3_size, duration, language, "
    "(text IS NOT NULL) AS has_text"
)


class DB:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def create(self, name: str, ext: str) -> str:
        rid = uuid.uuid4().hex
        with self._lock:
            self._conn.execute(
                "INSERT INTO recordings (id, name, status, created_at, original_ext) VALUES (?,?,?,?,?)",
                (rid, name, "queued", time.time(), ext),
            )
            self._conn.commit()
        return rid

    def update(self, rid: str, **fields) -> None:
        if not fields:
            return
        for k in ("utterances", "words"):
            if k in fields and not isinstance(fields[k], (str, type(None))):
                fields[k] = json.dumps(fields[k], ensure_ascii=False)
        cols = ", ".join(f"{k}=?" for k in fields)
        with self._lock:
            self._conn.execute(f"UPDATE recordings SET {cols} WHERE id=?", (*fields.values(), rid))
            self._conn.commit()

    def get(self, rid: str) -> dict | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM recordings WHERE id=?", (rid,)).fetchone()
        return self._row(row) if row else None

    def list_all(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {LIST_FIELDS} FROM recordings ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def delete(self, rid: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM recordings WHERE id=?", (rid,))
            self._conn.commit()

    def pending_ids(self) -> list[str]:
        """Записи, прерванные перезапуском сервера (не done/error)."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id FROM recordings WHERE status NOT IN ('done','error') ORDER BY created_at"
            ).fetchall()
        return [r["id"] for r in rows]

    @staticmethod
    def _row(row: sqlite3.Row) -> dict:
        d = dict(row)
        for k in ("utterances", "words"):
            d[k] = json.loads(d[k]) if d.get(k) else None
        return d
