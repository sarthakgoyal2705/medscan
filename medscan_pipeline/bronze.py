"""Bronze — raw Vision-LLM output, stored exactly as returned.

Append-only, partitioned by ingest_date, never updated or deleted. This is the
replay source: if normalize/match logic changes, silver and gold are rebuildable
from bronze WITHOUT re-paying for LLM inference. That replayability is the actual
reason bronze exists and is immutable.
"""

from __future__ import annotations

from pyspark.sql import types as T

from . import config
from .records import ExtractRecord

BRONZE_SCHEMA = T.StructType([
    T.StructField("pipeline_run_id", T.StringType()),
    T.StructField("source_file_hash", T.StringType()),
    T.StructField("raw_response", T.StringType()),
    T.StructField("model_name", T.StringType()),
    T.StructField("model_provider", T.StringType()),
    T.StructField("prompt_version", T.StringType()),
    T.StructField("ingested_at", T.StringType()),
    T.StructField("ingest_date", T.StringType()),
])


def write_bronze(spark, records: list[ExtractRecord]) -> int:
    """Append raw extract records to the bronze Delta table."""
    if not records:
        return 0
    df = spark.createDataFrame([r.dict() for r in records], schema=BRONZE_SCHEMA)
    (df.write.format("delta")
        .mode("append")
        .partitionBy("ingest_date")
        .save(config.BRONZE_PATH))
    return df.count()


def read_bronze(spark):
    return spark.read.format("delta").load(config.BRONZE_PATH)
