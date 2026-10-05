# Databricks notebook source
# MAGIC %md
# MAGIC # AI Parts Wizard — Reverse Sync: Lakebase → Delta (Phase 5)
# MAGIC
# MAGIC Lakebase owns review state; this copies it back into Delta so dashboards (§7) and the
# MAGIC matcher's suppression step (§5) read an all-Delta view — no federation (spec §3.3).
# MAGIC Runs hourly and immediately before the nightly matching job.
# MAGIC
# MAGIC Reads the Lakebase-owned `review_dispositions` and `normalized_assignments`, writes the
# MAGIC Delta `gold_review_dispositions`, and populates `gold_normalized_parts` +
# MAGIC `silver_parts.normalized_part_id` from the assignments.

# COMMAND ----------

dbutils.widgets.text("pg_host", "")
dbutils.widgets.text("pg_user", "")
dbutils.widgets.text("pg_token", "")
dbutils.widgets.text("pg_db", "apw")
host = dbutils.widgets.get("pg_host"); user = dbutils.widgets.get("pg_user")
token = dbutils.widgets.get("pg_token"); db = dbutils.widgets.get("pg_db")
assert host and user and token, "pg_host / pg_user / pg_token are required job parameters"

# Target location — passed as job parameters (see DEPLOY.md).
dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema", "ai_parts_wizard")
CATALOG = dbutils.widgets.get("catalog")
SCHEMA = dbutils.widgets.get("schema")
assert CATALOG, "catalog is a required job parameter"
FQ = f"{CATALOG}.{SCHEMA}"

def read_pg(table):
    return (spark.read.format("postgresql")
            .option("host", host).option("port", "5432").option("database", db)
            .option("dbtable", table).option("user", user).option("password", token).load())

# COMMAND ----------

# MAGIC %md ## Dispositions → Delta (all-Delta view for dashboards + suppression)

# COMMAND ----------

disp = read_pg("review_dispositions")
disp.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"{FQ}.gold_review_dispositions")
print("dispositions synced:", disp.count())

# COMMAND ----------

# MAGIC %md ## Normalized assignments → gold_normalized_parts + parts.normalized_part_id

# COMMAND ----------

na = read_pg("normalized_assignments")
na.createOrReplaceTempView("na")

if na.count() > 0:
    # normalized_part_id = the (stable) group_id it was assigned to
    spark.sql(f"""INSERT OVERWRITE {FQ}.gold_normalized_parts
        SELECT na.group_id AS normalized_part_id, na.enterprise_part_number,
               g.part_category, na.assigned_by, na.assigned_at, na.notes
        FROM na JOIN {FQ}.gold_match_groups g ON g.group_id = na.group_id""")

    spark.sql(f"""MERGE INTO {FQ}.silver_parts p
        USING (SELECT m.part_id, m.group_id
               FROM {FQ}.gold_match_group_members m JOIN na ON na.group_id = m.group_id) s
        ON p.part_id = s.part_id
        WHEN MATCHED THEN UPDATE SET normalized_part_id = s.group_id""")
    print("normalized assignments applied:", na.count())
else:
    print("no normalized assignments yet")

print("Reverse sync complete.")
