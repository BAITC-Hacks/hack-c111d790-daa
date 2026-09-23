"""Source-backed partner data, kept separate from the synthetic daily demo."""

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def connect():
    path = Path(os.environ.get("EKT_PARTNER_DB", "data/partners/partners.sqlite3"))
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=60)
    db.row_factory = sqlite3.Row
    db.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS companies(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS products(company TEXT, sku TEXT, payload TEXT NOT NULL,
            PRIMARY KEY(company,sku));
        CREATE TABLE IF NOT EXISTS raw_rows(company TEXT, file TEXT, sheet TEXT, row_number INTEGER, payload TEXT);
        CREATE TABLE IF NOT EXISTS events(company TEXT, sku TEXT, date TEXT, warehouse TEXT,
            document TEXT, quantity REAL, source_row INTEGER);
        CREATE INDEX IF NOT EXISTS events_key ON events(company,sku,date);
        CREATE TABLE IF NOT EXISTS revisions(id INTEGER PRIMARY KEY AUTOINCREMENT,
            company TEXT, sku TEXT, created_at TEXT, note TEXT, before_json TEXT, after_json TEXT);
        CREATE TABLE IF NOT EXISTS partner_runs(id TEXT PRIMARY KEY, created_at TEXT, company TEXT, payload TEXT);
    """)
    try:
        yield db
        db.commit()
    finally:
        db.close()


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False, allow_nan=False, default=str)


def companies():
    with connect() as db:
        return [json.loads(r[0]) for r in db.execute("SELECT payload FROM companies ORDER BY id")]


def get_company(company):
    with connect() as db:
        row = db.execute("SELECT payload FROM companies WHERE id=?", (company,)).fetchone()
    return json.loads(row[0]) if row else None


def get_product(company, sku):
    with connect() as db:
        row = db.execute("SELECT payload FROM products WHERE company=? AND sku=?", (company, sku)).fetchone()
    return json.loads(row[0]) if row else None


def all_products(company):
    with connect() as db:
        return [
            json.loads(r[0])
            for r in db.execute("SELECT payload FROM products WHERE company=? ORDER BY sku", (company,))
        ]
