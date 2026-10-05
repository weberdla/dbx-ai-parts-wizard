# Tests

Planned test suite for AI Parts Wizard (not yet implemented in this repo). Strategy and categories are defined in §13 of
[`../../ai-parts-wizard-spec.md`](../../ai-parts-wizard-spec.md); each build phase (§12.2)
ships its own tests.

## Layout

| Path | Category (§13.1) | Covers |
|---|---|---|
| `unit/` | Unit | Normalization, `group_id` hash, similarity-score conversion, savings math. |
| `data_quality/` | Data-quality / expectations | Delta schema & constraints, FK integrity, `part_number` unique within model, blocking-key completeness, generator/label-table validation. |
| `integration/` | Pipeline / integration | Matching on a fixture catalog, nightly chain, Delta↔Lakebase round-trip, suppression path. |
| `app/` | App / API | FastAPI endpoints + React/Playwright e2e flows. |
| `genie/` | Genie evaluation | Benchmark NL questions → expected result sets. |
| `fixtures/` | — | Small deterministic catalog (tens of parts, known duplicates/negatives) for fast runs. |

## Critical invariants (§13.2)

The suite must explicitly cover all five: `group_id` stability, no-resurface,
no-join-on-`part_number`-alone, blocking excludes cross-material, and two-SoR integrity.

## Running

Unit + lint run on PRs via CI; integration/eval run as Databricks Asset Bundle job tasks in
the target workspace on merge (§13.3).
