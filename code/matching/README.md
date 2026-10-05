# Matching pipeline (Phase 3)

`build_matches.py` is the Databricks notebook that builds the shared feature table and the
batch matcher, producing `gold_match_groups` / `gold_match_group_members`. See spec §5, §9.

## Flow (spec §5 order)

1. **`gold_feature_stats`** — per-category z-score mean/std for the 21 numeric features
   (universal `weight`/`material_density` + the per-category dims/functional cols).
2. **`gold_part_features`** — one canonical normalized feature vector per part (fixed length;
   non-applicable features = 0, which is neutral within a block). This is the single artifact
   shared by the batch matcher and (later) the Vector Search index.
3. **Near-neighbor pairs** — candidates via offset grid-bucketing on the vector, keyed by
   `(grid, category, material)`; verified with exact L2. (Serverless blocks Spark ML LSH and
   `.cache()`, so this is hand-rolled with SQL higher-order functions.)
4. **Groups** — connected components over the pairs; each group gets a **stable,
   content-derived `group_id`** = `sha2(sorted member part_ids)` (§3.3).
5. **Savings + span** — group best price vs. members' current best; distinct models / machine
   types / plants spanned.

## Engine split

- **Batch matcher (this notebook, Spark):** authoritative `gold_match_groups`.
- **Online (later, Mosaic AI Vector Search):** a Delta Sync index over `gold_part_features`
  for the app's "find similar" + Genie — same vectors, so consistent (§9.1).

## Tuning (measured on `gold_ground_truth`)

- Duplicate-pair L2: p99 = 0.071, **max = 0.093**. Hard-negative L2: ≥ ~1.0.
- `L2_THRESHOLD = 0.12` (just above duplicate max) → **99.7% duplicate recall, ~0
  hard-negative/near-miss violations**.
- `GRID_CELL = 0.3` with 3 offset grids keeps coincidental candidates (and the self-join)
  light while preserving recall.
- Coincidental near-identical clusters (unlabeled) still appear in low-cardinality
  categories — a precision/recall trade-off to finalize in Phase 4.

## Run

Deployed and run by `deploy/deploy.sh` (`notebooks` imports it, `data` runs it as a serverless
job with the `catalog` / `schema` parameters). To run it by hand, import it and submit a job:

```bash
databricks workspace import <dir>/build_matches --file build_matches.py --language PYTHON --format SOURCE --overwrite -p <profile>
databricks jobs submit -p <profile> --json '{"run_name":"apw_build_matches","tasks":[{"task_key":"main",
  "notebook_task":{"notebook_path":"<dir>/build_matches","base_parameters":{"catalog":"<catalog>","schema":"ai_parts_wizard"}}}]}'
```


Note: on serverless, each run is ~25–35 min wall-clock (startup/scaling latency dominates a
few minutes of compute) — relevant to the nightly-job design in §5.
