# Implementation

All implementation code for AI Parts Wizard lives here, following the phased plan in §12 of
[`../ai-parts-wizard-spec.md`](../ai-parts-wizard-spec.md). To deploy it, see
[`../DEPLOY.md`](../DEPLOY.md).

## Structure

| Path | Phase (§12.2) | Purpose |
|---|---|---|
| `data_model/` | 1 | Delta master tables in `<catalog>.ai_parts_wizard` (medallion layers as `bronze_*`/`silver_*`/`gold_*` table prefixes; no catalog-create perms) — see §3. |
| `data_generation/` | 2 | Notebooks/jobs generating ~200K synthetic parts across the 8 categories + seeded ground truth + label table — see §4. |
| `matching/` | 3–4 | Feature build + normalization, Mosaic AI Vector Search index, nightly matching job (L2 KNN within `(category, material)` blocks, stable `group_id`, savings, hybrid flagging), and evaluation/tuning — see §5, §9. |
| `serving/` | 5 | Delta↔Lakebase syncs (facts down, review state reverse-synced up) and Lakebase review tables — see §3.3. |
| `app/` | 6 | Databricks App: React front end + FastAPI back end (Match Queue, filters, Group Detail, disposition, normalization, embedded chat) — see §6. |
| `genie/` | 7 | Curated Genie space definition over the gold tables — see §8. |
| `dashboards/` | 8 | AI/BI dashboards (business benefit + engine quality) — see §7. |
| `tests/` | all | Planned test suite — see §13 and [`tests/README.md`](tests/README.md). |

## Notebook parameters

The pipeline notebooks take `catalog` (required) and `schema` (default `ai_parts_wizard`) as
job parameters; the two sync notebooks additionally take the Lakebase connection
(`pg_host`, `pg_user`, `pg_token`, `pg_db`). `deploy/deploy.sh` supplies all of them.

## Tooling

Databricks CLI (`deploy/deploy.sh`) for deployment; Python notebooks on serverless for
generation, matching and syncs. The spec (§12.4) describes a fuller Databricks Asset Bundles +
Lakeflow setup as the production path.
