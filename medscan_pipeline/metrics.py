"""Run-metrics assembly + export of the latest run to the batch serving DB.

The Delta pipeline_metrics table is the system-of-record history. We also mirror
the newest row into data/serving.db (stdlib sqlite) so the FastAPI web process
can serve /pipeline/health WITHOUT importing Spark — the web image stays lean.
"""

from __future__ import annotations

import json
import sqlite3

from . import config
from .records import MatchedLine, RunMetrics

_SCHEMA = """
CREATE TABLE IF NOT EXISTS pipeline_metrics (
    pipeline_run_id TEXT PRIMARY KEY,
    run_started_at TEXT, run_finished_at TEXT,
    bronze_rows INTEGER, silver_rows INTEGER, quarantine_rows INTEGER,
    gold_rows INTEGER, matched_rows INTEGER,
    match_rate REAL, mean_confidence REAL,
    status TEXT, validation_failures TEXT, stage_durations_sec TEXT
);
"""


def compute_match_stats(matched: list[MatchedLine], mean_conf: float) -> dict:
    total = len(matched)
    hit = sum(1 for m in matched if m.match_method != "unmatched")
    return {
        "matched_rows": hit,
        "match_rate": round(hit / total, 4) if total else 0.0,
        "mean_confidence": round(mean_conf, 4),
    }


def export_to_serving(metrics: RunMetrics, db_path: str | None = None) -> None:
    """Mirror one run's metrics into sqlite for the web /pipeline/health endpoint."""
    with sqlite3.connect(db_path or config.SERVING_DB) as conn:
        conn.executescript(_SCHEMA)
        conn.execute(
            "INSERT OR REPLACE INTO pipeline_metrics VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (metrics.pipeline_run_id, metrics.run_started_at, metrics.run_finished_at,
             metrics.bronze_rows, metrics.silver_rows, metrics.quarantine_rows,
             metrics.gold_rows, metrics.matched_rows, metrics.match_rate,
             metrics.mean_confidence, metrics.status,
             json.dumps(metrics.validation_failures),
             json.dumps(metrics.stage_durations_sec)))
