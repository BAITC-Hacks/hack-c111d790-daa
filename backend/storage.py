"""Local persistence. Snapshots are immutable and approval is transactional."""

import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4


def now() -> str:
    return datetime.now(UTC).isoformat()


def digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


@contextmanager
def db():
    path = Path(os.environ.get("EKT_DB", "data/ekt.sqlite3"))
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS datasets (
                id TEXT PRIMARY KEY, created_at TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY, created_at TEXT NOT NULL, dataset_id TEXT NOT NULL,
                payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'draft', approval TEXT);
            CREATE TABLE IF NOT EXISTS audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
                action TEXT NOT NULL, entity_id TEXT NOT NULL, details TEXT NOT NULL);
        """)
        yield conn
        conn.commit()
    finally:
        conn.close()


def save_dataset(payload: dict) -> str:
    identity = digest(payload)
    with db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO datasets VALUES (?, ?, ?)",
            (identity, now(), json.dumps(payload, ensure_ascii=False)),
        )
        conn.execute(
            "INSERT INTO audit(created_at,action,entity_id,details) VALUES(?,?,?,?)",
            (now(), "dataset_imported", identity, json.dumps({"synthetic": payload["synthetic"]})),
        )
    return identity


def latest_dataset() -> tuple[str, dict] | None:
    with db() as conn:
        row = conn.execute("SELECT * FROM datasets ORDER BY created_at DESC LIMIT 1").fetchone()
    return (row["id"], json.loads(row["payload"])) if row else None


def save_run(dataset_id: str, payload: dict) -> dict:
    identity = uuid4().hex
    payload.update(id=identity, created_at=now(), dataset_id=dataset_id, status="draft", approval=None)
    with db() as conn:
        conn.execute(
            "INSERT INTO runs(id,created_at,dataset_id,payload) VALUES(?,?,?,?)",
            (identity, payload["created_at"], dataset_id, json.dumps(payload, ensure_ascii=False)),
        )
        conn.execute(
            "INSERT INTO audit(created_at,action,entity_id,details) VALUES(?,?,?,?)",
            (now(), "run_created", identity, json.dumps(payload["options"])),
        )
    return payload


def get_run(identity: str) -> dict | None:
    with db() as conn:
        row = conn.execute("SELECT * FROM runs WHERE id=?", (identity,)).fetchone()
    if not row:
        return None
    payload = json.loads(row["payload"])
    payload.update(status=row["status"], approval=json.loads(row["approval"]) if row["approval"] else None)
    return payload


def list_runs() -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            "SELECT id,created_at,status,payload FROM runs ORDER BY created_at DESC LIMIT 30"
        ).fetchall()
    return [
        dict(
            id=r["id"],
            created_at=r["created_at"],
            status=r["status"],
            summary=json.loads(r["payload"])["summary"],
        )
        for r in rows
    ]


def approve(identity: str, approval: dict) -> bool:
    with db() as conn:
        updated = conn.execute(
            "UPDATE runs SET status='approved', approval=? WHERE id=? AND status='draft'",
            (json.dumps(approval, ensure_ascii=False), identity),
        ).rowcount
        if updated:
            conn.execute(
                "INSERT INTO audit(created_at,action,entity_id,details) VALUES(?,?,?,?)",
                (now(), "run_approved", identity, json.dumps(approval, ensure_ascii=False)),
            )
    return bool(updated)
