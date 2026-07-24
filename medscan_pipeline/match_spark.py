"""Phase 3 — distributed fuzzy matching in PySpark.

This is the one stage with a real justification for Spark: scoring N prescription
lines against a 246K-row catalogue. The naive approach is an N×246K cross join —
quadratic and unusable at volume. We avoid it with:

  1. BLOCKING — both sides get a cheap block key (first 3 normalized chars).
     We only compare lines to catalogue entries sharing a block, shrinking the
     comparison space by ~2-3 orders of magnitude. Avoiding the cross join is the
     interesting part of the design.
  2. BROADCAST — the catalogue (~29 MB in memory) is broadcast to every executor
     so the join is map-side with no shuffle of the big side.
  3. VECTORIZED pandas_udf — the RapidFuzz scorer runs over a whole column batch
     via Arrow, not row-at-a-time. A plain Python UDF would serialize per row and
     dominate the runtime; the pandas_udf amortizes that.

The exact/prefix path in matcher.py stays the live single-lookup engine — spinning
up Spark for one lookup would be absurd. Batch here, RapidFuzz there, on purpose.
"""

from __future__ import annotations

import json
import re

import pandas as pd
from pyspark.broadcast import Broadcast
from pyspark.sql import functions as F
from pyspark.sql import types as T
from pyspark.sql.pandas.functions import pandas_udf
from rapidfuzz import fuzz, process

from . import config
from .records import MatchedLine, PrescriptionLine

_WS = re.compile(r"\s+")
_FORM = re.compile(r"^(tab|tablet|cap|capsule|syp|syrup|inj|t|c)\.?\s+", re.I)


def _norm(s: str) -> str:
    return _WS.sub(" ", (s or "").lower().replace("-", " ")).strip()


def _block_key(name: str) -> str:
    n = _FORM.sub("", _norm(name))
    return n[:3]


def load_catalogue_df(spark):
    """Catalogue as (name, block_key, salt, price, sig_idx) rows for blocking."""
    data = json.loads(open(config.CATALOGUE_JSON, encoding="utf-8").read())
    sigs = data["sigs"]  # [sig_str, cheapest_name, cheapest_price, count]
    rows = []
    for name, salt_str, _keys, pack, price, sig in data["items"]:
        rows.append((name, _block_key(name), salt_str, float(price), int(sig)))
    schema = T.StructType([
        T.StructField("cat_name", T.StringType()),
        T.StructField("block_key", T.StringType()),
        T.StructField("cat_salt", T.StringType()),
        T.StructField("cat_price", T.DoubleType()),
        T.StructField("sig_idx", T.IntegerType()),
    ])
    return spark.createDataFrame(rows, schema), sigs


def match_lines_spark(spark, lines: list[PrescriptionLine]) -> list[MatchedLine]:
    if not lines:
        return []

    cat_df, sigs = load_catalogue_df(spark)

    line_rows = [(ln.line_id, ln.source_file_hash, ln.drug_name_normalized,
                  _block_key(ln.drug_name_normalized), ln.pipeline_run_id)
                 for ln in lines]
    lines_df = spark.createDataFrame(
        line_rows, ["line_id", "source_file_hash", "q_name", "block_key", "pipeline_run_id"])

    # Blocking join on the cheap key + BROADCAST the catalogue → map-side, no shuffle.
    candidates = lines_df.join(F.broadcast(cat_df), on="block_key", how="left")

    # Vectorized similarity: RapidFuzz over the whole partition's columns at once.
    @pandas_udf(T.IntegerType())
    def score_udf(q: pd.Series, c: pd.Series) -> pd.Series:
        return pd.Series([
            int(fuzz.WRatio(_norm(a), _norm(b))) if isinstance(b, str) else 0
            for a, b in zip(q, c)
        ])

    scored = candidates.withColumn("score", score_udf(F.col("q_name"), F.col("cat_name")))

    # best candidate per line
    from pyspark.sql.window import Window
    w = Window.partitionBy("line_id").orderBy(F.col("score").desc())
    best = (scored.withColumn("rk", F.row_number().over(w))
                  .filter(F.col("rk") == 1))

    collected = best.select(
        "line_id", "source_file_hash", "q_name", "cat_name", "cat_salt",
        "cat_price", "sig_idx", "score", "pipeline_run_id").collect()

    now = config.utc_now_iso()
    THRESHOLD = 85
    out: list[MatchedLine] = []
    for r in collected:
        if r["cat_name"] is None or r["score"] < THRESHOLD:
            out.append(MatchedLine(
                line_id=r["line_id"], source_file_hash=r["source_file_hash"],
                drug_name_normalized=r["q_name"], matched_product=None, matched_salt=None,
                match_score=int(r["score"] or 0), match_method="unmatched",
                brand_price=None, generic_name=None, generic_price=None, saving=None,
                pipeline_run_id=r["pipeline_run_id"], matched_at=now))
            continue
        sig = sigs[r["sig_idx"]]  # [sig_str, cheapest_name, cheapest_price, count]
        cheapest_name, cheapest_price = sig[1], float(sig[2])
        method = "exact" if r["score"] >= 100 else "blocked_fuzzy"
        out.append(MatchedLine(
            line_id=r["line_id"], source_file_hash=r["source_file_hash"],
            drug_name_normalized=r["q_name"], matched_product=r["cat_name"],
            matched_salt=r["cat_salt"], match_score=int(r["score"]), match_method=method,
            brand_price=float(r["cat_price"]),
            generic_name=cheapest_name, generic_price=cheapest_price,
            saving=round(float(r["cat_price"]) - cheapest_price, 2),
            pipeline_run_id=r["pipeline_run_id"], matched_at=now))
    return out
