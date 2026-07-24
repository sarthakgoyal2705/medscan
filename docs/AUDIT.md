# Phase 0 — Repo Audit

Written before any pipeline code. Records what the repo actually is today, and
where this data-engineering spec must bend to fit reality.

## 1. Directory layout & where the logic lives

```
medscan/
├── app/                     # the live FastAPI application (Render-deployed)
│   ├── main.py              # HTTP layer: all /api/* routes, rate limiting, cookies
│   ├── extraction.py        # Vision-LLM call (Ollama / Claude / Gemini backends)
│   ├── matcher.py           # RapidFuzz matching over the 246K catalogue + interactions
│   ├── salts.py             # salt-composition parser → salt signatures
│   ├── auth.py              # SQLite: accounts, sessions, scan history, my-meds, feedback
│   ├── stores.py            # Jan Aushadhi store locator (haversine)
│   └── peddose.py           # paediatric dose calculator
├── data/                    # datasets (mostly static JSON) + users.db
├── static/index.html        # single-file frontend
├── Dockerfile               # Render production image (web only)
├── render.yaml              # Render blueprint
└── requirements.txt         # 6 web deps only
```

The extraction and matching logic is **already reasonably factored** into
`extraction.py` and `matcher.py` — it is *not* tangled inside request handlers,
contrary to the spec's assumption. `main.py` handlers are thin and already call
`extraction.extract_from_image(...)` and `matcher.lookup(...)`. Phase 1 is
therefore **formalising** these into typed, lineage-carrying stage functions,
not untangling a mess.

## 2. End-to-end flow (today)

```
POST /api/scan (image upload)
  → main.scan()  [rate-limit, size/type checks]
  → run_in_threadpool(extraction.extract_from_image(bytes, mime))
        → backend(): Gemini in prod (GEMINI_API_KEY), Ollama locally, Claude if key
        → returns dict: {is_prescription, medicines:[{raw_text, normalized_name,
                          dosage, frequency, confidence}], notes}
  → matcher.lookup(medicines)
        → per medicine: match_best() → RapidFuzz over ~459K indexed terms
          (curated 268 + 246K bulk names, tiered: exact → curated → bulk-prefix-bucket)
        → attaches salt, generic alternative (cheapest same-salt-signature), prices,
          savings, interaction warnings
  → _finish_result(): for logged-in users, cross-checks saved meds + saves to history
  → JSON back to the browser
```

The **live medicine lookup reads from in-memory JSON**, not SQLite (see §3).

## 3. Storage — important correction to the spec

The spec repeatedly refers to "the 246K-record product table" and "what gets
written to SQLite." Reality is split:

| Data | Where it actually lives | Notes |
|---|---|---|
| **246,064-product catalogue** | `data/bulk.json` (29 MB), loaded **into memory** by `matcher.py` at startup | Static; **not** in SQLite. Item shape: `[name, salt_str, [salt_keys], pack, price, sig_idx]`. 10,932 salt signatures in `sigs`. |
| 268 curated brands | `data/medicines.json` | in-memory |
| interactions / salt info / ped doses / stores | `data/*.json` | in-memory |
| **User/serving data** | `data/users.db` (SQLite, 36 KB) | tables: `users`, `sessions`, `scans`, `feedback`, `user_meds` |

`data/users.db` SQLite schema (from `auth.py`):
- `users(id, name, email UNIQUE, pw_hash, pw_salt, created_at)`
- `sessions(token_hash, user_id, expires_at)`
- `scans(id, user_id, source, result JSON, created_at)`  ← prescription results, per user
- `feedback(id, user_id, raw_text, matched_brand, verdict, correction, created_at)`
- `user_meds(id, user_id, brand, salt, salt_keys, added_at)`

**Implication:** there is no existing "serving product table" the pipeline can
just write into. The catalogue is a read-only JSON asset. So Phase 1 `load.py`
and the "Gold → SQLite" step will create a **new** serving table
(`pipeline_prescriptions` in a separate `data/serving.db`) for *batch-processed
prescription results* — kept distinct from the live medicine-lookup path, which
continues to read `bulk.json` in memory. This satisfies the spec's intent
(Spark-processed results land in a serving store) without rerouting the live app.

## 4. Vision-LLM provider selection & credentials

`extraction.backend()` picks, in order: `MEDSCAN_BACKEND` override → Claude if
`ANTHROPIC_API_KEY` → Gemini if `GEMINI_API_KEY` → Ollama (local default).
Credentials come from **environment variables only** (never in code). Production
(Render) sets `MEDSCAN_BACKEND=gemini` + `GEMINI_API_KEY` secret; model is
`gemini-flash-latest`. Raw model output is already returned as a clean dict —
good, because Bronze wants the **raw** response, so `extract.py` must capture the
provider's untouched JSON *before* our dict-shaping.

## 5. Dependencies, Dockerfile, Render

- `requirements.txt`: **6 lean deps** (fastapi, uvicorn, python-multipart,
  anthropic, rapidfuzz, requests). No pandas, no numpy, no Spark.
- `Dockerfile`: `python:3.12-slim`, non-root, installs `requirements.txt`, runs
  `uvicorn ... --port ${PORT:-7860}`. `MEDSCAN_BACKEND=gemini`,
  `MEDSCAN_SECURE_COOKIES=1` baked in.
- Render: free tier, Singapore, Docker runtime, auto-deploys on push to `main`,
  health check `/api/health`. **Live at https://medscan-mzny.onrender.com.**

## 6. Existing pipeline-stage boundaries

Already present, just not named as such:
- **ingest**: HTTP upload in `main.scan()` (no hashing/lineage today)
- **extract**: `extraction.extract_from_image()`
- **normalize**: partially inside `matcher.lookup()` (name selection) + `salts.py`
- **match**: `matcher.match_best()` / `match_one()`
- **load**: `auth.save_scan()` (writes result JSON to SQLite per user)

---

## 7. Environment reality — what MUST adjust in this spec

Two hard blockers found on this machine, plus consequences:

### 🔴 Blocker A — No Java, and Python is 3.13
- `java`: **not installed**. PySpark needs a JVM.
- Python here is **3.13.5**. PySpark (≤ 4.0) supports Python **≤ 3.12** — 3.13 is
  too new; `pip install pyspark` will run but jobs will fail/behave oddly.

**Resolution (no native Spark on this box):** run **all Spark/Delta work inside
Docker** — Docker *is* installed (v29.6.1, Compose v5.2.0). A pipeline image
(`python:3.11` + JRE + pyspark + delta-spark) runs Spark with its own JVM and a
compatible Python. This also matches Phase 4's intent (Airflow in Docker). Native
`pip install pyspark` on the host is **not** part of the plan.

### 🟢 Docker is available → Airflow (Phase 4) and Spark (Phases 2–3) both viable
via containers. Good.

### 🔴 Keep the Render web image untouched and lean
The spec says the web app must **not** depend on Spark at request time. Concretely
that means:
- **Do not add pyspark/delta/airflow to `requirements.txt`.** That would bloat the
  Render image ~10×, likely break on py3.13/no-Java, and slow deploys.
- Pipeline deps go in a **separate `requirements-pipeline.txt`**, used only by the
  Docker pipeline/Airflow images. `Dockerfile` (Render) stays as-is.
- `/pipeline/health` (Phase 5) reads the metrics table with **stdlib sqlite3 /
  file reads only** — no Spark import in the web process.

### 🟡 Ingestion source for batch
The live path is HTTP upload (one image, synchronous). The batch DAG needs a
source of files: a **landing directory** `data/landing/` where images are dropped
(or re-fed from Bronze). This is a **new** batch ingest path parallel to the live
HTTP one — the same Phase-1 `extract/normalize/match` functions power both, so the
live app keeps working unchanged.

### 🟡 "246K product table" wording
Everywhere the spec says the catalogue is a SQLite table — it's actually
`bulk.json` in memory. Phase 3 Spark matching will load the catalogue **from
`bulk.json`** into a Spark DataFrame and broadcast it. No SQLite catalogue exists
to read.

---

## 8. Proposed adjusted plan (what I'll actually build)

| Phase | As-spec'd | Adjusted for this repo |
|---|---|---|
| 1 | Untangle stages from handlers | **Wrap** existing `extraction`/`matcher` into typed, idempotent stage fns in `medscan_pipeline/` carrying `source_file_hash`, `ingested_at`, `pipeline_run_id`. Handlers delegate. Live app identical. |
| 2 | Delta bronze/silver/gold under `DATA_ROOT` | Same, but **executed inside the Docker pipeline image** (no host Java). Sample data in `data_samples/`. |
| 3 | Spark match, broadcast + blocking, benchmark | Same; catalogue loaded from `bulk.json`. RapidFuzz live path untouched. Benchmark in Docker. |
| 4 | Airflow Compose + DAG | Same (Docker). DAG calls Phase-1 fns; ingest from `data/landing/`. |
| 5 | Validation + `/pipeline/health` | Same; endpoint uses stdlib only, zero Spark in web process. |
| 6 | Azure Databricks | Optional, last, `DATA_ROOT=abfss://…`. |

**Nothing above touches `requirements.txt`, `Dockerfile`, `render.yaml`, or any
`app/*` request path in a way that changes live behaviour.** New code lives under
`medscan_pipeline/`, `airflow/`, `docker/`.

> Note: the spec names the package `medscan/pipeline/`, but the repo's app package
> is `app/` (there is no `medscan/` package). I'll use **`medscan_pipeline/`** as a
> top-level package to avoid colliding with the existing layout. Flag if you'd
> prefer `pipeline/` instead.

---

## ✋ Confirmation gate

Per the spec, I'm stopping here until you confirm. Specifically, please confirm:
1. **Spark/Airflow run in Docker** (not natively) — forced by no-Java + Python 3.13. ✅/❌
2. **`requirements.txt`, `Dockerfile`, `render.yaml` stay untouched**; pipeline deps
   are separate. ✅/❌
3. New batch **serving table is separate** (`data/serving.db`), live medicine lookup
   still reads `bulk.json`. ✅/❌
4. Package name **`medscan_pipeline/`** (vs the spec's `medscan/pipeline/`). ✅/❌
5. Batch **ingest source = `data/landing/`** image drop folder. ✅/❌
