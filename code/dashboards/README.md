# AI/BI Dashboard (Phase 8)

Lakeview dashboard over the all-Delta gold tables — business benefit + engine quality. See spec §7.

- "AI Parts Wizard — Rationalization", created and published by `deploy/deploy.sh dashboard`
  (prints the URL; dashboard id saved to `deploy/.state.env`).

## Contents

**KPIs:** Annual savings identified (USD), Match groups, Parts in groups, Duplicate recall,
Precision, Normalized groups. (Reference build: ~$36.1M/yr savings on ~$397M annual spend
across grouped parts; 24,987 groups, 65,251 parts, 99.7% recall, 100% precision.)

**Business benefit:**
- Annual savings by category (bar)
- Annual savings by duplication span — Cross-plant / Cross-type / Cross-model (bar)
- Duplicate groups by category (bar)
- Review status (pie: new / reviewed / consolidated / dismissed)

**Engine quality** (from `gold_eval_metrics`, vs the §4 seeded ground truth):
- F1 by category (bar)
- Coincidental near-identical parts by category (bar)
- Per-category recall / precision / F1 / coincidental parts (table)

## Data sources (all-Delta, no federation)

`gold_match_groups`, `gold_match_group_members`, `gold_review_dispositions`,
`gold_normalized_parts`, `gold_eval_metrics`.

## Recreate / update

`dashboard.json` holds `{serialized_dashboard: <json string>}` with table names templated as
`__CATALOG__.__SCHEMA__`; `deploy.sh dashboard` renders and creates/updates it. Manual
equivalent (after substituting):

```bash
databricks api post  /api/2.0/lakeview/dashboards            -p <profile> --json @create.json
databricks api patch /api/2.0/lakeview/dashboards/<id>       -p <profile> --json @update.json
databricks api post  /api/2.0/lakeview/dashboards/<id>/published -p <profile> --json '{"warehouse_id":"<warehouse_id>"}'
```

> All six dataset queries were validated against the warehouse before building (the skill's
> mandatory step). The dashboard is behind workspace SSO.
