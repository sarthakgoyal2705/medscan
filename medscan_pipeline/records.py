"""Typed record shapes at each stage boundary.

Dataclasses (stdlib) rather than Pydantic so the pipeline package stays
independent of the web app / FastAPI. Every record from ingest onward carries the
three lineage fields — source_file_hash, ingested_at, pipeline_run_id — which are
what make the stages idempotent and traceable.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class IngestRecord:
    pipeline_run_id: str
    source_file_hash: str          # sha256 of the image bytes — the idempotency key
    source_path: str
    media_type: str
    size_bytes: int
    ingested_at: str               # UTC ISO
    ingest_date: str               # partition key (YYYY-MM-DD)

    def dict(self) -> dict:
        return asdict(self)


@dataclass
class ExtractRecord:
    pipeline_run_id: str
    source_file_hash: str
    raw_response: str              # the model's structured JSON, stored verbatim (Bronze)
    model_name: str
    model_provider: str
    prompt_version: str
    ingested_at: str
    ingest_date: str

    def dict(self) -> dict:
        return asdict(self)


@dataclass
class PrescriptionLine:
    """One parsed, typed prescription line (Silver)."""
    line_id: str                   # deterministic: f"{hash[:12]}-{index}"
    source_file_hash: str
    drug_name_raw: str
    drug_name_normalized: str
    dosage_value: float | None
    dosage_unit: str | None
    frequency: str | None
    quantity: int | None
    extraction_confidence: float   # 0..1
    pipeline_run_id: str
    processed_at: str
    rejection_reason: str | None = None  # set only for quarantined rows

    def dict(self) -> dict:
        return asdict(self)


@dataclass
class MatchedLine:
    """A silver line joined to the product catalogue (Gold)."""
    line_id: str
    source_file_hash: str
    drug_name_normalized: str
    matched_product: str | None
    matched_salt: str | None
    match_score: int
    match_method: str              # "exact" | "blocked_fuzzy" | "unmatched"
    brand_price: float | None
    generic_name: str | None
    generic_price: float | None
    saving: float | None
    pipeline_run_id: str
    matched_at: str

    def dict(self) -> dict:
        return asdict(self)


@dataclass
class RunMetrics:
    """One row per pipeline run (Gold monitoring layer)."""
    pipeline_run_id: str
    run_started_at: str
    run_finished_at: str
    bronze_rows: int = 0
    silver_rows: int = 0
    quarantine_rows: int = 0
    gold_rows: int = 0
    matched_rows: int = 0
    match_rate: float = 0.0
    mean_confidence: float = 0.0
    stage_durations_sec: dict = field(default_factory=dict)
    status: str = "success"
    validation_failures: dict = field(default_factory=dict)

    def dict(self) -> dict:
        return asdict(self)
