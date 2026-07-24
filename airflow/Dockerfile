# Airflow worker image = Airflow + Java 17 + our Spark/Delta pipeline deps + code.
# LocalExecutor runs the stage functions (Spark in-process) directly in this image.
FROM apache/airflow:2.10.3-python3.11

USER root
# Spark needs a JVM; Airflow 2.10 py3.11 base is Debian bookworm → openjdk-17 available
RUN apt-get update && apt-get install -y --no-install-recommends \
        openjdk-17-jre-headless procps && \
    rm -rf /var/lib/apt/lists/*
ENV JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64

USER airflow
# pyspark/delta/pandas/pyarrow + rapidfuzz — the same stack the pipeline image uses
COPY requirements-pipeline.txt /tmp/requirements-pipeline.txt
RUN pip install --no-cache-dir -r /tmp/requirements-pipeline.txt

# pre-cache Delta jars so DAG runs don't fetch from Maven each task
RUN python - <<'PY'
from pyspark.sql import SparkSession
from delta import configure_spark_with_delta_pip
b=(SparkSession.builder.appName("warmup").master("local[1]")
   .config("spark.sql.extensions","io.delta.sql.DeltaSparkSessionExtension")
   .config("spark.sql.catalog.spark_catalog","org.apache.spark.sql.delta.catalog.DeltaCatalog"))
configure_spark_with_delta_pip(b).getOrCreate().stop()
PY
