# Databricks notebook source
# MAGIC %md
# MAGIC # AI Parts Wizard — Facts Sync: Delta → Lakebase (Phase 5)
# MAGIC
# MAGIC Syncs the authoritative match facts (Delta gold) into Lakebase Postgres so the app
# MAGIC reads them with low latency (spec §3.3). Delta stays the system of record; these are
# MAGIC read-only serving copies. Runs after the matcher in the nightly sequence (§5).
# MAGIC
# MAGIC Connection params (host / user / OAuth token / db) are passed as job parameters at
# MAGIC run time — never hard-coded. The token is short-lived (~1h), generated per run.

# COMMAND ----------

dbutils.widgets.text("pg_host", "")
dbutils.widgets.text("pg_user", "")
dbutils.widgets.text("pg_token", "")
dbutils.widgets.text("pg_db", "apw")

host = dbutils.widgets.get("pg_host")
user = dbutils.widgets.get("pg_user")
token = dbutils.widgets.get("pg_token")
db = dbutils.widgets.get("pg_db")
assert host and user and token, "pg_host / pg_user / pg_token are required job parameters"

# Target location — passed as job parameters (see DEPLOY.md).
dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema", "ai_parts_wizard")
CATALOG = dbutils.widgets.get("catalog")
SCHEMA = dbutils.widgets.get("schema")
assert CATALOG, "catalog is a required job parameter"
FQ = f"{CATALOG}.{SCHEMA}"

# Serverless allows the native "postgresql" data source (the generic "jdbc" writer is blocked).
def write_pg(df, table):
    (df.write.format("postgresql")
        .option("host", host).option("port", "5432").option("database", db)
        .option("dbtable", table).option("user", user).option("password", token)
        .mode("overwrite").save())

# COMMAND ----------

# MAGIC %md ## match_groups — the review queue

# COMMAND ----------

mg = spark.table(f"{FQ}.gold_match_groups").select(
    "group_id", "part_category", "material", "member_count", "models_spanned",
    "machine_types_spanned", "plants_spanned", "avg_similarity",
    "group_best_price", "total_current_spend", "savings_potential")
write_pg(mg, "match_groups")
print("match_groups synced:", mg.count())

# COMMAND ----------

# MAGIC %md ## match_group_members — denormalized with part details, best price + annual volume

# COMMAND ----------

members = spark.sql(f"""
SELECT m.group_id, m.part_id, p.part_number, p.description,
       m.model_id, m.machine_type, m.plant_id, m.similarity,
       mb.member_best_price, p.annual_volume
FROM {FQ}.gold_match_group_members m
JOIN {FQ}.silver_parts p ON p.part_id = m.part_id
LEFT JOIN (SELECT part_id, min(price_per_unit * (1 - coalesce(unit_discount,0))) AS member_best_price
           FROM {FQ}.silver_supplier_catalogs GROUP BY part_id) mb ON mb.part_id = m.part_id
""")
write_pg(members, "match_group_members")
print("match_group_members synced:", members.count())

# COMMAND ----------

# MAGIC %md ## supplier_offers — per-supplier pricing for grouped parts (for savings deltas)

# COMMAND ----------

offers = spark.sql(f"""
SELECT c.part_id, s.supplier_name, c.price_per_unit, c.unit_discount, c.lead_time_days, c.currency
FROM {FQ}.silver_supplier_catalogs c
JOIN {FQ}.silver_suppliers s ON s.supplier_id = c.supplier_id
WHERE c.part_id IN (SELECT part_id FROM {FQ}.gold_match_group_members)
""")
write_pg(offers, "supplier_offers")
print("supplier_offers synced:", offers.count())

# COMMAND ----------

print("Facts sync complete.")
