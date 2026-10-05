# Databricks App (Phase 6)

React + FastAPI review app for AI Parts Wizard, reading/writing Lakebase `apw`. See spec §6.

Deployed by `deploy/deploy.sh` (steps `app-setup` and `app`) — see [`DEPLOY.md`](../../DEPLOY.md).

## What it does

- **Match Queue** — ranked match groups with the full filter set + duplication-span toggles
  (spans > 1 model / type / plant); default view = review status `new` AND spans > 1 model,
  sorted by savings. Status chip from `review_dispositions` (missing = `new`).
- **Group Detail** — member parts, supplier pricing with the price-gap ("vs best") column,
  and actions: set disposition (reviewed / consolidated / dismissed) and assign a normalized
  enterprise part number. Writes upsert to `review_dispositions` / `normalized_assignments`.
- **Ask Genie** — docked chat panel proxying the Genie Conversation API (`/api/chat`), run as the app service principal.

## Layout

- `app.py` — FastAPI entry; mounts `/api`, serves the built SPA, warms the DB pool on startup.
- `app.yaml` — uvicorn command + env (`PGHOST/PGPORT/PGDATABASE/PGSSLMODE/PGUSER=<SP client id>/ENDPOINT_NAME/GENIE_SPACE_ID`).
  It is a **template**: `deploy.sh app` fills the `__PLACEHOLDERS__` in a staged copy at deploy time.
- `server/` — `config.py` (dual-mode auth), `db.py` (asyncpg pool, 45-min token refresh),
  `routes.py` (`/api/me`, `/api/filters`, `/api/queue`, `/api/groups/{id}`, disposition + normalize upserts, `/api/chat`),
  `genie.py` (Genie Conversation API proxy).
- `frontend/` — Vite + React 18 + TS (`components/`: Filters, MatchQueue, GroupDetail, ChatPanel).
  `frontend/dist/` is the committed pre-built bundle that gets deployed — **do not gitignore it**.

## Auth / Lakebase wiring

- The app connects to Lakebase as its **service principal**. Two layers were required:
  1. Lakebase attached as an **App resource** (`postgres` type, `CAN_CONNECT_AND_CREATE`).
  2. A Postgres role mapping the SP (`databricks postgres create-role ... identity_type=SERVICE_PRINCIPAL`)
     + `GRANT SELECT` on the serving tables and `SELECT, INSERT, UPDATE` on the two write tables
     to that role (`code/serving/lakebase_setup.sql`). `PGUSER` = the SP's client id.
- In-process token: `WorkspaceClient().api_client.do("POST","/api/2.0/postgres/credentials", body={"endpoint": ENDPOINT_NAME})`
  (autoscaling-tier credential; the typed `w.database.generate_database_credential` is provisioned-tier).

## Local dev / redeploy

```bash
# local: connects to Lakebase as you (do NOT set PGUSER locally)
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
export DATABRICKS_PROFILE=<profile>
export PGHOST=<lakebase endpoint host>     # databricks postgres list-endpoints projects/<project>/branches/production
export ENDPOINT_NAME=projects/<project>/branches/production/endpoints/primary
export GENIE_SPACE_ID=<space id>           # from deploy/.state.env
.venv/bin/python app.py                    # or, for UI work: cd frontend && npm run dev

# rebuild the UI, then redeploy
cd frontend && npm ci && npm run build && cd ../../..
deploy/deploy.sh app
```

> Env note: the workspace mirror only had TypeScript 7 / Vite 8, so the frontend pins those;
> the build uses `vite build` (esbuild transpile) rather than a separate `tsc` type-check step.
