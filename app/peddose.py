"""Paediatric weight-based dose calculator.

Guide doses only — every response carries the disclaimer and per-drug cautions.
Hard safety rails: plausible-weight bounds, per-dose caps, age minimums.
"""

import json
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "ped_doses.json"

with open(DATA_PATH, encoding="utf-8") as f:
    _DATA = json.load(f)

DISCLAIMER = _DATA["disclaimer"]
_RULES = {r["id"]: r for r in _DATA["rules"]}

MIN_WEIGHT_KG = 2.5
MAX_WEIGHT_KG = 60.0


class DoseError(Exception):
    pass


def supported() -> list[dict]:
    return [{"id": r["id"], "label": r["label"]} for r in _DATA["rules"]]


def rule_for_salts(salt_keys: list[str]) -> dict | None:
    """Best rule whose salts are all present in the medicine's salt keys."""
    keys = {k.lower() for k in salt_keys}
    best = None
    for r in _DATA["rules"]:
        need = set(r["salts"])
        if need <= keys and (best is None or len(need) > len(set(best["salts"]))):
            best = r
    return best


def _round_ml(ml: float) -> float:
    """Round to the nearest 0.25 ml below 5 ml, else 0.5 ml — syringe-measurable."""
    step = 0.25 if ml < 5 else 0.5
    return round(round(ml / step) * step, 2)


def compute(rule_id: str, weight_kg: float) -> dict:
    rule = _RULES.get(rule_id)
    if rule is None:
        raise DoseError(f"No paediatric dosing data for '{rule_id}'.")
    if not (MIN_WEIGHT_KG <= weight_kg <= MAX_WEIGHT_KG):
        raise DoseError(
            f"Weight must be between {MIN_WEIGHT_KG} and {MAX_WEIGHT_KG} kg. "
            "For newborns or larger children/adults, ask a doctor directly.")

    cautions = []
    if rule.get("min_age_months"):
        m = rule["min_age_months"]
        age = f"{m // 12} year(s)" if m >= 12 else f"{m} month(s)"
        cautions.append(f"Not for children below {age} without a doctor's advice.")

    out = {
        "label": rule["label"],
        "weight_kg": weight_kg,
        "frequency": rule["frequency"],
        "max_doses_per_day": rule.get("max_doses_per_day"),
        "notes": rule.get("notes", ""),
        "cautions": cautions,
        "disclaimer": DISCLAIMER,
    }

    if rule["type"] == "fixed":
        out["fixed_doses"] = rule["fixed_doses"]
        return out

    low = rule["mg_per_kg_low"] * weight_kg
    high = rule["mg_per_kg_high"] * weight_kg
    cap = rule.get("max_single_mg")
    capped = False
    if cap:
        if high > cap:
            high, capped = cap, True
        if low > cap:
            low = cap
    if capped:
        cautions.append(f"Dose capped at the child maximum of {cap} mg per dose.")

    out["dose_mg_low"] = round(low, 1)
    out["dose_mg_high"] = round(high, 1)
    out["syrups"] = [
        {
            "label": s["label"],
            "ml_low": _round_ml(low / s["mg_per_ml"]),
            "ml_high": _round_ml(high / s["mg_per_ml"]),
        }
        for s in rule.get("syrups", [])
    ]
    return out
