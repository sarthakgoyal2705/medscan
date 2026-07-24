"""Data-quality expectations enforced at the silver boundary.

Hand-rolled and readable rather than a heavy framework. Each check returns a
rejection reason string (or None if the row passes). A failing row is quarantined
with its reason, not dropped. Run-level checks (row-count sanity vs trailing
average) live in metrics.py where the history is available.
"""

from __future__ import annotations

from .records import PrescriptionLine

# plausible dosage strengths; anything outside is almost certainly a misread
KNOWN_UNITS = {"mg", "mcg", "g", "ml", "iu", "%"}
DOSE_MIN, DOSE_MAX = 0.0, 100000.0  # mcg-to-gram range, generous on purpose


def check_line(line: PrescriptionLine) -> str | None:
    """Return a rejection_reason if the line fails any expectation, else None."""
    if line.rejection_reason:
        return line.rejection_reason  # already flagged upstream (e.g. bad bronze)

    if not line.drug_name_normalized or not line.drug_name_normalized.strip():
        return "empty_drug_name"

    if not (0.0 <= line.extraction_confidence <= 1.0):
        return "confidence_out_of_range"

    if line.dosage_value is not None:
        if not isinstance(line.dosage_value, (int, float)):
            return "dosage_not_numeric"
        if not (DOSE_MIN <= line.dosage_value <= DOSE_MAX):
            return "dosage_out_of_range"

    if line.dosage_unit is not None and line.dosage_unit.lower() not in KNOWN_UNITS:
        return "unknown_dosage_unit"

    return None


def summarize(lines: list[PrescriptionLine]) -> dict:
    """Per-run breakdown of which expectations failed (feeds pipeline_metrics)."""
    failures: dict[str, int] = {}
    for ln in lines:
        reason = check_line(ln)
        if reason:
            failures[reason] = failures.get(reason, 0) + 1
    return failures
