"""MedScan — prescription digitizer + generic medicine finder.

Run:  uvicorn app.main:app --reload
"""

from pathlib import Path

from fastapi import Cookie, FastAPI, File, HTTPException, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import auth, extraction, matcher, peddose, stores

app = FastAPI(title="MedScan", version="0.1.0")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MAX_IMAGE_BYTES = 20 * 1024 * 1024


class LookupRequest(BaseModel):
    names: list[str]


class SignupRequest(BaseModel):
    name: str
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


SESSION_COOKIE = "medscan_session"


def _set_session(response: Response, token: str) -> None:
    response.set_cookie(SESSION_COOKIE, token, max_age=auth.SESSION_DAYS * 86400,
                        httponly=True, samesite="lax")


@app.post("/api/auth/signup")
def api_signup(req: SignupRequest, response: Response):
    try:
        token = auth.signup(req.name, req.email, req.password)
    except auth.AuthError as exc:
        raise HTTPException(exc.status, str(exc))
    _set_session(response, token)
    return {"user": auth.user_for_token(token)}


@app.post("/api/auth/login")
def api_login(req: LoginRequest, response: Response):
    try:
        token = auth.login(req.email, req.password)
    except auth.AuthError as exc:
        raise HTTPException(exc.status, str(exc))
    _set_session(response, token)
    return {"user": auth.user_for_token(token)}


@app.post("/api/auth/logout")
def api_logout(response: Response, medscan_session: str | None = Cookie(default=None)):
    auth.logout(medscan_session)
    response.delete_cookie(SESSION_COOKIE)
    return {"ok": True}


@app.get("/api/auth/me")
def api_me(medscan_session: str | None = Cookie(default=None)):
    user = auth.user_for_token(medscan_session)
    out = {"user": user}
    if user:
        out["total_saving"] = auth.total_saving(user["id"])
    return out


def _finish_result(result: dict, source: str, token: str | None) -> dict:
    """Attach saved-medicine cross-checks and persist to history for logged-in users."""
    user = auth.user_for_token(token)
    if not user:
        result["saved_interactions"] = []
        return result
    saved = auth.list_meds(user["id"])
    scanned = []
    for m in result["medicines"]:
        if not m.get("matched"):
            continue
        entry, _ = matcher.match_one(m["brand"])
        if entry:
            scanned.append({"brand": entry["brand"], "salt_keys": entry["salt_keys"]})
    result["saved_interactions"] = matcher.cross_interactions(scanned, saved)
    auth.save_scan(user["id"], source, result)
    return result


# ------------------------------------------------------------- history ----

@app.get("/api/history")
def api_history(medscan_session: str | None = Cookie(default=None)):
    user = auth.user_for_token(medscan_session)
    if not user:
        raise HTTPException(401, "Sign in to see your scan history.")
    return {"scans": auth.list_scans(user["id"]),
            "total_saving": auth.total_saving(user["id"])}


@app.get("/api/history/{scan_id}")
def api_history_item(scan_id: int, medscan_session: str | None = Cookie(default=None)):
    user = auth.user_for_token(medscan_session)
    if not user:
        raise HTTPException(401, "Sign in to see your scan history.")
    result = auth.get_scan(user["id"], scan_id)
    if result is None:
        raise HTTPException(404, "Scan not found.")
    return result


@app.delete("/api/history/{scan_id}")
def api_history_delete(scan_id: int, medscan_session: str | None = Cookie(default=None)):
    user = auth.user_for_token(medscan_session)
    if not user:
        raise HTTPException(401, "Sign in first.")
    auth.delete_scan(user["id"], scan_id)
    return {"ok": True}


# --------------------------------------------------------- my medicines ----

class AddMedRequest(BaseModel):
    name: str


@app.get("/api/mymeds")
def api_mymeds(medscan_session: str | None = Cookie(default=None)):
    user = auth.user_for_token(medscan_session)
    if not user:
        raise HTTPException(401, "Sign in to manage your medicines.")
    meds = auth.list_meds(user["id"])
    return {"meds": meds, "interactions": matcher.check_interactions(meds)}


@app.post("/api/mymeds")
def api_mymeds_add(req: AddMedRequest, medscan_session: str | None = Cookie(default=None)):
    user = auth.user_for_token(medscan_session)
    if not user:
        raise HTTPException(401, "Sign in to save medicines.")
    entry, _score = matcher.match_one(req.name)
    if entry is None:
        raise HTTPException(404, f"'{req.name}' not found in the medicine database.")
    auth.add_med(user["id"], entry["brand"], entry["salt"], entry["salt_keys"])
    return {"ok": True, "brand": entry["brand"]}


@app.delete("/api/mymeds/{med_id}")
def api_mymeds_delete(med_id: int, medscan_session: str | None = Cookie(default=None)):
    user = auth.user_for_token(medscan_session)
    if not user:
        raise HTTPException(401, "Sign in first.")
    auth.delete_med(user["id"], med_id)
    return {"ok": True}


# -------------------------------------------------------------- stores ----

@app.get("/api/stores")
def api_stores(lat: float | None = None, lng: float | None = None,
               pincode: str | None = None, limit: int = 8):
    if not stores.available():
        raise HTTPException(503, "Store data not available on this server.")
    if pincode:
        ll = stores.resolve_pincode(pincode)
        if ll is None:
            raise HTTPException(404, f"No Jan Aushadhi kendra data for pincode {pincode}. Try a nearby pincode.")
        lat, lng = ll
    if lat is None or lng is None:
        raise HTTPException(400, "Provide lat & lng, or a pincode.")
    return {"stores": stores.nearest(lat, lng, min(max(limit, 1), 25))}


# ------------------------------------------------------ paediatric dose ----

@app.get("/api/peddose/list")
def api_peddose_list():
    return {"medicines": peddose.supported(), "disclaimer": peddose.DISCLAIMER}


@app.get("/api/peddose")
def api_peddose(id: str = "", medicine: str = "", weight_kg: float = 0):
    rule_id = id.strip()
    if not rule_id and medicine.strip():
        entry, _ = matcher.match_one(medicine.strip())
        rule = peddose.rule_for_salts(entry["salt_keys"]) if entry else None
        if rule is None:
            raise HTTPException(404, f"No paediatric dosing data for '{medicine}'.")
        rule_id = rule["id"]
    if not rule_id:
        raise HTTPException(400, "Provide a medicine id or name.")
    try:
        return peddose.compute(rule_id, weight_kg)
    except peddose.DoseError as exc:
        raise HTTPException(400, str(exc))


# -------------------------------------------------------------- feedback ----

class FeedbackRequest(BaseModel):
    raw_text: str
    matched_brand: str
    verdict: str  # "correct" | "wrong"
    correction: str | None = None


@app.post("/api/feedback")
def api_feedback(req: FeedbackRequest, medscan_session: str | None = Cookie(default=None)):
    if req.verdict not in ("correct", "wrong"):
        raise HTTPException(400, "verdict must be 'correct' or 'wrong'.")
    user = auth.user_for_token(medscan_session)
    auth.save_feedback(user["id"] if user else None, req.raw_text,
                       req.matched_brand, req.verdict, req.correction)
    return {"ok": True}


@app.get("/api/feedback/stats")
def api_feedback_stats():
    return auth.feedback_stats()


# ------------------------------------------------------ medicine detail ----

@app.get("/api/medicine")
def api_medicine(name: str = ""):
    if not name.strip():
        raise HTTPException(400, "Provide a medicine name.")
    detail = matcher.medicine_detail(name.strip())
    if detail is None:
        raise HTTPException(404, f"'{name}' not found in the medicine database.")
    return detail


@app.get("/api/health")
def health():
    return {"status": "ok", **extraction.backend_status()}


@app.post("/api/scan")
async def scan(image: UploadFile = File(...),
               medscan_session: str | None = Cookie(default=None)):
    """Photo of a prescription -> extracted medicines + generics + interactions."""
    if image.content_type not in ALLOWED_TYPES:
        raise HTTPException(415, f"Unsupported image type {image.content_type}. Use JPEG/PNG/WebP.")
    data = await image.read()
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "Image too large (max 20 MB). Please downscale and retry.")

    try:
        # local-model inference takes minutes — keep the event loop free
        extracted = await run_in_threadpool(extraction.extract_from_image, data, image.content_type)
    except extraction.NotConfiguredError as exc:
        raise HTTPException(503, str(exc))
    except extraction.ExtractionRefusedError:
        raise HTTPException(422, "The image could not be processed. Try a clearer photo of the prescription.")

    if not extracted.get("is_prescription"):
        raise HTTPException(422, "This doesn't look like a prescription. Try a clearer photo.")

    result = matcher.lookup(extracted["medicines"])
    result["notes"] = extracted.get("notes", "")
    return _finish_result(result, "scan", medscan_session)


@app.post("/api/lookup")
def lookup_by_name(req: LookupRequest,
                   medscan_session: str | None = Cookie(default=None)):
    """Typed medicine names -> generics + interactions (no LLM call needed)."""
    names = [n for n in (s.strip() for s in req.names) if n]
    if not names:
        raise HTTPException(400, "Provide at least one medicine name.")
    extracted = [{"raw_text": n, "normalized_name": n, "dosage": None,
                  "frequency": None, "confidence": "high"} for n in names]
    result = matcher.lookup(extracted)
    result["notes"] = ""
    return _finish_result(result, "lookup", medscan_session)


@app.get("/api/suggest")
def suggest_names(q: str = "", limit: int = 8):
    """Prefix autocomplete over the full drug index (fires from the 1st letter)."""
    return {"suggestions": matcher.suggest(q, min(max(limit, 1), 20))}


@app.get("/api/demo")
def demo():
    """Canned scan result so the full flow can be seen without an API key."""
    extracted = extraction.mock_extraction()
    result = matcher.lookup(extracted["medicines"])
    result["notes"] = extracted["notes"]
    return result


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
