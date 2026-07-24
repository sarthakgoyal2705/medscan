"""Read-only view of the batch pipeline's health for the web app.

Deliberately stdlib-only (sqlite3 + json). The web process must never import
Spark/Delta — it just reads the metrics that the pipeline mirrored into
data/serving.db. If the pipeline has never run, endpoints report that cleanly.
"""

from __future__ import annotations

import json
import os
import sqlite3

# same default the pipeline uses; overridable for tests/deploys
SERVING_DB = os.environ.get("MEDSCAN_SERVING_DB",
                            os.path.join(os.getcwd(), "data", "serving.db"))


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def pipeline_health() -> dict:
    if not os.path.exists(SERVING_DB):
        return {"status": "no_runs", "detail": "The batch pipeline has not run yet."}
    conn = sqlite3.connect(SERVING_DB)
    conn.row_factory = sqlite3.Row
    try:
        if not _has_table(conn, "pipeline_metrics"):
            return {"status": "no_runs", "detail": "No pipeline_metrics table yet."}
        row = conn.execute(
            "SELECT * FROM pipeline_metrics ORDER BY run_finished_at DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return {"status": "no_runs", "detail": "No runs recorded."}
        total_runs = conn.execute("SELECT COUNT(*) FROM pipeline_metrics").fetchone()[0]
        served = 0
        if _has_table(conn, "pipeline_prescriptions"):
            served = conn.execute("SELECT COUNT(*) FROM pipeline_prescriptions").fetchone()[0]

        silver = row["silver_rows"] or 0
        quarantine = row["quarantine_rows"] or 0
        denom = silver + quarantine
        return {
            "status": "ok" if row["status"] == "success" else row["status"],
            "last_run_id": row["pipeline_run_id"],
            "last_run_at": row["run_finished_at"],
            "total_runs": total_runs,
            "match_rate": row["match_rate"],
            "mean_confidence": row["mean_confidence"],
            "rows": {
                "bronze": row["bronze_rows"], "silver": silver,
                "quarantine": quarantine, "gold": row["gold_rows"],
                "matched": row["matched_rows"],
            },
            "quarantine_rate": round(quarantine / denom, 4) if denom else 0.0,
            "validation_failures": json.loads(row["validation_failures"] or "{}"),
            "stage_durations_sec": json.loads(row["stage_durations_sec"] or "{}"),
            "served_prescription_lines": served,
        }
    finally:
        conn.close()
