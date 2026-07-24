"""Stage 4 — match (single-record path).

Wraps the existing RapidFuzz matcher so a single prescription line can be scored
against the catalogue with no Spark involved. This is the SAME code the live API
uses; the batch Spark equivalent lives in match_spark.py. Having both, and using
each where it fits (low-latency single lookups here, high-volume batch there), is
deliberate — see the README design notes.
"""

from __future__ import annotations

from app import matcher  # reuse the live matcher — one matching implementation

from . import config
from .records import MatchedLine, PrescriptionLine


def match_line(line: PrescriptionLine) -> MatchedLine:
    entry, score = matcher.match_one(line.drug_name_normalized)
    now = config.utc_now_iso()
    if entry is None:
        return MatchedLine(
            line_id=line.line_id, source_file_hash=line.source_file_hash,
            drug_name_normalized=line.drug_name_normalized,
            matched_product=None, matched_salt=None,
            match_score=score, match_method="unmatched",
            brand_price=None, generic_name=None, generic_price=None, saving=None,
            pipeline_run_id=line.pipeline_run_id, matched_at=now)

    method = "exact" if score >= 100 else "blocked_fuzzy"
    saving = round(entry["brand_price"] - entry["generic"]["price"], 2)
    return MatchedLine(
        line_id=line.line_id, source_file_hash=line.source_file_hash,
        drug_name_normalized=line.drug_name_normalized,
        matched_product=entry["brand"], matched_salt=entry["salt"],
        match_score=score, match_method=method,
        brand_price=entry["brand_price"],
        generic_name=entry["generic"]["name"], generic_price=entry["generic"]["price"],
        saving=saving,
        pipeline_run_id=line.pipeline_run_id, matched_at=now)


def match_lines(lines: list[PrescriptionLine]) -> list[MatchedLine]:
    return [match_line(ln) for ln in lines]
