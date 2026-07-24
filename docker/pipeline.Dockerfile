# Pipeline runtime: Python 3.11 + JRE + Spark/Delta. Separate from the web image
# (the host is Python 3.13 with no Java, so Spark can only run in a container).
# Pinned to bookworm: Spark 3.5 supports Java 8/11/17, and bookworm ships
# openjdk-17 (trixie moved to Java 21, which Spark 3.5 doesn't support).
FROM python:3.11-slim-bookworm

# Spark 3.5 needs a JVM (8/11/17). Headless JRE keeps the image lean.
RUN apt-get update && apt-get install -y --no-install-recommends \
        openjdk-17-jre-headless procps && \
    rm -rf /var/lib/apt/lists/*
ENV JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64

WORKDIR /opt/medscan
COPY requirements-pipeline.txt .
RUN pip install --no-cache-dir -r requirements-pipeline.txt

# Pre-fetch the Delta Lake jars at build time so runs don't hit Maven each start.
RUN python - <<'PY'
from pyspark.sql import SparkSession
from delta import configure_spark_with_delta_pip
b = (SparkSession.builder.appName("warmup").master("local[1]")
     .config("spark.sql.extensions","io.delta.sql.DeltaSparkSessionExtension")
     .config("spark.sql.catalog.spark_catalog","org.apache.spark.sql.delta.catalog.DeltaCatalog"))
configure_spark_with_delta_pip(b).getOrCreate().stop()
print("delta jars cached")
PY

# app/ is imported by the stage functions (single extraction + matcher impl)
COPY app ./app
COPY medscan_pipeline ./medscan_pipeline
COPY data/bulk.json data/medicines.json data/interactions.json data/salt_info.json ./data/
COPY data/stores.json data/ped_doses.json ./data/

ENV MEDSCAN_DATA_ROOT=/opt/medscan/data \
    MEDSCAN_LANDING_DIR=/opt/medscan/data/landing \
    MEDSCAN_SERVING_DB=/opt/medscan/data/serving.db \
    PYTHONUNBUFFERED=1

CMD ["python", "-m", "medscan_pipeline.run_pipeline"]
