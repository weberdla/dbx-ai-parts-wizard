#!/usr/bin/env bash
# Deploy AI Parts Wizard into a Databricks workspace. See DEPLOY.md.
#
# Usage:  deploy/deploy.sh all              # full deploy, in order
#         deploy/deploy.sh <step> [step...]  # run individual steps
#
# Steps (in order): notebooks data lakebase app-setup sync genie app dashboard
# Extras:           vector-search  (optional online "find similar" index)
#
# Every step is safe to re-run. IDs created along the way (app service principal,
# Genie space, dashboard) are kept in deploy/.state.env (gitignored).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG="$ROOT/deploy/config.env"
STATE="$ROOT/deploy/.state.env"

[[ -f "$CONFIG" ]] || { echo "Missing deploy/config.env - copy deploy/config.env.example and fill it in." >&2; exit 1; }
set -a; source "$CONFIG"; [[ -f "$STATE" ]] && source "$STATE"; set +a

for v in DATABRICKS_PROFILE CATALOG SCHEMA WAREHOUSE_ID LAKEBASE_PROJECT PGDATABASE APP_NAME; do
  [[ -n "${!v:-}" ]] || { echo "Set $v in deploy/config.env" >&2; exit 1; }
done
for bin in databricks jq psql rsync; do
  command -v "$bin" >/dev/null || { echo "Requires '$bin' on PATH (see DEPLOY.md prerequisites)." >&2; exit 1; }
done

dbx() { databricks "$@" -p "$DATABRICKS_PROFILE"; }
log() { printf '\n==> %s\n' "$*"; }
warn() { printf 'WARN: %s\n' "$*" >&2; }

save_state() {  # save_state KEY VALUE
  touch "$STATE"
  grep -v "^$1=" "$STATE" > "$STATE.tmp" || true
  mv "$STATE.tmp" "$STATE"
  echo "$1=$2" >> "$STATE"
  export "$1=$2"
}

require_state() {
  [[ -n "${!1:-}" ]] || { echo "$1 is not set - run the '$2' step first." >&2; exit 1; }
}

ME=$(dbx current-user me -o json | jq -r .userName)
WORKSPACE_DIR=${WORKSPACE_DIR:-/Workspace/Users/$ME/ai_parts_wizard}
NB_DIR="$WORKSPACE_DIR/notebooks"
UC_PARAMS=$(jq -nc --arg c "$CATALOG" --arg s "$SCHEMA" '{catalog: $c, schema: $s}')

# Substitute the __PLACEHOLDERS__ used in the committed templates.
render() {
  sed -e "s|__CATALOG__|$CATALOG|g" \
      -e "s|__SCHEMA__|$SCHEMA|g" \
      -e "s|__WAREHOUSE_ID__|$WAREHOUSE_ID|g" \
      -e "s|__PARENT_PATH__|$WORKSPACE_DIR|g" \
      -e "s|__PGHOST__|${PGHOST:-}|g" \
      -e "s|__PGDATABASE__|$PGDATABASE|g" \
      -e "s|__APP_SP_CLIENT_ID__|${APP_SP_CLIENT_ID:-}|g" \
      -e "s|__ENDPOINT_NAME__|${ENDPOINT_NAME:-}|g" \
      -e "s|__GENIE_SPACE_ID__|${GENIE_SPACE_ID:-}|g" \
      "$1"
}

# Run a notebook as a one-off serverless job and fail unless it succeeds.
run_notebook() {  # run_notebook NAME PARAMS_JSON
  log "Running notebook $1 (serverless job; this can take a while)"
  local body run_id state=""
  body=$(jq -nc --arg n "apw_$1" --arg p "$NB_DIR/$1" --argjson params "$2" \
    '{run_name: $n, tasks: [{task_key: "main", notebook_task: {notebook_path: $p, base_parameters: $params}}]}')
  run_id=$(dbx jobs submit --json "$body" --no-wait -o json | jq -r .run_id)
  # Poll ourselves so a transient network error doesn't abort a long run.
  while :; do
    sleep 30
    state=$(dbx jobs get-run "$run_id" -o json 2>/dev/null |
      jq -r '"\(.state.life_cycle_state) \(.state.result_state // "")"') ||
      { warn "Could not poll run $run_id; retrying"; continue; }
    case "$state" in TERMINATED*|INTERNAL_ERROR*|SKIPPED*) break ;; esac
  done
  [[ "${state#* }" == "SUCCESS" ]] ||
    { echo "Notebook $1 finished with: $state (run $run_id; see Job runs in the workspace UI)" >&2; exit 1; }
}

# Run one SQL statement on the warehouse via the Statement Execution API.
run_sql() {
  local body resp state
  body=$(jq -nc --arg w "$WAREHOUSE_ID" --arg s "$1" '{warehouse_id: $w, statement: $s, wait_timeout: "50s"}')
  resp=$(dbx api post /api/2.0/sql/statements --json "$body")
  state=$(jq -r .status.state <<<"$resp")
  [[ "$state" == "SUCCEEDED" ]] || { echo "SQL failed ($state): $1" >&2; jq -r '.status.error.message // empty' <<<"$resp" >&2; exit 1; }
}

# Resolve the Lakebase branch/endpoint and export psql connection settings for the
# deploying user (short-lived OAuth token).
lakebase_conn() {
  BRANCH=$(dbx postgres list-branches "projects/$LAKEBASE_PROJECT" -o json | jq -r '.[0].name')
  local ep
  ep=$(dbx postgres list-endpoints "$BRANCH" -o json)
  ENDPOINT_NAME=$(jq -r '.[0].name' <<<"$ep")
  export PGHOST=$(jq -r '.[0].status.hosts.host' <<<"$ep")
  export PGUSER="$ME" PGSSLMODE=require PGPORT=5432
  export PGPASSWORD=$(dbx postgres generate-database-credential "$ENDPOINT_NAME" -o json | jq -r .token)
}

step_notebooks() {
  log "Importing notebooks to $NB_DIR"
  dbx workspace mkdirs "$NB_DIR"
  local f
  for f in data_model/create_schema_and_tables data_generation/generate_sample_data \
           matching/build_matches matching/evaluate_matches \
           serving/sync_facts_to_lakebase serving/reverse_sync_review_to_delta; do
    dbx workspace import "$NB_DIR/$(basename "$f")" --file "$ROOT/code/$f.py" \
      --language PYTHON --format SOURCE --overwrite
  done
}

step_data() {
  run_notebook create_schema_and_tables "$UC_PARAMS"
  run_notebook generate_sample_data "$UC_PARAMS"
  run_notebook build_matches "$UC_PARAMS"
  run_notebook evaluate_matches "$UC_PARAMS"
}

step_lakebase() {
  # list-projects, not get-project: get-project still answers for a recently deleted project.
  if dbx postgres list-projects -o json | jq -e --arg n "projects/$LAKEBASE_PROJECT" 'any(.[]; .name == $n)' >/dev/null; then
    log "Lakebase project $LAKEBASE_PROJECT already exists"
  else
    log "Creating Lakebase project $LAKEBASE_PROJECT"
    dbx postgres create-project "$LAKEBASE_PROJECT" \
      --json '{"spec": {"display_name": "AI Parts Wizard", "pg_version": 17}}' >/dev/null
  fi
  lakebase_conn
  if [[ "$(psql -X -d databricks_postgres -tAc "SELECT 1 FROM pg_database WHERE datname = '$PGDATABASE'")" != 1 ]]; then
    log "Creating database $PGDATABASE"
    psql -X -d databricks_postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE \"$PGDATABASE\""
  fi
}

step_app_setup() {
  if dbx apps get "$APP_NAME" >/dev/null 2>&1; then
    log "App $APP_NAME already exists"
  else
    log "Creating app $APP_NAME (starts its compute; takes a few minutes)"
    dbx apps create "$APP_NAME" --description "AI Parts Wizard - part rationalization review" >/dev/null
  fi
  save_state APP_SP_CLIENT_ID "$(dbx apps get "$APP_NAME" -o json | jq -r .service_principal_client_id)"
  lakebase_conn

  log "Attaching Lakebase database $PGDATABASE as an app resource"
  local db_res
  db_res=$(dbx api get "/api/2.0/postgres/$BRANCH/databases" |
    jq -r --arg d "$PGDATABASE" '.databases[] | select(.status.postgres_database == $d) | .name')
  [[ -n "$db_res" ]] || { echo "Database $PGDATABASE not found - run the 'lakebase' step first." >&2; exit 1; }
  dbx apps update "$APP_NAME" --json "$(jq -nc --arg b "$BRANCH" --arg d "$db_res" \
    '{resources: [{name: "database", postgres: {branch: $b, database: $d, permission: "CAN_CONNECT_AND_CREATE"}}]}')" >/dev/null

  # Attaching the database resource normally creates the SP's Postgres role; create it
  # only if it is still missing.
  if [[ -z "$(dbx postgres list-roles "$BRANCH" -o json |
      jq -r --arg r "$APP_SP_CLIENT_ID" '.[] | select(.status.postgres_role == $r) | .name')" ]]; then
    log "Creating Postgres role for the app service principal"
    dbx postgres create-role "$BRANCH" --role-id apw-app --json "$(jq -nc --arg r "$APP_SP_CLIENT_ID" \
      '{spec: {postgres_role: $r, identity_type: "SERVICE_PRINCIPAL", auth_method: "LAKEBASE_OAUTH_V1"}}')" >/dev/null
  fi

  log "Creating review tables + grants in $PGDATABASE"
  psql -X -d "$PGDATABASE" -v ON_ERROR_STOP=1 -v app_role="$APP_SP_CLIENT_ID" \
    -f "$ROOT/code/serving/lakebase_setup.sql"

  log "Granting the app service principal read access for Genie (Unity Catalog + warehouse)"
  run_sql "GRANT USE CATALOG ON CATALOG \`$CATALOG\` TO \`$APP_SP_CLIENT_ID\`"
  run_sql "GRANT USE SCHEMA, SELECT ON SCHEMA \`$CATALOG\`.\`$SCHEMA\` TO \`$APP_SP_CLIENT_ID\`"
  dbx warehouses update-permissions "$WAREHOUSE_ID" --json "$(jq -nc --arg sp "$APP_SP_CLIENT_ID" \
    '{access_control_list: [{service_principal_name: $sp, permission_level: "CAN_USE"}]}')" >/dev/null
}

# Review state Lakebase -> Delta first (so reviewed groups stay suppressed and
# gold_review_dispositions exists for Genie + the dashboard), then facts Delta -> Lakebase.
step_sync() {
  lakebase_conn
  local params
  params=$(jq -nc --argjson uc "$UC_PARAMS" --arg h "$PGHOST" --arg u "$ME" \
    --arg t "$PGPASSWORD" --arg d "$PGDATABASE" '$uc + {pg_host: $h, pg_user: $u, pg_token: $t, pg_db: $d}')
  run_notebook reverse_sync_review_to_delta "$params"
  run_notebook sync_facts_to_lakebase "$params"
}

step_genie() {
  require_state APP_SP_CLIENT_ID app-setup
  local tmp; tmp=$(mktemp)
  render "$ROOT/code/genie/genie_space.json" > "$tmp"
  if [[ -n "${GENIE_SPACE_ID:-}" ]]; then
    log "Updating Genie space $GENIE_SPACE_ID"
    dbx api patch "/api/2.0/genie/spaces/$GENIE_SPACE_ID" --json "@$tmp" >/dev/null
  else
    log "Creating Genie space"
    local id; id=$(dbx api post /api/2.0/genie/spaces --json "@$tmp" | jq -r '.space_id // empty')
    [[ -n "$id" ]] || { echo "Genie space creation failed (see error above)." >&2; exit 1; }
    save_state GENIE_SPACE_ID "$id"
  fi
  rm -f "$tmp"
  dbx api patch "/api/2.0/permissions/genie/$GENIE_SPACE_ID" --json "$(jq -nc --arg sp "$APP_SP_CLIENT_ID" \
    '{access_control_list: [{service_principal_name: $sp, permission_level: "CAN_RUN"}]}')" >/dev/null ||
    warn "Could not grant the app CAN_RUN on the Genie space - share it with service principal $APP_SP_CLIENT_ID in the Genie UI."
}

step_app() {
  require_state APP_SP_CLIENT_ID app-setup
  require_state GENIE_SPACE_ID genie
  lakebase_conn
  local stage; stage=$(mktemp -d)
  rsync -a --exclude node_modules --exclude .venv --exclude __pycache__ "$ROOT/code/app/" "$stage/"
  render "$ROOT/code/app/app.yaml" > "$stage/app.yaml"
  log "Uploading app source to $WORKSPACE_DIR/app"
  dbx workspace import-dir "$stage" "$WORKSPACE_DIR/app" --overwrite >/dev/null
  rm -rf "$stage"
  log "Deploying app $APP_NAME"
  dbx apps deploy "$APP_NAME" --source-code-path "$WORKSPACE_DIR/app" >/dev/null
  echo "App URL: $(dbx apps get "$APP_NAME" -o json | jq -r .url)"
}

step_dashboard() {
  local tmp; tmp=$(mktemp)
  render "$ROOT/code/dashboards/dashboard.json" |
    jq --arg n "AI Parts Wizard - Rationalization" --arg w "$WAREHOUSE_ID" --arg p "$WORKSPACE_DIR" \
      '{display_name: $n, warehouse_id: $w, parent_path: $p, serialized_dashboard: .serialized_dashboard}' > "$tmp"
  if [[ -n "${DASHBOARD_ID:-}" ]]; then
    log "Updating dashboard $DASHBOARD_ID"
    jq 'del(.parent_path)' "$tmp" > "$tmp.patch"
    dbx api patch "/api/2.0/lakeview/dashboards/$DASHBOARD_ID" --json "@$tmp.patch" >/dev/null
    rm -f "$tmp.patch"
  else
    log "Creating dashboard"
    local id; id=$(dbx api post /api/2.0/lakeview/dashboards --json "@$tmp" | jq -r '.dashboard_id // empty')
    [[ -n "$id" ]] || { echo "Dashboard creation failed (see error above)." >&2; exit 1; }
    save_state DASHBOARD_ID "$id"
  fi
  rm -f "$tmp"
  dbx api post "/api/2.0/lakeview/dashboards/$DASHBOARD_ID/published" \
    --json "$(jq -nc --arg w "$WAREHOUSE_ID" '{warehouse_id: $w}')" >/dev/null
  local host; host=$(databricks auth env --profile "$DATABRICKS_PROFILE" | jq -r .env.DATABRICKS_HOST)
  echo "Dashboard URL: ${host%/}/dashboardsv3/$DASHBOARD_ID/published"
}

step_vector_search() {
  [[ -n "${VS_ENDPOINT:-}" ]] || { echo "Set VS_ENDPOINT in deploy/config.env" >&2; exit 1; }
  if ! dbx vector-search-endpoints get-endpoint "$VS_ENDPOINT" >/dev/null 2>&1; then
    log "Creating Vector Search endpoint $VS_ENDPOINT (takes several minutes)"
    dbx vector-search-endpoints create-endpoint "$VS_ENDPOINT" STANDARD >/dev/null
  fi
  local index="$CATALOG.$SCHEMA.part_features_vs_index" tmp
  if dbx vector-search-indexes get-index "$index" >/dev/null 2>&1; then
    log "Syncing existing index $index"
    dbx vector-search-indexes sync-index "$index"
  else
    log "Creating Delta Sync index $index"
    tmp=$(mktemp)
    render "$ROOT/code/genie/vs_index.json" | jq --arg e "$VS_ENDPOINT" '.endpoint_name = $e' > "$tmp"
    dbx vector-search-indexes create-index --json "@$tmp" >/dev/null
    rm -f "$tmp"
  fi
}

ALL_STEPS=(notebooks data lakebase app-setup sync genie app dashboard)

[[ $# -gt 0 ]] || { sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 1; }
[[ "$1" == "all" ]] && set -- "${ALL_STEPS[@]}"

for step in "$@"; do
  case "$step" in
    notebooks|data|lakebase|app-setup|sync|genie|app|dashboard|vector-search)
      "step_${step//-/_}" ;;
    *) echo "Unknown step: $step" >&2; exit 1 ;;
  esac
done
log "Done: $*"
