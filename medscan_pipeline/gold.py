"""Gold — curated serving tables.

  matched_products : silver lines joined to the catalogue with score + generics.
                     MERGE on line_id so re-runs upsert (idempotent).
  pipeline_metrics : one row per run — the monitoring layer. Append-only history
                     so quality/throughput is tracked over time, not just at the
                     moment of failure.
"""

from __future__ import annotations

from delta.tables import DeltaTable
from pyspark.sql import types as T

from . import config
from .records import MatchedLine, RunMetrics

MATCHED_SCHEMA = T.StructType([
    T.StructField("line_id", T.StringType()),
    T.StructField("source_file_hash", T.StringType()),
    T.StructField("drug_name_normalized", T.StringType()),
    T.StructField("matched_product", T.StringType()),
    T.StructField("matched_salt", T.StringType()),
    T.StructField("match_score", T.IntegerType()),
    T.StructField("match_method", T.StringType()),
    T.StructField("brand_price", T.DoubleType()),
    T.StructField("generic_name", T.StringType()),
    T.StructField("generic_price", T.DoubleType()),
    T.StructField("saving", T.DoubleType()),
    T.StructField("pipeline_run_id", T.StringType()),
    T.StructField("matched_at", T.StringType()),
])

METRICS_SCHEMA = T.StructType([
    T.StructField("pipeline_run_id", T.StringType()),
    T.StructField("run_started_at", T.StringType()),
    T.StructField("run_finished_at", T.StringType()),
    T.StructField("bronze_rows", T.IntegerType()),
    T.StructField("silver_rows", T.IntegerType()),
    T.StructField("quarantine_rows", T.IntegerType()),
    T.StructField("gold_rows", T.IntegerType()),
    T.StructField("matched_rows", T.IntegerType()),
    T.StructField("match_rate", T.DoubleType()),
    T.StructField("mean_confidence", T.DoubleType()),
    T.StructField("stage_durations_sec", T.MapType(T.StringType(), T.DoubleType())),
    T.StructField("status", T.StringType()),
    T.StructField("validation_failures", T.MapType(T.StringType(), T.IntegerType())),
])


def write_gold_matched(spark, matched: list[MatchedLine]) -> int:
    if not matched:
        return 0
    updates = spark.createDataFrame([m.dict() for m in matched], schema=MATCHED_SCHEMA)
    if DeltaTable.isDeltaTable(spark, config.GOLD_MATCHED_PATH):
        (DeltaTable.forPath(spark, config.GOLD_MATCHED_PATH).alias("t")
            .merge(updates.alias("s"), "t.line_id = s.line_id")
            .whenMatchedUpdateAll().whenNotMatchedInsertAll().execute())
    else:
        updates.write.format("delta").mode("overwrite").save(config.GOLD_MATCHED_PATH)
    return len(matched)


def write_gold_metrics(spark, metrics: RunMetrics) -> None:
    df = spark.createDataFrame([metrics.dict()], schema=METRICS_SCHEMA)
    df.write.format("delta").mode("append").save(config.GOLD_METRICS_PATH)


def read_metrics(spark):
    return spark.read.format("delta").load(config.GOLD_METRICS_PATH)
