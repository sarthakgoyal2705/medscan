"""Shared salt-composition parsing.

Used by both data/import_bulk.py (build time) and app/matcher.py (runtime) so
that curated entries and bulk-dataset entries produce identical salt keys and
signatures — signatures are what group "same salt, different brand" products.
"""

import re

# Indian datasets / prescriptions use British or variant spellings; interaction
# rules are keyed on the canonical forms on the right.
SPELLING = {
    "amoxycillin": "amoxicillin",
    "acetaminophen": "paracetamol",
    "cetrizine": "cetirizine",
    "levocetrizine": "levocetirizine",
    "albuterol": "salbutamol",
    "glimepride": "glimepiride",
    "adrenaline": "epinephrine",
    "frusemide": "furosemide",
    "sodium valproate": "valproate",
    "valproic acid": "valproate",
    "isosorbide-5-mononitrate": "isosorbide mononitrate",
    "glyceryl trinitrate": "nitroglycerin",
    "vitamin d3": "vitamin d3",
    "cholecalciferol": "vitamin d3",
    "ferrous ascorbate": "iron",
    "ferrous fumarate": "iron",
    "ferrous sulphate": "iron",
    "ferrous sulfate": "iron",
    "carbonyl iron": "iron",
    "thyroxine": "levothyroxine",
    "dicyclomine hcl": "dicyclomine",
    "metformin hcl": "metformin",
}

# "Paracetamol (650mg)" -> name, strength.  Strength part optional.
_COMP_RE = re.compile(r"^(.*?)\s*\(([^)]*)\)\s*$")
_WS = re.compile(r"\s+")


def parse_component(text: str) -> tuple[str, str] | None:
    """'Amoxycillin  (500mg)' -> ('amoxicillin', '500mg'); None if empty."""
    text = text.strip().strip(",").strip()
    if not text:
        return None
    m = _COMP_RE.match(text)
    if m and re.search(r"\d", m.group(2)):
        # "Aspirin (75mg)" — parenthesized strength
        name, strength = m.group(1), m.group(2)
    else:
        if m:
            # parenthesized annotation, not a strength: "Aspirin 75mg (low dose)"
            text = m.group(1).strip()
        # curated style: "Paracetamol 650mg" (strength glued on the end)
        m2 = re.match(r"^(.*?)\s+([\d.]+\s*(?:mg|mcg|g|iu|ml|%)[\w./%]*)$", text, re.IGNORECASE)
        if m2:
            name, strength = m2.group(1), m2.group(2)
        else:
            name, strength = text, ""
    key = _WS.sub(" ", name).strip().lower()
    key = SPELLING.get(key, key)
    return key, _WS.sub("", strength).lower()


def parse_salt_string(salt: str) -> list[tuple[str, str]]:
    """Split a full composition string on '+' into (key, strength) pairs."""
    parts = []
    for chunk in salt.split("+"):
        comp = parse_component(chunk)
        if comp:
            parts.append(comp)
    return parts


def signature(components: list[tuple[str, str]]) -> str:
    """Canonical grouping key: same ingredients at same strengths."""
    return "|".join(f"{k}@{s}" for k, s in sorted(components))
