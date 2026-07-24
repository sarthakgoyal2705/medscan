"""Stage 3 — normalize.

Parse the raw Bronze response into typed, cleaned prescription lines (Silver).
Cleans drug-name strings, splits dosage into value + unit, maps a confidence
label to a 0..1 float. Pure: raw string in, list[PrescriptionLine] out.

line_id is deterministic — f"{hash[:12]}-{index}" — so re-normalizing the same
bronze row produces the same ids, which is what lets Silver dedupe via MERGE
instead of appending duplicates.
"""

from __future__ import annotations

import json
import re

from . import config
from .records import ExtractRecord, PrescriptionLine

_CONF = {"high": 0.95, "medium": 0.7, "low": 0.4}
_FORM_PREFIX = re.compile(r"^(tab|tablet|cap|capsule|syp|syrup|inj|injection|oint|cream|drops?|t|c)\.?\s+", re.I)
_DOSE = re.compile(r"([\d.]+)\s*(mg|mcg|g|ml|iu|%)", re.I)
_QTY = re.compile(r"(?:x|×)\s*(\d+)\s*(?:days?|tabs?|caps?)?", re.I)


def _clean_name(name: str) -> str:
    name = _FORM_PREFIX.sub("", (name or "").strip())
    name = re.sub(r"\s+", " ", name)
    return name.strip()


def _parse_dose(dosage: str | None):
    if not dosage:
        return None, None
    m = _DOSE.search(dosage)
    if not m:
        return None, None
    try:
        return float(m.group(1)), m.group(2).lower()
    except ValueError:
        return None, m.group(2).lower()


def _parse_qty(text: str | None):
    if not text:
        return None
    m = _QTY.search(text)
    return int(m.group(1)) if m else None


def normalize(extract_rec: ExtractRecord) -> list[PrescriptionLine]:
    now = config.utc_now_iso()
    try:
        payload = json.loads(extract_rec.raw_response)
    except json.JSONDecodeError:
        # a malformed bronze row still becomes one quarantinable line, not a crash
        return [PrescriptionLine(
            line_id=f"{extract_rec.source_file_hash[:12]}-0",
            source_file_hash=extract_rec.source_file_hash,
            drug_name_raw="", drug_name_normalized="",
            dosage_value=None, dosage_unit=None, frequency=None, quantity=None,
            extraction_confidence=0.0,
            pipeline_run_id=extract_rec.pipeline_run_id, processed_at=now,
            rejection_reason="unparseable_bronze_json")]

    lines: list[PrescriptionLine] = []
    for i, med in enumerate(payload.get("medicines", [])):
        raw = med.get("raw_text") or med.get("normalized_name") or ""
        normalized = _clean_name(med.get("normalized_name") or raw)
        dose_val, dose_unit = _parse_dose(med.get("dosage"))
        lines.append(PrescriptionLine(
            line_id=f"{extract_rec.source_file_hash[:12]}-{i}",
            source_file_hash=extract_rec.source_file_hash,
            drug_name_raw=raw,
            drug_name_normalized=normalized,
            dosage_value=dose_val,
            dosage_unit=dose_unit,
            frequency=med.get("frequency"),
            quantity=_parse_qty(med.get("frequency")),
            extraction_confidence=_CONF.get(str(med.get("confidence", "")).lower(), 0.5),
            pipeline_run_id=extract_rec.pipeline_run_id,
            processed_at=now,
        ))
    return lines
