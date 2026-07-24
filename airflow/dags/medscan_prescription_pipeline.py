"""medscan_prescription_pipeline — batch Medallion pipeline for prescription scans.

WHY THIS NEEDS AIRFLOW (and not a cron job or a shell script):

  The extract stage calls an external Vision LLM. Those calls fail in ways a shell
  script handles badly — they time out, they rate-limit (HTTP 429), and they
  occasionally return malformed JSON. What we need is per-task RETRY with
  exponential backoff on *that stage specifically*, plus BACKFILL: if the box was
  down for six hours, we want the six missed hourly windows to run, each as its own
  idempotent logical date. That is retry semantics + catchup — exactly what Airflow
  gives us and what cron does not. Scheduling for its own sake is not the reason.

Design:
  - Tasks contain no business logic; each delegates to medscan_pipeline.airflow_tasks,
    which calls the Phase-1 stage functions.
  - Data flows between tasks through the Delta layers (+ a run-scoped staging file
    for the raw-extract handoff). Only pipeline_run_id and small counts ride XCom.
  - Every task is keyed on pipeline_run_id (derived from the Airflow run) so
    re-running a task for the same logical date upserts rather than duplicates.
  - retries live on extract_via_llm, with exponential backoff + a failure callback
    that records the failure into pipeline_metrics.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

from medscan_pipeline import airflow_tasks as t

default_args = {
    "owner": "medscan",
    "retries": 1,
    "retry_delay": timedelta(seconds=30),
}

with DAG(
    dag_id="medscan_prescription_pipeline",
    description="Ingest prescription images → Bronze/Silver/Gold → serving DB + metrics",
    start_date=datetime(2026, 7, 1),
    schedule="@hourly",
    catchup=True,                      # backfill missed windows
    max_active_runs=1,                 # local mode: one run at a time
    default_args=default_args,
    tags=["medscan", "medallion", "spark", "delta"],
) as dag:

    ingest_new_files = PythonOperator(
        task_id="ingest_new_files", python_callable=t.ingest_new_files)

    extract_via_llm = PythonOperator(
        task_id="extract_via_llm", python_callable=t.extract_via_llm,
        retries=3,                                   # the flaky external call
        retry_delay=timedelta(seconds=10),
        retry_exponential_backoff=True,
        max_retry_delay=timedelta(minutes=5),
        sla=timedelta(minutes=30),
        on_failure_callback=t.extraction_alert)

    write_bronze = PythonOperator(
        task_id="write_bronze", python_callable=t.write_bronze)

    normalize_to_silver = PythonOperator(
        task_id="normalize_to_silver", python_callable=t.normalize_to_silver)

    validate_silver = PythonOperator(
        task_id="validate_silver", python_callable=t.validate_silver)

    match_products_spark = PythonOperator(
        task_id="match_products_spark", python_callable=t.match_products_spark)

    write_gold = PythonOperator(
        task_id="write_gold", python_callable=t.write_gold)

    publish_to_serving_db = PythonOperator(
        task_id="publish_to_serving_db", python_callable=t.publish_to_serving_db)

    emit_run_metrics = PythonOperator(
        task_id="emit_run_metrics", python_callable=t.emit_run_metrics,
        trigger_rule="all_done")       # always record metrics, even on upstream failure

    (ingest_new_files >> extract_via_llm >> write_bronze >> normalize_to_silver
        >> validate_silver >> match_products_spark >> write_gold
        >> publish_to_serving_db >> emit_run_metrics)
