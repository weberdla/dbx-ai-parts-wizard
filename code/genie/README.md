# Genie space + Vector Search (Phase 7)

The conversational / online-lookup layer. See spec §8, §9.1.

## Genie space

- Title "AI Parts Wizard"; created by `deploy/deploy.sh genie` (space id saved to `deploy/.state.env`).
- Curated over the gold/silver tables: `silver_parts`, `silver_models`, `silver_plants`,
  `silver_suppliers`, `silver_supplier_catalogs`, `gold_match_groups`,
  `gold_match_group_members`, `gold_normalized_parts`, `gold_review_dispositions`.
- Instructions encode the domain (plants/models, matching, `group_id`, similarity 0–1,
  savings, blocking by category+material, the part_number join-safety rule, and how to
  answer the "harvester parts >95% similar to tractor part X" query).
- **Global, catalog-wide** — backs the app chat panel docked at the bottom of the Match
  Queue (§6.1). Validated: "total annual savings potential" → **$36,112,562.69** with correct SQL.

`genie_space.json` is the create payload (title/description/parent_path/warehouse_id +
`serialized_space`), templated with `__CATALOG__`, `__SCHEMA__`, `__WAREHOUSE_ID__` and
`__PARENT_PATH__`; `deploy.sh` renders them. Manual equivalent (after substituting):

```bash
databricks api post  /api/2.0/genie/spaces            -p <profile> --json @genie_space.json
databricks api get   "/api/2.0/genie/spaces/<id>?include_serialized_space=true" -p <profile>
databricks api patch /api/2.0/genie/spaces/<id>       -p <profile> --json @genie_space.json
```

> Note: example-SQL and benchmark entries were folded into the instructions text — the
> export proto requires those arrays to carry sorted ids / answers, which the builder helper
> doesn't emit; add them via the Genie UI if richer tuning is wanted.

## Vector Search index (online "find similar")

- **Endpoint:** `apw-vs` (STANDARD). **Index:**
  `<catalog>.<schema>.part_features_vs_index` (template: `vs_index.json`).
- **Delta Sync** over `gold_part_features` (the same canonical normalized vectors the batch
  matcher uses — §9.1), `primary_key=part_id`, self-managed `feature_vector` (21-dim),
  `pipeline_type=TRIGGERED`. CDF is enabled on the source table.
- Purpose: live per-part nearest-neighbor lookups for the app's "find similar" (a future
  app feature); the batch groups remain the system of record.

```bash
deploy/deploy.sh vector-search      # creates the endpoint (if missing) + index, or re-syncs it
# manual equivalent:
databricks vector-search-indexes create-index --json @<rendered vs_index.json> -p <profile>
databricks vector-search-indexes sync-index <index-name> -p <profile>   # trigger a sync
```
