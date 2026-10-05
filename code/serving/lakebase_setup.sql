-- Lakebase (Postgres) setup for AI Parts Wizard. Run by deploy/deploy.sh against the
-- serving database (default `apw`) as the deploying user, with psql variable
--   :app_role = the app service principal's client id (its Postgres role name).
--
-- The three serving tables (match_groups, match_group_members, supplier_offers) are
-- created by the sync_facts_to_lakebase notebook, which overwrites them on each run —
-- hence the DEFAULT PRIVILEGES grant so the app keeps SELECT on the recreated tables.

-- Review state: Lakebase is the system of record (spec §3.3), keyed on stable group_id.
CREATE TABLE IF NOT EXISTS review_dispositions (
    group_id    TEXT PRIMARY KEY,
    status      TEXT NOT NULL,        -- new | reviewed | consolidated | dismissed
    reviewer    TEXT,
    notes       TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS normalized_assignments (
    group_id               TEXT PRIMARY KEY,
    enterprise_part_number TEXT NOT NULL,
    assigned_by            TEXT,
    assigned_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    notes                  TEXT
);

GRANT USAGE ON SCHEMA public TO :"app_role";
GRANT SELECT ON ALL TABLES IN SCHEMA public TO :"app_role";
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO :"app_role";
GRANT SELECT, INSERT, UPDATE ON review_dispositions, normalized_assignments TO :"app_role";
