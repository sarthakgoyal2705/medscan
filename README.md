---
title: MedScan
emoji: 💊
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# ℞ MedScan — Prescription Digitizer + Generic Medicine Finder

Photograph a handwritten prescription → AI decodes the scrawl → see each drug's
**salt composition**, a **generic (Jan Aushadhi–style) alternative with prices**,
and **dangerous drug-interaction warnings**.

**100% free to run** — vision AI runs locally via Ollama, no API key or card needed.

## How it works

```
photo ──► vision model (local llava      ──► rapidfuzz correction  ──► formulary lookup
          via Ollama; or Claude if an        (fixes misspellings /     salt · generic price
          ANTHROPIC_API_KEY is set)          shaky handwriting reads)  savings · interactions
```

Raw OCR (Tesseract etc.) fails badly on doctors' handwriting. A vision LLM does the
reading; Ollama's structured-output mode grammar-constrains it to our JSON schema so
parsing never breaks. A fuzzy-match layer then maps whatever comes out onto the local
drug database, so even a shaky read like "Augmentn" lands on Augmentin 625.

## Run it

```powershell
cd C:\Users\user\medscan
pip install -r requirements.txt

# one-time: install Ollama (ollama.com) and pull the vision model
ollama pull llava

uvicorn app.main:app --port 8010
```

Open http://127.0.0.1:8010  (port 8000 is taken by another app on this machine)

**Backends** (auto-selected, override with `MEDSCAN_BACKEND=ollama|claude`):

| Backend | Cost | Handwriting accuracy | Speed |
|---|---|---|---|
| `ollama` + llava (default) | Free, local | Fair — OK on printed/neat writing, struggles with heavy scrawl | Slow on CPU (1–5 min/scan) |
| `claude` (if `ANTHROPIC_API_KEY` set) | Paid API | Excellent | 10–20 s |

Better free local models than llava, if your machine can handle them:
`ollama pull qwen2.5vl:7b` (much stronger OCR) then set `$env:OLLAMA_MODEL="qwen2.5vl:7b"`.

**No model at all?** The **Try demo** button and the **Type names** tab work with zero AI backend.

## Project layout

| Path | What it is |
|---|---|
| `app/main.py` | FastAPI server — scan/lookup/suggest/medicine/stores/history/mymeds/auth APIs |
| `app/extraction.py` | Vision extraction — Ollama (default) or Claude backend, same JSON schema |
| `app/matcher.py` | Tiered fuzzy matching over 246k names, salt-signature grouping, interactions |
| `app/salts.py` | Shared salt-composition parser (spelling normalization, signatures) |
| `app/auth.py` | Accounts (SQLite + PBKDF2), sessions, scan history, My Medicines storage |
| `app/stores.py` | Jan Aushadhi kendra locator (haversine nearest by coords or pincode) |
| `data/medicines.json` | **268 curated brands** — hand-checked categories, aliases, generic prices |
| `data/bulk.json` | **246,064 products / 10,932 salt groups** from the 1mg dataset (`python data/import_bulk.py`) |
| `data/stores.json` | **18,673 Jan Aushadhi kendras** geolocated via pincode centroids (`python data/build_stores.py`) |
| `data/salt_info.json` | Consumer-level uses/side-effects/cautions for ~170 common salts |
| `data/interactions.json` | **76 curated interaction rules** + auto duplicate-ingredient check |
| `static/index.html` | Single-page frontend: autocomplete, store finder, history, My Medicines, detail views, EN/हिंदी toggle |

**Features**: scan history with lifetime savings (per account) · **My Medicines** — every new
scan is cross-checked against the medicines you take regularly · Jan Aushadhi **store
locator** (geolocation or pincode) · per-medicine **detail view** (uses, side effects,
cautions, all same-salt brands) · **paediatric dose calculator** (weight-based, 13 common
children's medicines, hard safety caps) · **scan-accuracy feedback** (👍/👎 per medicine,
aggregated at `/api/feedback/stats`) · **price-freshness labels** (bulk MRPs ≈ Nov 2022,
curated ≈ Jul 2026) · **Hindi UI** toggle. Store data: kendra list via
janaushdhi.pages.dev (July 2026) + [All India Pincode Directory](https://www.data.gov.in/resource/all-india-pincode-directory)
coordinates. UI chrome is translated; medical text stays English for accuracy.

**Same salt, different brands** — every product is grouped by an exact salt+strength
signature; results list the cheapest interchangeable brands (e.g. 2,573 products share
Augmentin 625's composition, from ₹6.98). **Autocomplete** — `/api/suggest?q=do` returns
matches from the first letter via binary search (<1ms).

## Deploy for free (Hugging Face Spaces)

The repo ships a `Dockerfile` ready for [HF Spaces](https://huggingface.co/spaces)
(free tier: 2 vCPU / 16 GB RAM — enough for the in-memory drug index):

1. Get a **free Gemini API key** at [aistudio.google.com](https://aistudio.google.com) (no card).
2. Create a Space → SDK: **Docker** → link this repo (or push to the Space's git remote).
3. In Space **Settings → Secrets**, add `GEMINI_API_KEY`.
4. That's it — the app auto-uses Gemini for scans in production
   (`MEDSCAN_BACKEND=gemini` is set in the Dockerfile; locally it still uses Ollama).

Scan endpoint is rate-limited (`MEDSCAN_SCANS_PER_HOUR_PER_IP`, default 6/h;
`MEDSCAN_SCANS_PER_DAY`, default 200) to stay inside the free Gemini quota.
Known free-tier trade-offs: the Space sleeps when idle (first visit after that is
slow), and `data/users.db` (accounts/history) resets on rebuild — swap SQLite for a
free Neon/Supabase Postgres when that starts to matter.

## Dataset notes

The bulk layer covers essentially every allopathic product on the Indian market
(253,974 rows; discontinued and unpriced rows dropped → 246,064 active). Bulk prices
are MRPs as of ~Nov 2022 — treat as indicative. Curated entries win on exact matches
and carry better generic pricing. Further upgrades: Jan Aushadhi product list
(janaushadhi.gov.in) for official generic prices; DrugBank / ONC datasets for
interactions at scale (keyed on the same salt names).

Unmatched drugs are still shown in the UI, flagged "not in formulary" — the app never
silently drops a medicine it read.

## Disclaimers

Prices are indicative MRPs for comparison. The interaction list is not exhaustive.
Local-model reads (llava) should be double-checked against the photo — the UI shows
the raw text it read next to each match. This is a decision-support demo, **not**
medical advice — substitutions should be confirmed with a doctor or pharmacist.
