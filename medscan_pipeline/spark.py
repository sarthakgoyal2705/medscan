"""One place that builds a Delta-configured Spark session, reused everywhere.

Local mode only (this is a portfolio pipeline, not a cluster). Delta jars are
resolved by configure_spark_with_delta_pip; the Docker image pre-fetches them at
build time so runs work without hitting Maven each time.

Import guarded so the rest of the package (pure stage functions, config) can be
imported on the host, which has no pyspark.
"""

from __future__ import annotations


def get_spark(app_name: str = "medscan-pipeline"):
    from delta import configure_spark_with_delta_pip
    from pyspark.sql import SparkSession

    builder = (
        SparkSession.builder.appName(app_name)
        .master("local[*]")
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config("spark.sql.catalog.spark_catalog",
                "org.apache.spark.sql.delta.catalog.DeltaCatalog")
        # small-data local runs: keep shuffle partitions low so we don't spawn
        # 200 tiny tasks per stage
        .config("spark.sql.shuffle.partitions", "8")
        .config("spark.sql.session.timeZone", "UTC")
    )
    spark = configure_spark_with_delta_pip(builder).getOrCreate()
    spark.sparkContext.setLogLevel("WARN")
    return spark
