# Phase 6 — Azure Databricks (optional)

> **Status: code-ready, not stood up here.** Phases 0–5 run locally in Docker and
> are verified. This phase needs a live Azure subscription + Databricks workspace
> (your credentials, your free-trial credits), so it is documented as a runnable
> path rather than executed in this environment. Nothing about it is faked.

The whole point of Phase 2's `DATA_ROOT` abstraction was that moving to the cloud
should require **no code change**. It doesn't:

```bash
# local (default)
MEDSCAN_DATA_ROOT=./data

# Azure ADLS Gen2 — same code, different root
MEDSCAN_DATA_ROOT=abfss://data@<storage_account>.dfs.core.windows.net/medscan
```

Verified: with that env var set, `config.BRONZE_PATH` etc. resolve to
`abfss://…/bronze/prescriptions` and the Spark/Delta writers are unchanged. The
only local-file read (`bulk.json`) is overridable via `MEDSCAN_CATALOGUE_JSON`
(point it at a DBFS/volume path, or load the catalogue as a Delta table).

## Setup (free trial)

1. **Azure free account** (₹0, includes credits) → create a **Storage account**
   with **hierarchical namespace = ON** (that's what makes it ADLS Gen2). Add a
   container `data`.
2. **Azure Databricks** workspace (Trial / 14-day premium, or the free
   Community-style tier where available).
3. **Cluster** — smallest node (e.g. `Standard_DS3_v2`), single node,
   **auto-terminate = 10 min** (cost guard — see below). Databricks Runtime 15.x
   ships Spark 3.5 + Delta, so no jar install needed.
4. **Unity Catalog** — register the layers as external tables over the ADLS paths:
   ```sql
   CREATE CATALOG IF NOT EXISTS medscan;
   CREATE SCHEMA IF NOT EXISTS medscan.medallion;
   CREATE TABLE medscan.medallion.bronze_prescriptions
     USING DELTA LOCATION 'abfss://data@<acct>.dfs.core.windows.net/medscan/bronze/prescriptions';
   -- repeat for silver / gold / metrics
   ```
5. **Run the matcher as a job** — upload `medscan_pipeline/` to the workspace (or
   `%pip install` from the repo), set the env vars in the cluster spec, and run:
   ```python
   import os
   os.environ["MEDSCAN_DATA_ROOT"] = "abfss://data@<acct>.dfs.core.windows.net/medscan"
   os.environ["MEDSCAN_CATALOGUE_JSON"] = "/Volumes/medscan/ref/bulk.json"
   from medscan_pipeline import silver, match_spark, gold
   spark  # provided by Databricks
   lines = [ ... ]  # or read from silver
   gold.write_gold_matched(spark, match_spark.match_lines_spark(spark, lines))
   ```
   On Databricks, `spark` and Delta are already configured, so `medscan_pipeline.spark`
   is bypassed — pass the notebook's `spark` straight into the stage functions.

## 💸 Cost guards (do not skip)

- **Auto-terminate the cluster at 10 min idle.** Set it on cluster creation.
- **Smallest node, single-node mode.** This is a demo, not a load test.
- **Never leave a cluster running overnight.** Confirm it's terminated before you
  close the tab. Azure bills per second the cluster is up.
- Delete the storage container and workspace when done with the demo.

## What to capture

A screenshot of the Databricks **job run succeeding** against ADLS, plus the Unity
Catalog tables listing, goes here (`docs/azure_job_run.png`) once you run it on your
own subscription.
