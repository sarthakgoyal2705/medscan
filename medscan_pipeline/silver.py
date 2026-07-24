"""Silver — parsed, typed, deduplicated prescription lines.

Idempotency is enforced HERE via a Delta MERGE on (source_file_hash, line_id):
re-running the same bronze data updates in place instead of appending duplicates.
Rows failing validation are written to the _quarantine table with a
rejection_reason — never silently dropped, because losing bad rows loses the
evidence that validation works.

Full validation rules live in validate.py (Phase 5); this module applies them at
the silver boundary.
"""

from __future__ import annotations

from delta.tables import DeltaTable
from pyspark.sql import types as T

from . import config, validate
from .records import PrescriptionLine

SILVER_SCHEMA = T.StructType([
    T.StructField("line_id", T.StringType()),
    T.StructField("source_file_hash", T.StringType()),
    T.StructField("drug_name_raw", T.StringType()),
    T.StructField("drug_name_normalized", T.StringType()),
    T.StructField("dosage_value", T.DoubleType()),
    T.StructField("dosage_unit", T.StringType()),
    T.StructField("frequency", T.StringType()),
    T.StructField("quantity", T.IntegerType()),
    T.StructField("extraction_confidence", T.DoubleType()),
    T.StructField("pipeline_run_id", T.StringType()),
    T.StructField("processed_at", T.StringType()),
    T.StructField("rejection_reason", T.StringType()),
])


def _table_exists(spark, path: str) -> bool:
    return DeltaTable.isDeltaTable(spark, path)


def write_silver(spark, lines: list[PrescriptionLine]) -> dict:
    """Validate → split → MERGE clean rows, append quarantine. Returns counts."""
    clean: list[dict] = []
    rejected: list[dict] = []
    for ln in lines:
        reason = validate.check_line(ln)
        row = ln.dict()
        if reason:
            row["rejection_reason"] = reason
            rejected.append(row)
        else:
            clean.append(row)

    # ---- clean rows: MERGE (idempotent upsert on the composite key) ----
    if clean:
        # Delta MERGE forbids multiple source rows matching one target. The same
        # image can appear in >1 bronze capture (append-only), yielding duplicate
        # (source_file_hash,line_id) here — so dedupe the source first, keeping the
        # most recently processed. This is what makes the merge idempotent.
        deduped: dict[tuple, dict] = {}
        for row in clean:
            deduped[(row["source_file_hash"], row["line_id"])] = row
        clean = list(deduped.values())
        updates = spark.createDataFrame(clean, schema=SILVER_SCHEMA)
        if _table_exists(spark, config.SILVER_PATH):
            (DeltaTable.forPath(spark, config.SILVER_PATH).alias("t")
                .merge(updates.alias("s"),
                       "t.source_file_hash = s.source_file_hash AND t.line_id = s.line_id")
                .whenMatchedUpdateAll()
                .whenNotMatchedInsertAll()
                .execute())
        else:
            updates.write.format("delta").mode("overwrite").save(config.SILVER_PATH)

    # ---- rejected rows: keep the evidence ----
    if rejected:
        qdf = spark.createDataFrame(rejected, schema=SILVER_SCHEMA)
        qdf.write.format("delta").mode("append").save(config.QUARANTINE_PATH)

    return {"silver_rows": len(clean), "quarantine_rows": len(rejected)}


def read_silver(spark):
    return spark.read.format("delta").load(config.SILVER_PATH)
