"""Stage 1 — ingest.

Accept an image, compute a content hash (the idempotency key), record source
metadata. Pure: bytes in, IngestRecord out. No Spark, no web objects.
"""

from __future__ import annotations

import hashlib
import os

from . import config
from .records import IngestRecord

_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
         ".webp": "image/webp", ".gif": "image/gif"}


def ingest_bytes(image_bytes: bytes, source_path: str, run_id: str,
                 media_type: str | None = None) -> IngestRecord:
    """Idempotent: the same bytes always yield the same source_file_hash."""
    digest = hashlib.sha256(image_bytes).hexdigest()
    ext = os.path.splitext(source_path)[1].lower()
    now = config.utc_now_iso()
    return IngestRecord(
        pipeline_run_id=run_id,
        source_file_hash=digest,
        source_path=source_path,
        media_type=media_type or _MIME.get(ext, "image/png"),
        size_bytes=len(image_bytes),
        ingested_at=now,
        ingest_date=config.ingest_date(now),
    )


def ingest_path(path: str, run_id: str) -> tuple[IngestRecord, bytes]:
    with open(path, "rb") as f:
        data = f.read()
    return ingest_bytes(data, path, run_id), data


def discover_landing(run_id: str, landing_dir: str | None = None) -> list[tuple[IngestRecord, bytes]]:
    """Scan the landing folder for prescription images to process this run."""
    landing = landing_dir or config.LANDING_DIR
    out = []
    if not os.path.isdir(landing):
        return out
    for name in sorted(os.listdir(landing)):
        if os.path.splitext(name)[1].lower() in config.IMAGE_EXTS:
            out.append(ingest_path(os.path.join(landing, name), run_id))
    return out
