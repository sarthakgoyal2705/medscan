"""End-to-end batch pipeline orchestration.

ingest → extract → bronze → silver(validate+quarantine) → match → gold → load → metrics

Callable as a script (`python -m medscan_pipeline.run_pipeline`) and imported by
the Airflow DAG, which runs each stage as a separate task. Data flows between
stages through the Delta layers; only small metadata (run_id, counts) would move
via XCom in the orchestrated version.

MEDSCAN_MATCH_ENGINE=spark uses the distributed matcher (match_spark); anything
else uses the single-record RapidFuzz path (match.py). Both are real; see README.
"""

from __future__ import annotations

import os
import time

from . import (bronze, config, extract, gold, ingest, load, match, metrics,
               normalize, silver, validate)
from .records import RunMetrics


def run(landing_dir: str | None = None, use_spark_match: bool | None = None) -> RunMetrics:
    from .spark import get_spark

    run_id = config.new_run_id()
    started = config.utc_now_iso()
    durations: dict[str, float] = {}
    if use_spark_match is None:
        use_spark_match = os.environ.get("MEDSCAN_MATCH_ENGINE", "").lower() == "spark"

    spark = get_spark()

    def timed(name, fn, *a, **k):
        t = time.time()
        out = fn(*a, **k)
        durations[name] = round(time.time() - t, 2)
        return out

    # 1. ingest
    pairs = timed("ingest", ingest.discover_landing, run_id, landing_dir)

    # 2. extract (raw) — the stage Airflow retries, since LLMs fail flakily
    extracts = timed("extract", lambda: [extract.extract(ing, img) for ing, img in pairs])

    # 3. bronze (append raw, immutable)
    bronze_n = timed("bronze", bronze.write_bronze, spark, extracts)

    # 4. normalize → typed lines
    lines = timed("normalize", lambda: [ln for ex in extracts for ln in normalize.normalize(ex)])

    # 5. silver (MERGE dedup + quarantine on validation)
    sv = timed("silver", silver.write_silver, spark, lines)

    # 6. match — Spark path for volume, single-record path otherwise
    if use_spark_match:
        from . import match_spark
        matched = timed("match", match_spark.match_lines_spark, spark, lines)
    else:
        matched = timed("match", match.match_lines, lines)

    # 7. gold (matched_products)
    gold_n = timed("gold", gold.write_gold_matched, spark, matched)

    # 8. load → batch serving DB (sqlite, for the web read path)
    timed("load", load.load, matched)

    # 9. metrics
    mean_conf = (sum(ln.extraction_confidence for ln in lines) / len(lines)) if lines else 0.0
    stats = metrics.compute_match_stats(matched, mean_conf)
    rm = RunMetrics(
        pipeline_run_id=run_id, run_started_at=started, run_finished_at=config.utc_now_iso(),
        bronze_rows=bronze_n, silver_rows=sv["silver_rows"],
        quarantine_rows=sv["quarantine_rows"], gold_rows=gold_n,
        matched_rows=stats["matched_rows"], match_rate=stats["match_rate"],
        mean_confidence=stats["mean_confidence"], stage_durations_sec=durations,
        status="success", validation_failures=validate.summarize(lines))
    gold.write_gold_metrics(spark, rm)
    metrics.export_to_serving(rm)

    spark.stop()
    return rm


if __name__ == "__main__":
    m = run()
    print("run:", m.pipeline_run_id, "| status:", m.status)
    print("bronze:", m.bronze_rows, "silver:", m.silver_rows,
          "quarantine:", m.quarantine_rows, "gold:", m.gold_rows)
    print("match_rate:", m.match_rate, "mean_conf:", m.mean_confidence)
    print("durations:", m.stage_durations_sec)
    print("validation_failures:", m.validation_failures)
