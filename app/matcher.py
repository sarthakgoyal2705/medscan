"""Match extracted (possibly misspelled) drug names against the formulary,
map brands to salt compositions and generic alternatives, and flag
dangerous drug interactions.

Two data layers:
  - curated (data/medicines.json, ~270 entries) — hand-checked categories,
    aliases, and real Jan Aushadhi-style generic prices. Wins on conflicts.
  - bulk (data/bulk.json, ~246k entries from the 1mg dataset) — every product
    gets a salt *signature*; products sharing a signature are interchangeable
    brands, and the cheapest of them is offered as the generic alternative.
"""

import bisect
import json
from collections import defaultdict
from itertools import combinations
from pathlib import Path

import re

from rapidfuzz import fuzz, process

from .salts import parse_salt_string, signature

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

with open(DATA_DIR / "medicines.json", encoding="utf-8") as f:
    _DB = json.load(f)

with open(DATA_DIR / "interactions.json", encoding="utf-8") as f:
    _INTERACTIONS = json.load(f)["interactions"]

DISCLAIMER = _DB["disclaimer"]
BRANDS = _DB["brands"]

# ------------------------------------------------------------- bulk layer --
_BULK_PATH = DATA_DIR / "bulk.json"
if _BULK_PATH.exists():
    with open(_BULK_PATH, encoding="utf-8") as f:
        _BULK = json.load(f)
else:  # app still works with just the curated layer
    _BULK = {"sigs": [], "items": []}

_SIGS = _BULK["sigs"]    # [sig_string, cheapest_name, cheapest_price, count]
_ITEMS = _BULK["items"]  # [name, salt_str, [salt_keys], pack, price, sig_idx]

_SIG_IDX = {s[0]: i for i, s in enumerate(_SIGS)}
_SIG_MEMBERS: dict[int, list[int]] = defaultdict(list)
for _i, _it in enumerate(_ITEMS):
    _SIG_MEMBERS[_it[5]].append(_i)

# Link curated entries into bulk salt groups so they get alternatives too.
for _e in BRANDS:
    _e["_sig"] = _SIG_IDX.get(signature(parse_salt_string(_e["salt"])))

# ------------------------------------------------------------ search index --
_WS_RE = re.compile(r"\s+")


def _norm(s: str) -> str:
    """Hyphens and case are noise in drug names: 'Montek-LC' == 'montek lc'."""
    return _WS_RE.sub(" ", s.lower().replace("-", " ")).strip()


# term -> ("c", curated entry) | ("b", bulk item index). Curated terms are
# registered first so they win exact-match collisions.
_INDEX: dict[str, tuple] = {}
for entry in BRANDS:
    for term in [entry["brand"], *entry.get("aliases", []), entry["salt"]]:
        _INDEX.setdefault(_norm(term), ("c", entry))

_CUR_TERMS = list(_INDEX.keys())

# Bulk names end in a dosage form ("Calpol 650 Tablet", "Ascoril LS Dry Syrup");
# prescriptions omit it, so index a suffix-stripped variant of each name too.
_FORM_SUFFIX = re.compile(
    r"(\s+(oral|dry|eye|ear|nasal|dispersible|effervescent|chewable))*"
    r"\s+(tablets?|capsules?|syrups?|injections?|suspensions?|creams?|gels?|ointments?|"
    r"drops?|solutions?|infusions?|respules?|rotacaps?|inhalers?|sachets?|sprays?|"
    r"lotions?|powders?|kits?|soaps?|shampoos?|expectorants?)\s*$",
    re.IGNORECASE,
)
for _i, _it in enumerate(_ITEMS):
    _lname = _norm(_it[0])
    _INDEX.setdefault(_lname, ("b", _i))
    _short = _FORM_SUFFIX.sub("", _lname).strip()
    if _short and _short != _lname:
        _INDEX.setdefault(_short, ("b", _i))

_TERMS = list(_INDEX.keys())

# 3-char prefix buckets: fuzzy-searching all 450k+ terms per query takes seconds,
# so the bulk fallback only scans terms sharing the query's first 3 letters
# (handwriting errors are rarely in the first letters of a name).
_PREFIX3: dict[str, list[str]] = defaultdict(list)
for _t in _TERMS:
    _PREFIX3[_t[:3]].append(_t)

# Sorted name table for prefix suggestions (autocomplete): normalized -> display.
_NAMES: list[tuple[str, str]] = sorted(
    {(_norm(e["brand"]), e["brand"]) for e in BRANDS} |
    {(_norm(it[0]), it[0]) for it in _ITEMS}
)
_NAME_KEYS = [n for n, _ in _NAMES]

MATCH_THRESHOLD = 72   # curated entries (hand-checked aliases, low junk risk)
BULK_THRESHOLD = 85    # bulk entries (246k names — demand near-certainty)

# Dosage-form prefixes doctors write before names: "Tab Dolo", "Cap. Omez", "Syp Ascoril"
_FORM_PREFIX = re.compile(r"^(tab|tablet|cap|capsule|syp|syrup|inj|injection|oint|cream|drops?|t|c)\.?\s+", re.IGNORECASE)


def brand_names() -> list[str]:
    """Curated brands only — used to prime the vision prompt (keep it small)."""
    return [e["brand"] for e in BRANDS]


def _bulk_entry(i: int) -> dict:
    name, salt_str, keys, pack, price, sig = _ITEMS[i]
    _, cheap_name, cheap_price, _count = _SIGS[sig]
    return {
        "brand": name,
        "salt": salt_str,
        "salt_keys": keys,
        "category": "Medicine",
        "pack": pack,
        "brand_price": price,
        "generic": {"name": cheap_name, "price": cheap_price},
        "_sig": sig,
    }


def _resolve(ref: tuple) -> dict:
    kind, val = ref
    return val if kind == "c" else _bulk_entry(val)


def match_one(name: str) -> tuple[dict | None, int]:
    """Return (entry, score 0-100) for the best fuzzy match, or (None, score).

    Tiered: exact hit -> fuzzy over ~1.5k curated terms (fast, forgiving) ->
    fuzzy over the query's 3-char prefix bucket of the 450k bulk terms
    (strict threshold, since junk queries will always find *something* there).
    """
    query = _norm(_FORM_PREFIX.sub("", name.strip()))
    if not query:
        return None, 0
    if query in _INDEX:
        return _resolve(_INDEX[query]), 100

    cur = process.extractOne(query, _CUR_TERMS, scorer=fuzz.WRatio,
                             score_cutoff=MATCH_THRESHOLD)
    cur_ref, cur_score = (_INDEX[cur[0]], int(cur[1])) if cur else (None, 0)
    if cur_score >= 95:
        return _resolve(cur_ref), cur_score

    bulk_ref, bulk_score = None, 0
    if len(query) >= 3:
        bucket = _PREFIX3.get(query[:3])
        if bucket:
            res = process.extractOne(query, bucket, scorer=fuzz.WRatio,
                                     score_cutoff=BULK_THRESHOLD)
            if res:
                bulk_ref, bulk_score = _INDEX[res[0]], int(res[1])

    # Prefer the bulk hit on ties: it usually carries the exact strength
    # ("Calpol 650") where the curated hit is a sibling ("Calpol 500").
    if bulk_ref and bulk_score >= cur_score:
        return _resolve(bulk_ref), bulk_score
    if cur_ref:
        return _resolve(cur_ref), cur_score
    return None, max(cur_score, bulk_score)


def match_best(raw_text: str, normalized_name: str) -> tuple[dict | None, int]:
    """Match both what was literally read and the model's interpretation, keep the winner.

    Local vision models often transcribe the name correctly but 'normalize' it into
    nonsense — and occasionally the reverse — so neither string alone is reliable.
    """
    candidates = {raw_text or "", normalized_name or ""}
    best_entry, best_score = None, 0
    for cand in candidates:
        if not cand.strip():
            continue
        entry, score = match_one(cand)
        if entry and score > best_score:
            best_entry, best_score = entry, score
    return best_entry, best_score


def alternatives(entry: dict, limit: int = 5) -> list[dict]:
    """Cheapest other brands with the exact same salt composition & strength."""
    sig = entry.get("_sig")
    if sig is None:
        return []
    brand_lower = entry["brand"].lower()
    seen = {brand_lower}
    alts = []
    for i in sorted(_SIG_MEMBERS.get(sig, []), key=lambda i: _ITEMS[i][4]):
        name, _salt, _keys, pack, price, _sig = _ITEMS[i]
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        alts.append({"brand": name, "price": price, "pack": pack})
        if len(alts) >= limit:
            break
    return alts


def same_salt_count(entry: dict) -> int:
    sig = entry.get("_sig")
    return _SIGS[sig][3] if sig is not None else 0


def suggest(q: str, limit: int = 8) -> list[dict]:
    """Prefix autocomplete over all ~246k names. Fast: binary search on a sorted list."""
    q = _norm(q)
    if not q:
        return []
    out = []
    pos = bisect.bisect_left(_NAME_KEYS, q)
    while pos < len(_NAME_KEYS) and len(out) < limit:
        key = _NAME_KEYS[pos]
        if not key.startswith(q):
            break
        ref = _INDEX.get(key)
        if ref:
            e = _resolve(ref)
            out.append({
                "name": e["brand"],
                "salt": e["salt"],
                "price": e["brand_price"],
                "pack": e["pack"],
            })
        pos += 1
    return out


def _pair_warnings(a: dict, b: dict, seen: set) -> list[dict]:
    """All warnings for one pair of medicines (duplicate ingredient + rule table)."""
    warnings = []
    salts_a = {s.lower() for s in a["salt_keys"]}
    salts_b = {s.lower() for s in b["salt_keys"]}
    overlap = salts_a & salts_b - {"multivitamin", "b-complex"}
    for salt in overlap:
        key = ("dup", salt, a["brand"], b["brand"])
        if key not in seen:
            seen.add(key)
            warnings.append({
                "severity": "moderate",
                "between": [a["brand"], b["brand"]],
                "effect": f"Both contain {salt.title()} — taking them together risks an accidental overdose of that ingredient.",
                "advice": "Do not take both unless the doctor has confirmed the total dose is intended.",
            })
    for rule in _INTERACTIONS:
        r1, r2 = (s.lower() for s in rule["salts"])
        if (r1 in salts_a and r2 in salts_b) or (r1 in salts_b and r2 in salts_a):
            key = (r1, r2, a["brand"], b["brand"])
            if key not in seen:
                seen.add(key)
                warnings.append({
                    "severity": rule["severity"],
                    "between": [a["brand"], b["brand"]],
                    "effect": rule["effect"],
                    "advice": rule["advice"],
                })
    return warnings


def check_interactions(entries: list[dict]) -> list[dict]:
    """Check every pair of matched medicines against the interaction table."""
    warnings = []
    seen = set()
    for a, b in combinations(entries, 2):
        warnings.extend(_pair_warnings(a, b, seen))
    warnings.sort(key=lambda w: 0 if w["severity"] == "major" else 1)
    return warnings


def cross_interactions(scanned: list[dict], saved: list[dict]) -> list[dict]:
    """Interactions between newly scanned medicines and the user's saved medicines."""
    warnings = []
    seen = set()
    for a in scanned:
        for b in saved:
            if a["brand"].lower() == b["brand"].lower():
                continue
            for w in _pair_warnings(a, b, seen):
                w["saved_med"] = b["brand"]
                warnings.append(w)
    warnings.sort(key=lambda w: 0 if w["severity"] == "major" else 1)
    return warnings


# Optional per-salt consumer info (uses / common side effects) for detail views.
_SALT_INFO_PATH = DATA_DIR / "salt_info.json"
_SALT_INFO: dict[str, dict] = {}
if _SALT_INFO_PATH.exists():
    with open(_SALT_INFO_PATH, encoding="utf-8") as f:
        _SALT_INFO = json.load(f)


def medicine_detail(name: str, alt_limit: int = 30) -> dict | None:
    """Full detail for one medicine: entry + all same-salt brands + salt info."""
    entry, score = match_one(name)
    if entry is None:
        return None
    info = [dict(_SALT_INFO[k], salt=k.title()) for k in entry["salt_keys"] if k in _SALT_INFO]
    return {
        "brand": entry["brand"],
        "salt": entry["salt"],
        "category": entry["category"],
        "pack": entry["pack"],
        "brand_price": entry["brand_price"],
        "generic_name": entry["generic"]["name"],
        "generic_price": entry["generic"]["price"],
        "salt_keys": entry["salt_keys"],
        "same_salt_brands": same_salt_count(entry),
        "alternatives": alternatives(entry, alt_limit),
        "salt_info": info,
        "match_score": score,
    }


def lookup(extracted: list[dict]) -> dict:
    """Build the full response for a list of extracted medicines.

    Each item: {"raw_text": str, "normalized_name": str, "dosage": str|None,
                "frequency": str|None, "confidence": str}
    """
    results = []
    matched_entries = []
    total_brand = 0.0
    total_generic = 0.0

    for med in extracted:
        name = med.get("normalized_name") or med.get("raw_text", "")
        entry, score = match_best(med.get("raw_text", ""), name)
        item = {
            "raw_text": med.get("raw_text", name),
            "query": name,
            "dosage": med.get("dosage"),
            "frequency": med.get("frequency"),
            "ocr_confidence": med.get("confidence", "medium"),
            "matched": entry is not None,
            "match_score": score,
        }
        if entry:
            saving = entry["brand_price"] - entry["generic"]["price"]
            pct = round(saving / entry["brand_price"] * 100) if entry["brand_price"] else 0
            item.update({
                "brand": entry["brand"],
                "salt": entry["salt"],
                "category": entry["category"],
                "pack": entry["pack"],
                "brand_price": entry["brand_price"],
                "generic_name": entry["generic"]["name"],
                "generic_price": entry["generic"]["price"],
                "saving": round(saving, 2),
                "saving_pct": pct,
                "alternatives": alternatives(entry),
                "same_salt_brands": same_salt_count(entry),
            })
            matched_entries.append(entry)
            total_brand += entry["brand_price"]
            total_generic += entry["generic"]["price"]
        results.append(item)

    return {
        "medicines": results,
        "interactions": check_interactions(matched_entries),
        "totals": {
            "brand": round(total_brand, 2),
            "generic": round(total_generic, 2),
            "saving": round(total_brand - total_generic, 2),
            "saving_pct": round((total_brand - total_generic) / total_brand * 100) if total_brand else 0,
        },
        "disclaimer": DISCLAIMER,
    }
