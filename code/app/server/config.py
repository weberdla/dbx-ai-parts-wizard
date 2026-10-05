"""Runtime configuration and Lakebase OAuth token generation.

Works in two modes:
  * Databricks App  -> WorkspaceClient() auto-configures from the injected
    service-principal credentials (DATABRICKS_CLIENT_ID / _SECRET / _HOST).
  * Local dev       -> WorkspaceClient(profile=DATABRICKS_PROFILE) uses the CLI
    profile; PGUSER falls back to the current user's email.

The Postgres password is a short-lived Lakebase OAuth token generated from the
autoscaling credentials API (POST /api/2.0/postgres/credentials). This is the
autoscaling-tier equivalent of `databricks postgres generate-database-credential`.
"""
import os
import functools

from databricks.sdk import WorkspaceClient

# --- Lakebase target (set in app.yaml, rendered by deploy/deploy.sh) ---
ENDPOINT_NAME = os.environ.get(
    "ENDPOINT_NAME",
    "projects/ai-parts-wizard/branches/production/endpoints/primary",
)
PGHOST = os.environ.get("PGHOST", "")
PGPORT = int(os.environ.get("PGPORT", "5432"))
PGDATABASE = os.environ.get("PGDATABASE", "apw")
PGSSLMODE = os.environ.get("PGSSLMODE", "require")

# Are we running inside a Databricks App? (DATABRICKS_APP_NAME is injected there.)
IS_DATABRICKS_APP = bool(
    os.environ.get("DATABRICKS_APP_NAME") or os.environ.get("DATABRICKS_CLIENT_ID")
)


@functools.lru_cache(maxsize=1)
def get_workspace_client() -> WorkspaceClient:
    if IS_DATABRICKS_APP:
        return WorkspaceClient()
    profile = os.environ.get("DATABRICKS_PROFILE")
    return WorkspaceClient(profile=profile) if profile else WorkspaceClient()


@functools.lru_cache(maxsize=1)
def get_pguser() -> str:
    """Postgres role name to connect as.

    In a deployed app the Database resource injects PGUSER (the service
    principal's application id). Locally we connect as the developer's email.
    """
    env_user = os.environ.get("PGUSER")
    if env_user:
        return env_user
    if IS_DATABRICKS_APP:
        # Fall back to the service principal's client id.
        return os.environ.get("DATABRICKS_CLIENT_ID", "")
    # Local: connect as the current user (their email is a valid PG role).
    try:
        return get_workspace_client().current_user.me().user_name
    except Exception:
        return os.environ.get("USER", "")


def generate_db_token() -> str:
    """Generate a short-lived Lakebase OAuth token for the endpoint."""
    w = get_workspace_client()
    resp = w.api_client.do(
        "POST", "/api/2.0/postgres/credentials", body={"endpoint": ENDPOINT_NAME}
    )
    return resp["token"]
