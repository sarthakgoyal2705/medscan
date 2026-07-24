"""MedScan batch pipeline — Medallion (Bronze/Silver/Gold) over Delta Lake,
orchestrated by Airflow, matched with PySpark.

Stage functions (ingest/extract/normalize/match/load) are pure, typed and
Spark-free so they run anywhere. The Delta/Spark modules (spark, bronze, silver,
gold, match_spark) import pyspark and are meant to run inside the Docker pipeline
image (see docker/pipeline.Dockerfile) — the host has no JVM.
"""
