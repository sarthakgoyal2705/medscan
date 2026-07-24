"""Benchmark: single-record RapidFuzz path vs the Spark batch matcher.

Generates N prescription lines by sampling REAL drug names from the catalogue and
injecting a light typo into some, so fuzzy matching is actually exercised (not just
exact hits). Reports wall-clock for each engine at each volume.

Honesty note baked into the output: at small N, Spark is expected to LOSE — JVM
startup, broadcast, and task scheduling dominate when the work is tiny. The point
of the benchmark is to find where that crossover is, not to pretend distribution
is free. Run inside the pipeline Docker image.

    docker run --rm -v <data>:/opt/medscan/data medscan-pipeline \
        python -m medscan_pipeline.benchmark
"""

from __future__ import annotations

import json
import random
import time

from . import config
from .records import PrescriptionLine


def _typo(s: str) -> str:
    if len(s) < 5 or random.random() < 0.5:
        return s
    i = random.randint(1, len(s) - 2)
    return s[:i] + s[i + 1:]  # drop a middle char


def make_lines(n: int, seed: int = 7) -> list[PrescriptionLine]:
    random.seed(seed)
    data = json.loads(open(config.CATALOGUE_JSON, encoding="utf-8").read())
    names = [it[0] for it in data["items"]]
    picks = random.sample(names, min(n, len(names)))
    while len(picks) < n:                       # allow repeats to reach 5000+
        picks.append(random.choice(names))
    now = config.utc_now_iso()
    return [PrescriptionLine(
        line_id=f"bench-{i}", source_file_hash="benchmark",
        drug_name_raw=nm, drug_name_normalized=_typo(nm),
        dosage_value=None, dosage_unit=None, frequency=None, quantity=None,
        extraction_confidence=0.9, pipeline_run_id="benchmark", processed_at=now)
        for i, nm in enumerate(picks)]


def main(volumes=(500, 5000)):
    from . import match, match_spark
    from .spark import get_spark

    print(f"{'volume':>8} | {'pandas/RapidFuzz (s)':>22} | {'Spark (s)':>12} | {'winner':>8}")
    print("-" * 62)
    spark = get_spark("benchmark")
    for n in volumes:
        lines = make_lines(n)

        t = time.time()
        r_pandas = match.match_lines(lines)
        t_pandas = time.time() - t

        t = time.time()
        r_spark = match_spark.match_lines_spark(spark, lines)
        t_spark = time.time() - t

        # sanity: both engines should agree on match-rate within a small margin
        mr_p = sum(1 for m in r_pandas if m.match_method != "unmatched") / len(lines)
        mr_s = sum(1 for m in r_spark if m.match_method != "unmatched") / len(lines)

        winner = "pandas" if t_pandas < t_spark else "spark"
        print(f"{n:>8} | {t_pandas:>22.2f} | {t_spark:>12.2f} | {winner:>8}"
              f"   (match-rate pandas={mr_p:.2f} spark={mr_s:.2f})")
    spark.stop()


if __name__ == "__main__":
    main()
