# Serving + syncs (Phase 5)

Lakebase (Postgres) serving layer and the Delta↔Lakebase syncs. See spec §3.3, §5.

## Lakebase

- **Project:** `projects/ai-parts-wizard` (autoscaling), branch `production`, endpoint `primary`.
- **Database:** `apw`.
- **Two systems of record:** Delta owns match facts; **Lakebase owns review state**.

Review tables + app grants: [`lakebase_setup.sql`](lakebase_setup.sql) (applied by
`deploy/deploy.sh app-setup`).

## Tables in `apw`

| Table | Owner | Source |
|---|---|---|
| `match_groups` | Delta (synced copy) | `gold_match_groups` |
| `match_group_members` | Delta (synced copy) | `gold_match_group_members` + part details + best price |
| `supplier_offers` | Delta (synced copy) | per-supplier pricing for grouped parts |
| `review_dispositions` | **Lakebase (SoR)** | written by the app (`new`/`reviewed`/`consolidated`/`dismissed`) |
| `normalized_assignments` | **Lakebase (SoR)** | written by the app (enterprise part number per group) |

All keyed on the stable content-derived `group_id`.

## Notebooks

- `sync_facts_to_lakebase.py` — **Delta → Lakebase** (read-only serving copies). Runs after
  the matcher in the nightly sequence.
- `reverse_sync_review_to_delta.py` — **Lakebase → Delta**: writes `gold_review_dispositions`
  and populates `gold_normalized_parts` + `silver_parts.normalized_part_id` from assignments.
  Runs hourly and immediately before the nightly matching job.

Both use the native **`postgresql`** Spark data source (serverless blocks the generic `jdbc`
writer). Connection params (`pg_host`, `pg_user`, `pg_token`, `pg_db`) are passed as job
parameters; the OAuth token is short-lived and generated per run — **never committed**.

### Why notebooks and not Lakebase synced tables?

- **Reverse (Lakebase → Delta):** synced tables only flow **Delta → Lakebase**, so there is
  no managed option for this direction — a notebook is required.
- **Forward (Delta → Lakebase):** we chose a notebook so the serving copies can be
  **denormalized** (a 1:1 synced table can't join in part details / supplier names) and to
  keep one uniform mechanism for both directions. Trade-off: we give up synced tables'
  managed incremental/CDC refresh. **Future refinement:** denormalized CDF-enabled Delta gold
  tables + managed synced tables for the forward direction, notebook only for the reverse.

## Run

```bash
deploy/deploy.sh sync     # review state Lakebase -> Delta, then facts Delta -> Lakebase
```

It submits both notebooks as a serverless job with `catalog`/`schema` plus a freshly generated
Lakebase token (see `step_sync` in [`deploy/deploy.sh`](../../deploy/deploy.sh)).

> **Security:** the demo passes the token as a plaintext job parameter (visible in run
> metadata). Production should use a Databricks secret or the job's service-principal
> identity instead.
