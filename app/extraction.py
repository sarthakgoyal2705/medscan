"""Extract medicine names from a prescription photo.

Three interchangeable vision backends (auto-picked, force with MEDSCAN_BACKEND):

  - "claude"  — when ANTHROPIC_API_KEY is set. Best on messy handwriting.
  - "gemini"  — when GEMINI_API_KEY is set (free tier at aistudio.google.com,
    no card needed). Good handwriting reading; the deploy-for-free option.
  - "ollama"  (fallback) — free, local. Uses Ollama's structured-output mode.
    Model set by OLLAMA_MODEL (default: llava).

Either way, a fuzzy-match layer in matcher.py is the second correction pass,
so a shaky read like "Augmentn" still lands on Augmentin 625.
"""

import base64
import json
import os

import requests

from . import matcher

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llava")
CLAUDE_MODEL = "claude-opus-4-8"
# "gemini-flash-latest" is Google's rolling alias — never retires for new accounts
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models"

# Structured-output schema: guarantees parseable JSON from either backend.
EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "is_prescription": {
            "type": "boolean",
            "description": "True if the image appears to be a medical prescription or medicine list.",
        },
        "medicines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "raw_text": {
                        "type": "string",
                        "description": "The medicine name exactly as it visually appears (best-effort transcription of the handwriting).",
                    },
                    "normalized_name": {
                        "type": "string",
                        "description": "Your best identification of the intended medicine, corrected for handwriting ambiguity.",
                    },
                    "dosage": {
                        "type": ["string", "null"],
                        "description": "Strength/dose if written, e.g. '650mg', '1 tab'.",
                    },
                    "frequency": {
                        "type": ["string", "null"],
                        "description": "Frequency/duration if written, decoded from shorthand: 1-0-1 means morning & night, BD twice daily, TDS thrice daily, OD once daily, HS at bedtime, SOS as needed.",
                    },
                    "confidence": {
                        "type": "string",
                        "enum": ["high", "medium", "low"],
                        "description": "How confident you are in the identification.",
                    },
                },
                "required": ["raw_text", "normalized_name", "dosage", "frequency", "confidence"],
                "additionalProperties": False,
            },
        },
        "notes": {
            "type": "string",
            "description": "Anything else legible and relevant (diagnosis, advice). Empty string if none.",
        },
    },
    "required": ["is_prescription", "medicines", "notes"],
    "additionalProperties": False,
}

CLAUDE_SYSTEM_PROMPT = """You are an expert at reading Indian doctors' handwritten prescriptions.
Prescriptions commonly mix brand names, dosage shorthand (1-0-1, BD, TDS, OD, HS, SOS),
Rx symbols, and abbreviations. Handwriting is often barely legible — use dosage strength,
drug-class context, and common prescribing patterns to disambiguate.

Known formulary (prefer these names in normalized_name when the handwriting plausibly
matches one — but if the medicine is clearly something not on this list, still report it
with your best reading):
{formulary}

Rules:
- Extract every distinct medicine. Ignore doctor/patient/clinic details.
- Never invent medicines that are not visibly written.
- If a name is truly unreadable, still emit it with confidence "low" and your best guess."""

# Local vision models are weaker instruction-followers: keep this prompt short
# and do NOT inject the ~250-name formulary (it overwhelms small models and
# eats context). The rapidfuzz layer handles name correction instead.
OLLAMA_PROMPT = """This image is a medical prescription (possibly handwritten, possibly Indian).
List every medicine written on it. For each: the text as written (raw_text), your best
guess of the intended medicine name (normalized_name), dosage strength if visible,
frequency if visible (decode shorthand: 1-0-1 = morning & night, BD = twice daily,
TDS = thrice daily, OD = once daily, HS = bedtime, SOS = as needed), and your
confidence (high/medium/low). Only report what is actually written — do not invent
medicines. If the image is not a prescription or medicine list, set is_prescription
to false with an empty medicines array."""


class NotConfiguredError(Exception):
    """No usable vision backend (Ollama not running / model not pulled / no API key)."""


class ExtractionRefusedError(Exception):
    """The model declined to process the image."""


class UpstreamBusyError(Exception):
    """The hosted vision API is rate-limited / out of free quota right now."""


def backend() -> str:
    forced = os.environ.get("MEDSCAN_BACKEND", "").lower()
    if forced in ("ollama", "claude", "gemini"):
        return forced
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return "claude"
    if os.environ.get("GEMINI_API_KEY"):
        return "gemini"
    return "ollama"


def backend_status() -> dict:
    """For /api/health: which backend would be used and is it actually usable."""
    b = backend()
    if b == "claude":
        return {"backend": "claude", "model": CLAUDE_MODEL, "ready": True}
    if b == "gemini":
        ready = bool(os.environ.get("GEMINI_API_KEY"))
        return {"backend": "gemini", "model": GEMINI_MODEL, "ready": ready,
                "detail": None if ready else "GEMINI_API_KEY not set — get a free key at aistudio.google.com"}
    try:
        tags = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3).json()
        names = [m["name"] for m in tags.get("models", [])]
        ready = any(n == OLLAMA_MODEL or n.startswith(OLLAMA_MODEL + ":") for n in names)
        detail = None if ready else f"model '{OLLAMA_MODEL}' not pulled — run: ollama pull {OLLAMA_MODEL}"
    except requests.ConnectionError:
        ready, detail = False, "Ollama is not running — install it from ollama.com and start it"
    except requests.RequestException as exc:
        ready, detail = False, f"Ollama check failed: {exc}"
    return {"backend": "ollama", "model": OLLAMA_MODEL, "ready": ready, "detail": detail}


def has_credentials() -> bool:
    return backend_status()["ready"]


def extract_from_image(image_bytes: bytes, media_type: str) -> dict:
    b = backend()
    if b == "claude":
        return _extract_claude(image_bytes, media_type)
    if b == "gemini":
        return _extract_gemini(image_bytes, media_type)
    return _extract_ollama(image_bytes)


# ---------------------------------------------------------------- Gemini ----

def _gemini_schema() -> dict:
    """EXTRACTION_SCHEMA translated to Gemini's OpenAPI-style response schema
    (Gemini uses `nullable` instead of union types)."""
    return {
        "type": "OBJECT",
        "properties": {
            "is_prescription": {"type": "BOOLEAN"},
            "medicines": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "raw_text": {"type": "STRING"},
                        "normalized_name": {"type": "STRING"},
                        "dosage": {"type": "STRING", "nullable": True},
                        "frequency": {"type": "STRING", "nullable": True},
                        "confidence": {"type": "STRING", "enum": ["high", "medium", "low"]},
                    },
                    "required": ["raw_text", "normalized_name", "confidence"],
                },
            },
            "notes": {"type": "STRING"},
        },
        "required": ["is_prescription", "medicines", "notes"],
    }


def _extract_gemini(image_bytes: bytes, media_type: str) -> dict:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise NotConfiguredError(
            "GEMINI_API_KEY not set. Create a free key at https://aistudio.google.com "
            "(no card needed) and set it in the environment.")

    system = CLAUDE_SYSTEM_PROMPT.format(formulary=", ".join(matcher.brand_names()))
    payload = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{
            "role": "user",
            "parts": [
                {"inline_data": {"mime_type": media_type,
                                 "data": base64.b64encode(image_bytes).decode()}},
                {"text": "Read this prescription and extract all medicines."},
            ],
        }],
        "generationConfig": {
            "response_mime_type": "application/json",
            "response_schema": _gemini_schema(),
            "temperature": 0,
        },
    }
    resp = requests.post(
        f"{GEMINI_URL}/{GEMINI_MODEL}:generateContent",
        params={"key": key}, json=payload, timeout=120)

    if resp.status_code in (400, 401, 403):
        raise NotConfiguredError(f"Gemini API rejected the key/request (HTTP {resp.status_code}).")
    if resp.status_code == 429:
        raise UpstreamBusyError(
            "The free daily scan quota is exhausted or rate-limited — please try again later.")
    resp.raise_for_status()

    body = resp.json()
    try:
        candidate = body["candidates"][0]
        text = "".join(p.get("text", "") for p in candidate["content"]["parts"])
        result = json.loads(text)
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        reason = body.get("candidates", [{}])[0].get("finishReason", "unknown")
        raise ExtractionRefusedError(f"Gemini returned no usable output (reason: {reason}).") from exc

    # schema marks dosage/frequency optional — normalise to the app's shape
    for m in result.get("medicines", []):
        m.setdefault("dosage", None)
        m.setdefault("frequency", None)
    return result


# ---------------------------------------------------------------- Ollama ----

def _extract_ollama(image_bytes: bytes) -> dict:
    payload = {
        "model": OLLAMA_MODEL,
        "stream": False,
        "format": EXTRACTION_SCHEMA,  # grammar-constrained decoding -> valid JSON
        "options": {"temperature": 0, "num_ctx": 4096},
        "messages": [
            {
                "role": "user",
                "content": OLLAMA_PROMPT,
                "images": [base64.b64encode(image_bytes).decode()],
            }
        ],
    }
    try:
        # Local CPU inference is slow; give it plenty of time.
        resp = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=600)
    except requests.ConnectionError as exc:
        raise NotConfiguredError(
            "Ollama is not running. Install it from https://ollama.com, then run: "
            f"ollama pull {OLLAMA_MODEL}"
        ) from exc

    if resp.status_code == 404:
        raise NotConfiguredError(
            f"Ollama model '{OLLAMA_MODEL}' is not downloaded. Run: ollama pull {OLLAMA_MODEL}"
        )
    resp.raise_for_status()

    content = resp.json()["message"]["content"]
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise ExtractionRefusedError(f"Model returned unparseable output: {content[:200]}") from exc


# ---------------------------------------------------------------- Claude ----

def _extract_claude(image_bytes: bytes, media_type: str) -> dict:
    import anthropic

    system = CLAUDE_SYSTEM_PROMPT.format(formulary=", ".join(matcher.brand_names()))

    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=4096,
            thinking={"type": "adaptive"},
            system=system,
            output_config={"format": {"type": "json_schema", "schema": EXTRACTION_SCHEMA}},
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": base64.b64encode(image_bytes).decode(),
                            },
                        },
                        {
                            "type": "text",
                            "text": "Read this prescription and extract all medicines.",
                        },
                    ],
                }
            ],
        )
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError, TypeError) as exc:
        # TypeError = SDK could not resolve any credentials at construction time
        raise NotConfiguredError(str(exc)) from exc

    if response.stop_reason == "refusal":
        raise ExtractionRefusedError("The model declined to process this image.")

    text = next(block.text for block in response.content if block.type == "text")
    return json.loads(text)


# ------------------------------------------------------------------ Demo ----

def mock_extraction() -> dict:
    """Canned result so the app can be demoed without any backend."""
    return {
        "is_prescription": True,
        "medicines": [
            {"raw_text": "T. Dolo 650", "normalized_name": "Dolo 650", "dosage": "650mg",
             "frequency": "1-1-1 x 3 days (thrice daily)", "confidence": "high"},
            {"raw_text": "Cap Augmentn 625", "normalized_name": "Augmentin 625 Duo", "dosage": "625mg",
             "frequency": "BD x 5 days (twice daily)", "confidence": "medium"},
            {"raw_text": "T. Pan 40", "normalized_name": "Pan 40", "dosage": "40mg",
             "frequency": "OD before breakfast", "confidence": "high"},
            {"raw_text": "Montair LC", "normalized_name": "Montair-LC", "dosage": None,
             "frequency": "HS (at bedtime)", "confidence": "medium"},
        ],
        "notes": "Demo result — the scan tab uses your local Ollama model for real prescriptions.",
    }
