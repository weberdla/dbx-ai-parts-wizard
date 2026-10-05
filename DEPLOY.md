# Deploying AI Parts Wizard

`deploy/deploy.sh` stands up the whole solution in one Databricks workspace using the
Databricks CLI. Every step is re-runnable; IDs it creates are remembered in
`deploy/.state.env` so a second run updates rather than duplicates.

## Prerequisites

**Workspace**

- Unity Catalog, with an existing catalog where you can `CREATE SCHEMA` (the project does not
  create a catalog).
- Serverless compute for notebooks/jobs, and a SQL warehouse (serverless recommended).
- **Lakebase Autoscaling** (Postgres), **Databricks Apps**, **Genie** and **AI/BI dashboards**
  enabled. Vector Search is only needed for the optional `vector-search` step.
- Permission to create apps and Lakebase projects, and to grant on the catalog/schema and
  warehouse (the app's service principal is granted read access for Genie).

**Local machine**

- [Databricks CLI](https://docs.databricks.com/dev-tools/cli/install.html) (a recent version with the
  `postgres` command group — developed with v0.297), authenticated:
  `databricks auth login --host https://<workspace-url> --profile <profile>`
- `jq`, `rsync`, and `psql` (PostgreSQL client — e.g. `brew install libpq`, or
  `apt-get install postgresql-client`).
- Only to change the UI: Node 20+ (the built bundle in `code/app/frontend/dist/` is committed,
  so deploying does not require Node).

## Configure

```bash
cp deploy/config.env.example deploy/config.env
```

| Setting | Meaning |
|---|---|
| `DATABRICKS_PROFILE` | CLI profile for the target workspace. |
| `CATALOG` / `SCHEMA` | Existing catalog, and the schema to create (default `ai_parts_wizard`). |
| `WAREHOUSE_ID` | SQL warehouse for Genie + dashboard (SQL Warehouses → warehouse → *Connection details*, or `databricks warehouses list`). |
| `WORKSPACE_DIR` | Workspace folder for notebooks, app source, Genie space and dashboard. Default `/Workspace/Users/<you>/ai_parts_wizard`. |
| `LAKEBASE_PROJECT` / `PGDATABASE` | Lakebase project (created if missing) and serving database (default `apw`). |
| `APP_NAME` | Databricks App name. |
| `VS_ENDPOINT` | Vector Search endpoint for the optional index. |

## Deploy

```bash
deploy/deploy.sh all
```

Expect about **30–60 minutes** end to end, mostly waiting on serverless jobs. That runs these
steps in order (you can also run any of them on their own, e.g.
`deploy/deploy.sh genie app`):

| Step | What it does | Time |
|---|---|---|
| `notebooks` | Imports the six pipeline notebooks into `WORKSPACE_DIR/notebooks`. | seconds |
| `data` | Runs, as serverless jobs: schema + tables → synthetic data (~200K parts) → batch matcher → evaluation. | ~20–45 min (the matcher alone is ~15–30 min) |
| `lakebase` | Creates the Lakebase project (if missing) and the serving database. | a few min |
| `app-setup` | Creates the app (and its service principal), attaches the database as an app resource, creates the SP's Postgres role, creates the review tables + grants ([`code/serving/lakebase_setup.sql`](code/serving/lakebase_setup.sql)), and grants the SP `USE CATALOG` / `USE SCHEMA` / `SELECT` and warehouse `CAN_USE`. | a few min |
| `sync` | Copies review state Lakebase → Delta (creates `gold_review_dispositions` on first run), then match facts Delta → Lakebase for the app. | ~5 min |
| `genie` | Creates (or updates) the Genie space and grants the app `CAN_RUN`. | seconds |
| `app` | Renders `code/app/app.yaml` with your Lakebase host / SP / Genie space, uploads the app and deploys it. Prints the **app URL**. | a few min |
| `dashboard` | Creates (or updates) and publishes the dashboard. Prints the **dashboard URL**. | seconds |

Optional:

```bash
deploy/deploy.sh vector-search   # Vector Search endpoint + Delta Sync index over gold_part_features
```

Open the app URL and you should see ~25K match groups in the queue, sorted by annual
savings (~$36M/yr in total).

## Day-2 operations

- **Refresh after reviews** — review state lives in Lakebase. To push it to Delta (for the
  dashboard and so reviewed groups don't resurface) and refresh the serving copies:
  `deploy/deploy.sh sync`
- **Rebuild from scratch** — `deploy/deploy.sh data sync` regenerates the synthetic catalog,
  re-runs matching and evaluation, and refreshes Lakebase. Review state in Lakebase is kept;
  group ids are content-derived, so reviews still apply to unchanged groups.
- **Change the UI** — `cd code/app/frontend && npm ci && npm run build`, then
  `deploy/deploy.sh app`.
- **Local app dev** — see [`code/app/README.md`](code/app/README.md).

## Security notes

- No credentials are stored in the repo. The app authenticates as its service principal;
  Lakebase passwords are short-lived OAuth tokens generated at run time.
- The `sync` step passes a short-lived Lakebase token to the notebooks as a job
  parameter, which is visible in that job run's metadata until it expires (~1 h). For
  production, use a Databricks secret or run the job as a service principal instead.

## Tear down

Remove what the script created (names are from your `config.env`; IDs from
`deploy/.state.env`):

```bash
P=<profile>
# first, in SQL (while the app's service principal still exists):
#   REVOKE USE CATALOG ON CATALOG <CATALOG> FROM `<APP_SP_CLIENT_ID>`;
databricks apps delete <APP_NAME> -p $P
databricks genie trash-space <GENIE_SPACE_ID> -p $P
databricks lakeview trash <DASHBOARD_ID> -p $P
databricks postgres delete-project projects/<LAKEBASE_PROJECT> -p $P   # soft-deleted; see note below
databricks vector-search-indexes delete-index <CATALOG>.<SCHEMA>.part_features_vs_index -p $P   # if created
databricks vector-search-endpoints delete-endpoint <VS_ENDPOINT> -p $P   # if created
databricks workspace delete <WORKSPACE_DIR> --recursive -p $P
# then, in SQL:  DROP SCHEMA <CATALOG>.<SCHEMA> CASCADE;
rm deploy/.state.env
```

Deleted Lakebase projects are **soft-deleted** and keep their name for a retention period, so
to redeploy right away set a new `LAKEBASE_PROJECT` in `config.env`.

## Troubleshooting

- **A notebook step fails** — open *Job runs* in the workspace (run names start with `apw_`)
  for the error, fix, and re-run just that step (e.g. `deploy/deploy.sh data`).
- **App shows no data** — the `sync` step hasn't run, or the app's Postgres role lacks
  `SELECT`; re-run `deploy/deploy.sh app-setup sync`.
- **Ask Genie returns a permission error** — the app service principal (ID in
  `deploy/.state.env`) needs `CAN_RUN` on the Genie space and `SELECT` on the schema; re-run
  `deploy/deploy.sh app-setup genie`, or share the space with it in the Genie UI.
