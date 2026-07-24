"""Thin task callables for the Airflow DAG.

The DAG file stays free of business logic — every task delegates here, and here
delegates to the Phase-1 stage functions. Data moves between tasks through the
Delta layers (and a small run-scoped staging file for the raw extract handoff),
never through XCom; only tiny metadata (the pipeline_run_id and counts) rides XCom.

Each task manages its own Spark session where needed and is keyed on
pipeline_run_id so a re-run of one task for the same logical date is idempotent.
"""

from __future__ import annotations

import json
import os
import time

from . import (bronze, config, extract, gold, ingest, load, match_spark,
               metrics, normalize, silver, validate)
from .records import ExtractRecord, PrescriptionLine, RunMetrics

STAGING = os.path.join(config.DATA_ROOT, "_staging")


def _run_id(context) -> str:
    # Airflow's run_id is unique per logical date → stable idempotency key
    return context["run_id"].replace(":", "").replace("+", "").replace(".", "")


def _staging_path(run_id: str) -> str:
    os.makedirs(STAGING, exist_ok=True)
    return os.path.join(STAGING, f"{run_id}.json")


# ---- stages -------------------------------------------------------------

def ingest_new_files(**context) -> str:
    run_id = _run_id(context)
    pairs = ingest.discover_landing(run_id)
    context["ti"].xcom_push(key="pipeline_run_id", value=run_id)
    context["ti"].xcom_push(key="n_files", value=len(pairs))
    return run_id


def extract_via_llm(**context) -> int:
    """The flaky stage: LLMs time out / rate-limit / return bad JSON → retried."""
    run_id = context["ti"].xcom_pull(key="pipeline_run_id")
    recs = [extract.extract(ing, img).dict() for ing, img in ingest.discover_landing(run_id)]
    # stage raw records to disk (data handoff, not XCom) for write_bronze
    with open(_staging_path(run_id), "w", encoding="utf-8") as f:
        json.dump(recs, f, ensure_ascii=False)
    return len(recs)


def write_bronze(**context) -> int:
    from .spark import get_spark
    run_id = context["ti"].xcom_pull(key="pipeline_run_id")
    with open(_staging_path(run_id), encoding="utf-8") as f:
        recs = [ExtractRecord(**r) for r in json.load(f)]
    spark = get_spark("bronze")
    try:
        return bronze.write_bronze(spark, recs)
    finally:
        spark.stop()


def normalize_to_silver(**context) -> dict:
    from .spark import get_spark
    run_id = context["ti"].xcom_pull(key="pipeline_run_id")
    spark = get_spark("silver")
    try:
        rows = (bronze.read_bronze(spark)
                .filter(f"pipeline_run_id = '{run_id}'").collect())
        lines: list[PrescriptionLine] = []
        for r in rows:
            lines.extend(normalize.normalize(ExtractRecord(**r.asDict())))
        return silver.write_silver(spark, lines)
    finally:
        spark.stop()


def validate_silver(**context) -> dict:
    """Reads this run's silver rows and asserts expectations; pushes failures."""
    from .spark import get_spark
    run_id = context["ti"].xcom_pull(key="pipeline_run_id")
    spark = get_spark("validate")
    try:
        rows = (silver.read_silver(spark)
                .filter(f"pipeline_run_id = '{run_id}'").collect())
        lines = [PrescriptionLine(**{k: r[k] for k in r.asDict()}) for r in rows]
        failures = validate.summarize(lines)
        if len(lines) == 0:
            failures["zero_rows"] = 1
        context["ti"].xcom_push(key="validation_failures", value=failures)
        return failures
    finally:
        spark.stop()


def match_products_spark(**context) -> int:
    from .spark import get_spark
    run_id = context["ti"].xcom_pull(key="pipeline_run_id")
    spark = get_spark("match")
    try:
        rows = (silver.read_silver(spark)
                .filter(f"pipeline_run_id = '{run_id}'").collect())
        lines = [PrescriptionLine(**{k: r[k] for k in r.asDict()}) for r in rows]
        matched = match_spark.match_lines_spark(spark, lines)
        return gold.write_gold_matched(spark, matched)
    finally:
        spark.stop()


def write_gold(**context) -> int:
    """Gold matched is written by match_products_spark; this verifies the rowcount."""
    from .spark import get_spark
    run_id = context["ti"].xcom_pull(key="pipeline_run_id")
    spark = get_spark("gold-verify")
    try:
        from delta.tables import DeltaTable
        if not DeltaTable.isDeltaTable(spark, config.GOLD_MATCHED_PATH):
            return 0
        return (spark.read.format("delta").load(config.GOLD_MATCHED_PATH)
                .filter(f"pipeline_run_id = '{run_id}'").count())
    finally:
        spark.stop()


def publish_to_serving_db(**context) -> int:
    from .spark import get_spark
    from .records import MatchedLine
    run_id = context["ti"].xcom_pull(key="pipeline_run_id")
    spark = get_spark("publish")
    try:
        rows = (spark.read.format("delta").load(config.GOLD_MATCHED_PATH)
                .filter(f"pipeline_run_id = '{run_id}'").collect())
        matched = [MatchedLine(**{k: r[k] for k in r.asDict()}) for r in rows]
        return load.load(matched)
    finally:
        spark.stop()


def emit_run_metrics(**context) -> None:
    from .spark import get_spark
    ti = context["ti"]
    run_id = ti.xcom_pull(key="pipeline_run_id")
    spark = get_spark("metrics")
    try:
        silver_rows = (silver.read_silver(spark).filter(f"pipeline_run_id = '{run_id}'"))
        gold_rows = (spark.read.format("delta").load(config.GOLD_MATCHED_PATH)
                     .filter(f"pipeline_run_id = '{run_id}'"))
        s_count = silver_rows.count()
        g = gold_rows.collect()
        matched_hits = sum(1 for r in g if r["match_method"] != "unmatched")
        mean_conf = (silver_rows.groupBy().avg("extraction_confidence").collect()[0][0]) or 0.0
        rm = RunMetrics(
            pipeline_run_id=run_id, run_started_at=context["ts"],
            run_finished_at=config.utc_now_iso(),
            bronze_rows=ti.xcom_pull(task_ids="extract_via_llm") or 0,
            silver_rows=s_count,
            quarantine_rows=(ti.xcom_pull(task_ids="normalize_to_silver") or {}).get("quarantine_rows", 0),
            gold_rows=len(g), matched_rows=matched_hits,
            match_rate=round(matched_hits / len(g), 4) if g else 0.0,
            mean_confidence=round(mean_conf, 4),
            stage_durations_sec={}, status="success",
            validation_failures=ti.xcom_pull(key="validation_failures") or {})
        gold.write_gold_metrics(spark, rm)
        metrics.export_to_serving(rm)
    finally:
        spark.stop()


def extraction_alert(context) -> None:
    """on_failure_callback for extract_via_llm — record the failure to metrics."""
    run_id = context.get("run_id", "unknown")
    rm = RunMetrics(
        pipeline_run_id=str(run_id), run_started_at=str(context.get("ts", "")),
        run_finished_at=config.utc_now_iso(), status="extract_failed")
    try:
        metrics.export_to_serving(rm)
    except Exception:
        pass
