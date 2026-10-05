# Databricks notebook source
# MAGIC %md
# MAGIC # AI Parts Wizard — Matching Evaluation (Phase 4)
# MAGIC
# MAGIC Per-category precision / recall / F1 of the matcher vs the seeded `gold_ground_truth`,
# MAGIC plus the coincidental-match volume. Writes `gold_eval_metrics` (read by the §7
# MAGIC engine-quality dashboard). See spec §1.4, §9.5.
# MAGIC
# MAGIC **Labeled eval set:** duplicates = positives (should match); hard-negatives + near-misses
# MAGIC = negatives (should not). A pair is "predicted matched" when both parts share a group.
# MAGIC **Coincidental** = grouped parts that are not part of any seeded duplicate — unlabeled
# MAGIC near-identical parts (legitimate consolidation candidates, not errors), concentrated in
# MAGIC low-attribute categories (Pin/Shaft, Seal/O-ring).

# COMMAND ----------

# Target location — passed as job parameters (see DEPLOY.md).
dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema", "ai_parts_wizard")
CATALOG = dbutils.widgets.get("catalog")
SCHEMA = dbutils.widgets.get("schema")
assert CATALOG, "catalog is a required job parameter"
FQ = f"{CATALOG}.{SCHEMA}"

# COMMAND ----------

spark.sql(f"""CREATE TABLE IF NOT EXISTS {FQ}.gold_eval_metrics (
  part_category STRING, recall DOUBLE, precision DOUBLE, f1 DOUBLE,
  dup_total INT, dup_tp INT, hn_fp INT, nm_fp INT, coincidental_parts INT, evaluated_at TIMESTAMP
) USING DELTA COMMENT 'Per-category matching evaluation vs gold_ground_truth. Spec 1.4, 9.5.'""")

# COMMAND ----------

spark.sql(f"""INSERT OVERWRITE {FQ}.gold_eval_metrics
WITH mem AS (SELECT m.part_id, m.group_id, p.part_category cat
             FROM {FQ}.gold_match_group_members m JOIN {FQ}.silver_parts p ON p.part_id=m.part_id),
gt AS (SELECT base_part_id b, variant_part_id v, relationship rel, part_category cat FROM {FQ}.gold_ground_truth),
pe AS (SELECT gt.cat, gt.rel, CASE WHEN gb.group_id IS NOT NULL AND gb.group_id=gv.group_id THEN 1 ELSE 0 END same
       FROM gt LEFT JOIN mem gb ON gb.part_id=gt.b LEFT JOIN mem gv ON gv.part_id=gt.v),
agg AS (SELECT cat,
    sum(CASE WHEN rel='duplicate' THEN 1 ELSE 0 END) dup_tot,
    sum(CASE WHEN rel='duplicate' AND same=1 THEN 1 ELSE 0 END) dup_tp,
    sum(CASE WHEN rel='hard_negative' AND same=1 THEN 1 ELSE 0 END) hn_fp,
    sum(CASE WHEN rel='near_miss' AND same=1 THEN 1 ELSE 0 END) nm_fp FROM pe GROUP BY cat),
grp AS (SELECT cat, count(DISTINCT part_id) grouped FROM mem GROUP BY cat),
seeded AS (SELECT cat, count(DISTINCT part_id) seeded FROM mem
           WHERE part_id IN (SELECT b FROM gt WHERE rel='duplicate' UNION SELECT v FROM gt WHERE rel='duplicate') GROUP BY cat),
base AS (SELECT a.cat, a.dup_tot, a.dup_tp, a.hn_fp, a.nm_fp, (g.grouped - s.seeded) coincidental,
                a.dup_tp/a.dup_tot AS r, a.dup_tp/(a.dup_tp+a.hn_fp+a.nm_fp) AS p
         FROM agg a JOIN grp g ON g.cat=a.cat JOIN seeded s ON s.cat=a.cat)
SELECT cat, r, p, (2*p*r)/nullif(p+r,0), dup_tot, dup_tp, hn_fp, nm_fp, coincidental, current_timestamp()
FROM base""")

# COMMAND ----------

display(spark.sql(f"""SELECT part_category, round(recall,3) recall, round(precision,3) precision,
  round(f1,3) f1, dup_tp, dup_total, hn_fp, nm_fp, coincidental_parts
  FROM {FQ}.gold_eval_metrics ORDER BY part_category"""))

# COMMAND ----------

# MAGIC %md
# MAGIC ### Notes
# MAGIC - Threshold `L2_THRESHOLD = 0.12` is set just above the measured duplicate-pair max
# MAGIC   (0.093); hard-negatives sit at L2 ≥ ~1.0, so labeled precision is ~100% globally —
# MAGIC   per-category thresholds are not needed to fix accuracy.
# MAGIC - Coincidental near-identical clusters are treated as additional (legitimate)
# MAGIC   consolidation candidates, not false positives.
