"""Stage 5 — load.

Write curated matched results to the batch serving store (a separate SQLite DB,
data/serving.db). Deliberately NOT the app's users.db and NOT bulk.json — the
live medicine lookup path is untouched. Idempotent via INSERT OR REPLACE keyed on
line_id, so re-running a batch overwrites rather than duplicates.

stdlib sqlite3 only — no Spark import here, so the web process can read this table
for /pipeline/health without any heavy dependency.
"""

from __future__ import annotations

import sqlite3

from . import config
from .records import MatchedLine

_SCHEMA = """
CREATE TABLE IF NOT EXISTS pipeline_prescriptions (
    line_id TEXT PRIMARY KEY,
    source_file_hash TEXT NOT NULL,
    drug_name_normalized TEXT,
    matched_product TEXT,
    matched_salt TEXT,
    match_score INTEGER,
    match_method TEXT,
    brand_price REAL,
    generic_name TEXT,
    generic_price REAL,
    saving REAL,
    pipeline_run_id TEXT,
    matched_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_pp_run ON pipeline_prescriptions(pipeline_run_id);
"""


def _connect(db_path: str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path or config.SERVING_DB)
    conn.executescript(_SCHEMA)
    return conn


def load(matched: list[MatchedLine], db_path: str | None = None) -> int:
    """INSERT OR REPLACE on line_id → idempotent re-runs. Returns rows written."""
    if not matched:
        return 0
    rows = [(m.line_id, m.source_file_hash, m.drug_name_normalized, m.matched_product,
             m.matched_salt, m.match_score, m.match_method, m.brand_price,
             m.generic_name, m.generic_price, m.saving, m.pipeline_run_id, m.matched_at)
            for m in matched]
    with _connect(db_path) as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO pipeline_prescriptions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    return len(rows)
