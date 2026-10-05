# Databricks notebook source
# MAGIC %md
# MAGIC # AI Parts Wizard — Matching Pipeline (Phase 3)
# MAGIC
# MAGIC Builds the shared feature table, then the batch matcher (Spark LSH) that produces
# MAGIC `gold_match_groups` / `gold_match_group_members`. See spec §5, §9.
# MAGIC
# MAGIC Order (spec §5): feature stats → feature table → LSH near-neighbor pairs → connected
# MAGIC components (groups, stable content-derived `group_id`) → savings + span → write.
# MAGIC The online Vector Search index is a Delta Sync off `gold_part_features` (separate step).

# COMMAND ----------

from pyspark.sql import functions as F

# Target location — passed as job parameters (see DEPLOY.md).
dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema", "ai_parts_wizard")
CATALOG = dbutils.widgets.get("catalog")
SCHEMA = dbutils.widgets.get("schema")
assert CATALOG, "catalog is a required job parameter"
FQ = f"{CATALOG}.{SCHEMA}"

# Matching parameters (measured on gold_ground_truth; tune further in Phase 4).
# Duplicate-pair L2: p99=0.071, max=0.093. Hard-negative L2: >=~1.0. So a threshold just
# above the duplicate max cleanly separates duplicates from coincidental neighbors — too
# loose and single-linkage connected-components chains the dense low-dim blocks into blobs.
L2_THRESHOLD = 0.12
# Candidate-bucket cell (z-score units). ~3x the per-dim duplicate delta so duplicates
# co-bucket, but small enough to keep coincidental candidates (and the self-join) light.
GRID_CELL = 0.3
GRID_OFFSETS = [0.0, GRID_CELL / 3, 2 * GRID_CELL / 3]

# 21 numeric features (universal weight/density + the per-category dims/functional cols).
# part_category & material are blocking keys, NOT features (spec §9.2/§9.4).
FEATURES = ["weight","material_density","length","width","thickness","diameter",
    "inner_diameter","outer_diameter","nominal_diameter","cross_section_diameter","head_width",
    "gauge","thread_pitch","tensile_strength","hardness","pressure_rating","load_rating",
    "temperature_rating","hole_count","voltage_rating","conductor_count"]

# COMMAND ----------

# MAGIC %md ## Gold tables (create if absent)

# COMMAND ----------

spark.sql(f"""CREATE TABLE IF NOT EXISTS {FQ}.gold_feature_stats (
  part_category STRING, feature STRING, mean DOUBLE, std DOUBLE
) USING DELTA COMMENT 'Per-category z-score normalization stats. Spec §5, §9.4.'""")

spark.sql(f"""CREATE TABLE IF NOT EXISTS {FQ}.gold_part_features (
  part_id STRING NOT NULL, part_category STRING, material STRING,
  feature_vector ARRAY<DOUBLE>,
  CONSTRAINT pk_gold_part_features PRIMARY KEY (part_id)
) USING DELTA
TBLPROPERTIES (delta.enableChangeDataFeed = true)
COMMENT 'Canonical normalized feature vector per part; shared by batch matcher + Vector Search. Spec §9.1.'""")

spark.sql(f"""CREATE TABLE IF NOT EXISTS {FQ}.gold_match_groups (
  group_id STRING NOT NULL, part_category STRING, material STRING,
  member_count INT, models_spanned INT, machine_types_spanned INT, plants_spanned INT,
  avg_similarity DOUBLE, group_best_price DOUBLE, total_current_spend DOUBLE,
  savings_potential DOUBLE, generated_at TIMESTAMP,
  CONSTRAINT pk_gold_match_groups PRIMARY KEY (group_id)
) USING DELTA COMMENT 'Match groups (clusters of similar parts). Stable content-derived group_id. Spec §3.3, §5.'""")

spark.sql(f"""CREATE TABLE IF NOT EXISTS {FQ}.gold_match_group_members (
  group_id STRING NOT NULL, part_id STRING NOT NULL, similarity DOUBLE,
  model_id STRING, machine_type STRING, plant_id STRING,
  CONSTRAINT pk_gold_match_group_members PRIMARY KEY (group_id, part_id)
) USING DELTA COMMENT 'Parts per group + per-part similarity and span metadata. Spec §3.3.'""")

# COMMAND ----------

# MAGIC %md ## 1. Per-category normalization stats (over base parts)

# COMMAND ----------

aggs = []
for f in FEATURES:
    aggs.append(f"avg({f}) AS {f}__m")
    aggs.append(f"stddev_pop({f}) AS {f}__s")
stats_row = spark.sql(
    f"SELECT part_category, {', '.join(aggs)} FROM {FQ}.silver_parts "
    "WHERE part_id NOT LIKE '%-%' GROUP BY part_category"
).collect()

stats = {}  # (category, feature) -> (mean, std_or_None)
stats_records = []
for r in stats_row:
    cat = r["part_category"]
    for f in FEATURES:
        m, s = r[f"{f}__m"], r[f"{f}__s"]
        if m is not None:
            stats[(cat, f)] = (float(m), float(s) if (s is not None and s > 0) else None)
            stats_records.append((cat, f, float(m), float(s) if s is not None else 0.0))

spark.createDataFrame(stats_records, "part_category string, feature string, mean double, std double") \
    .write.mode("overwrite").insertInto(f"{FQ}.gold_feature_stats")
print("feature stats rows:", len(stats_records))

# COMMAND ----------

# MAGIC %md ## 2. Build the canonical normalized feature vector per part

# COMMAND ----------

def norm_expr(feat):
    branches = []
    for (cat, f), (m, s) in stats.items():
        if f != feat:
            continue
        if s:  # (x - mean) / std ; NULL -> mean -> 0
            branches.append(f"WHEN '{cat}' THEN (coalesce({feat}, {m}) - {m}) / {s}")
        else:  # constant within category -> 0
            branches.append(f"WHEN '{cat}' THEN 0.0")
    if not branches:
        return "0.0"
    return "CASE part_category " + " ".join(branches) + " ELSE 0.0 END"

vector_expr = "array(" + ", ".join(norm_expr(f) for f in FEATURES) + ")"
spark.sql(f"""INSERT OVERWRITE {FQ}.gold_part_features
SELECT part_id, part_category, material, {vector_expr} AS feature_vector
FROM {FQ}.silver_parts""")
print("feature rows:", spark.table(f"{FQ}.gold_part_features").count())

# COMMAND ----------

# MAGIC %md ## 3. Near-neighbor pairs — offset grid-bucketing + exact L2
# MAGIC Serverless blocks Spark ML LSH, so we hand-roll it with SQL higher-order functions:
# MAGIC bucket the normalized vector on two half-cell-offset grids (boundary robustness),
# MAGIC keyed by (grid, category, material); candidates share a bucket; verify with exact L2.

# COMMAND ----------

feat = spark.table(f"{FQ}.gold_part_features")

def bucketed(tag, off):
    bexpr = (f"concat('{tag}|', part_category, '|', material, '|', "
             f"concat_ws('_', transform(feature_vector, x -> cast(floor((x + {off})/{GRID_CELL}) AS INT))))")
    return feat.selectExpr("part_id", "part_category AS cat", "feature_vector", f"{bexpr} AS bk")

buck = None
for _i, _off in enumerate(GRID_OFFSETS):
    _b = bucketed(f"g{_i}", _off)
    buck = _b if buck is None else buck.unionByName(_b)
L = buck.selectExpr("part_id AS a", "cat", "feature_vector AS va", "bk")
R = buck.selectExpr("part_id AS b", "feature_vector AS vb", "bk AS bk2")
pairs = (L.join(R, L.bk == R.bk2).where("a < b")
    .selectExpr("a", "b", "cat",
        "sqrt(aggregate(zip_with(va, vb, (x,y) -> (x-y)*(x-y)), cast(0.0 AS DOUBLE), (acc,x) -> acc + x)) AS dist")
    .dropDuplicates(["a", "b"])
    .where(f"dist <= {L2_THRESHOLD}")
    .selectExpr("a", "b", "cat", "1/(1+dist) AS sim"))
# Materialize to a table (serverless disallows .cache()); the CC loop below reads this
# small table instead of recomputing the 200K-row bucketing self-join each iteration.
pairs.write.mode("overwrite").saveAsTable(f"{FQ}.tmp_match_pairs")
pairs = spark.table(f"{FQ}.tmp_match_pairs")
print("candidate near-neighbor pairs:", pairs.count())

# COMMAND ----------

# MAGIC %md ## 4. Connected components -> groups (stable content-derived group_id)

# COMMAND ----------

edges = pairs.selectExpr("a AS src", "b AS dst").union(pairs.selectExpr("b AS src", "a AS dst"))
labels = edges.select(F.col("src").alias("id")).distinct().withColumn("comp", F.col("id"))
for _ in range(10):  # min-label propagation (small components converge quickly)
    msg = edges.join(labels, edges.src == labels.id).groupBy("dst").agg(F.min("comp").alias("nb"))
    labels = (labels.join(msg, labels.id == msg.dst, "left")
              .selectExpr("id", "least(comp, coalesce(nb, comp)) AS comp"))

groups = (labels.groupBy("comp")
    .agg(F.sort_array(F.collect_list("id")).alias("mids"), F.count("*").alias("cnt"))
    .where("cnt >= 2")
    .withColumn("group_id", F.sha2(F.concat_ws(",", F.col("mids")), 256)))
member_rows = groups.select("group_id", F.explode("mids").alias("part_id"))
print("groups:", groups.count(), "| grouped parts:", member_rows.count())

# COMMAND ----------

# MAGIC %md ## 5. Members table (similarity + span metadata)

# COMMAND ----------

node_sim = (pairs.selectExpr("a AS part_id", "sim").union(pairs.selectExpr("b AS part_id", "sim"))
            .groupBy("part_id").agg(F.max("sim").alias("similarity")))
parts = spark.table(f"{FQ}.silver_parts").select("part_id", "model_id")
models = spark.table(f"{FQ}.silver_models").select("model_id", "machine_type", "plant_id")

members = (member_rows
    .join(parts, "part_id")
    .join(models, "model_id")
    .join(node_sim, "part_id", "left")
    .select("group_id", "part_id", "similarity", "model_id", "machine_type", "plant_id"))
members.write.mode("overwrite").insertInto(f"{FQ}.gold_match_group_members")
print("wrote members:", spark.table(f"{FQ}.gold_match_group_members").count())

# COMMAND ----------

# MAGIC %md ## 6. Groups table (span rollups + savings)

# COMMAND ----------

# Read the persisted members table back (avoids recompute / caching on serverless)
mm = spark.table(f"{FQ}.gold_match_group_members")
pcat = spark.table(f"{FQ}.silver_parts").select("part_id", "part_category", "material")
eff = spark.table(f"{FQ}.silver_supplier_catalogs").selectExpr(
    "part_id", "price_per_unit * (1 - coalesce(unit_discount,0)) AS eff")
member_best = eff.groupBy("part_id").agg(F.min("eff").alias("member_best"))

# Annual economics: each member is bought at its own best unit price x its annual volume;
# consolidating onto the group's best unit price saves (member_best - group_best) x volume.
vol = spark.table(f"{FQ}.silver_parts").select("part_id", "annual_volume")
mb = (mm.select("group_id", "part_id").join(member_best, "part_id", "left")
      .join(vol, "part_id", "left"))
savings = (mb.groupBy("group_id").agg(
    F.min("member_best").alias("group_best_price"),
    F.sum(F.col("member_best") * F.col("annual_volume")).alias("total_current_spend"),
    F.sum(F.col("annual_volume")).alias("group_volume")))

span = (mm.join(pcat, "part_id")
    .groupBy("group_id").agg(
        F.first("part_category").alias("part_category"),
        F.first("material").alias("material"),
        F.count("*").alias("member_count"),
        F.countDistinct("model_id").alias("models_spanned"),
        F.countDistinct("machine_type").alias("machine_types_spanned"),
        F.countDistinct("plant_id").alias("plants_spanned"),
        F.avg("similarity").alias("avg_similarity")))

groups_final = (span.join(savings, "group_id")
    .withColumn("savings_potential", F.col("total_current_spend") - F.col("group_volume") * F.col("group_best_price"))
    .withColumn("generated_at", F.current_timestamp())
    .select("group_id","part_category","material","member_count","models_spanned",
            "machine_types_spanned","plants_spanned","avg_similarity","group_best_price",
            "total_current_spend","savings_potential","generated_at"))
groups_final.write.mode("overwrite").insertInto(f"{FQ}.gold_match_groups")
print("wrote groups:", spark.table(f"{FQ}.gold_match_groups").count())

# COMMAND ----------

# MAGIC %md ## 7. Quick evaluation vs gold_ground_truth (full eval is Phase 4)

# COMMAND ----------

gt = spark.table(f"{FQ}.gold_ground_truth")
m = spark.table(f"{FQ}.gold_match_group_members").select("part_id", "group_id")

# duplicate recall: base & variant land in the same group
dup = gt.where("relationship='duplicate'")
mg = m.withColumnRenamed("part_id","pid").withColumnRenamed("group_id","gid")
base_g = dup.join(mg, dup.base_part_id == mg.pid).select(dup.base_part_id, dup.variant_part_id, F.col("gid").alias("gb"))
both = base_g.join(mg, base_g.variant_part_id == mg.pid).select("base_part_id","variant_part_id","gb", F.col("gid").alias("gv"))
recovered = both.where("gb = gv").count()
total_dup = dup.count()
print(f"duplicate recall: {recovered}/{total_dup} = {recovered/total_dup:.3f}")

# hard-negative violations: base & variant wrongly in same group (should be ~0)
hn = gt.where("relationship='hard_negative'")
hb = hn.join(mg, hn.base_part_id == mg.pid).select(hn.base_part_id, hn.variant_part_id, F.col("gid").alias("gb"))
hboth = hb.join(mg, hb.variant_part_id == mg.pid).select("gb", F.col("gid").alias("gv"))
print("hard-negative violations (want 0):", hboth.where("gb = gv").count())

# near-miss violations: excluded by blocking, should be 0
nm = gt.where("relationship='near_miss'")
nb = nm.join(mg, nm.base_part_id == mg.pid).select(nm.base_part_id, nm.variant_part_id, F.col("gid").alias("gb"))
nboth = nb.join(mg, nb.variant_part_id == mg.pid).select("gb", F.col("gid").alias("gv"))
print("near-miss violations (want 0):", nboth.where("gb = gv").count())

print("total groups:", spark.table(f"{FQ}.gold_match_groups").count(),
      "| total grouped parts:", spark.table(f"{FQ}.gold_match_group_members").count())

spark.sql(f"DROP TABLE IF EXISTS {FQ}.tmp_match_pairs")
