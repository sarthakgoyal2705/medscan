"""Pipeline configuration and lineage helpers.

Everything is driven by DATA_ROOT so the same code runs against a local
filesystem (default) or an abfss:// path on Azure (Phase 6) with no other change.
Kept dependency-free (stdlib only) so any stage module can import it without
pulling in Spark.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

# Local default; Phase 6 sets this to abfss://<container>@<account>.dfs.core.windows.net/...
DATA_ROOT = os.environ.get("MEDSCAN_DATA_ROOT", os.path.join(os.getcwd(), "data"))

# Medallion layer locations
BRONZE_PATH = f"{DATA_ROOT}/bronze/prescriptions"
SILVER_PATH = f"{DATA_ROOT}/silver/prescription_lines"
QUARANTINE_PATH = f"{DATA_ROOT}/silver/_quarantine"
GOLD_MATCHED_PATH = f"{DATA_ROOT}/gold/matched_products"
GOLD_METRICS_PATH = f"{DATA_ROOT}/gold/pipeline_metrics"

# Where new prescription images are dropped for the batch DAG to pick up.
LANDING_DIR = os.environ.get("MEDSCAN_LANDING_DIR", os.path.join(os.getcwd(), "data", "landing"))

# Batch serving DB (separate from the app's users.db; the live medicine lookup
# still reads bulk.json in memory — the batch pipeline never touches that path).
SERVING_DB = os.environ.get("MEDSCAN_SERVING_DB", os.path.join(os.getcwd(), "data", "serving.db"))

# Read-only product catalogue the matcher scores against.
CATALOGUE_JSON = os.path.join(os.getcwd(), "data", "bulk.json")

# Bump when the extraction prompt changes — lets us tell which bronze rows came
# from which prompt version when we replay.
PROMPT_VERSION = "v1"

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def new_run_id() -> str:
    """A unique id for one end-to-end pipeline execution (used for lineage)."""
    return f"run_{datetime.now(timezone.utc):%Y%m%dT%H%M%S}_{uuid.uuid4().hex[:8]}"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ingest_date(iso_ts: str | None = None) -> str:
    """Partition key: the UTC date portion of an ISO timestamp."""
    ts = datetime.fromisoformat(iso_ts) if iso_ts else datetime.now(timezone.utc)
    return f"{ts:%Y-%m-%d}"
