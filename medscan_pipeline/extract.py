"""Stage 2 — extract.

Call the Vision LLM and capture its output UNTOUCHED for Bronze. We deliberately
store the model's structured JSON verbatim (json string) so that if normalization
logic changes later, we can rebuild silver/gold from bronze without re-paying for
inference — that replayability is the whole argument for the medallion layout.

Reuses app.extraction so there is exactly one LLM integration in the codebase
(no duplicated provider logic). This is the only place the pipeline touches the
app package, and only for the provider call — no web/request objects cross over.
"""

from __future__ import annotations

import json

from app import extraction  # single source of truth for the LLM call

from . import config
from .records import ExtractRecord, IngestRecord


def extract(ingest_rec: IngestRecord, image_bytes: bytes) -> ExtractRecord:
    """Run the configured vision backend; return raw model output + provenance.

    Raises the same NotConfigured/Refused/UpstreamBusy errors app.extraction does,
    so the orchestrator (Airflow) can apply retry policy on this stage specifically.
    """
    provider = extraction.backend()
    model = {
        "gemini": extraction.GEMINI_MODEL,
        "claude": extraction.CLAUDE_MODEL,
        "ollama": extraction.OLLAMA_MODEL,
    }.get(provider, provider)

    result = extraction.extract_from_image(image_bytes, ingest_rec.media_type)

    return ExtractRecord(
        pipeline_run_id=ingest_rec.pipeline_run_id,
        source_file_hash=ingest_rec.source_file_hash,
        # verbatim structured output — Bronze is the immutable replay source
        raw_response=json.dumps(result, ensure_ascii=False, sort_keys=True),
        model_name=model,
        model_provider=provider,
        prompt_version=config.PROMPT_VERSION,
        ingested_at=ingest_rec.ingested_at,
        ingest_date=ingest_rec.ingest_date,
    )
