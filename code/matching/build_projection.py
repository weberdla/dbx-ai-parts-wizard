# Databricks notebook source
# MAGIC %md
# MAGIC # AI Parts Wizard — 3D Projection of Part Vectors (v2)
# MAGIC
# MAGIC Projects the 21-dim normalized feature vectors in `gold_part_features` (the same vectors
# MAGIC the `part_features_vs_index` Vector Search index serves) down to 3D, so the app can show
# MAGIC duplicate parts as visible clusters.
# MAGIC
# MAGIC Two scopes, two methods:
# MAGIC - **global**: a capped sample of the whole catalog (all grouped + ground-truth-labeled parts,
# MAGIC   topped up with ungrouped parts). Mostly shows category islands.
# MAGIC - **block**: one projection per `(part_category, material)` block, the space the matcher
# MAGIC   actually searches. This is where duplicate groups show up as tight knots.
# MAGIC - **umap** (euclidean, to match the matcher's L2) and **pca** (linear, distance-honest baseline).
# MAGIC
# MAGIC Outputs:
# MAGIC - `gold_part_projection (scope, block_key, method, part_id, x, y, z)` — coords scaled to ~[-1, 1]
# MAGIC   per (scope, block, method) so the app camera is consistent.
# MAGIC - `gold_part_viz_attrs` — one row per part with display attributes, group, savings,
# MAGIC   ground-truth label and the feature vector (JSON) for live Vector Search queries.

# COMMAND ----------

# MAGIC %pip install umap-learn==0.5.7 --quiet

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

import json
import time

import numpy as np
import pandas as pd
from sklearn.decomposition import PCA
import umap

dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema", "ai_parts_wizard")
dbutils.widgets.text("global_max_points", "75000")
# Seeded UMAP is single-threaded (much slower). Turn on once the picture is final for a demo.
dbutils.widgets.dropdown("deterministic", "false", ["true", "false"])
CATALOG = dbutils.widgets.get("catalog")
SCHEMA = dbutils.widgets.get("schema")
GLOBAL_MAX = int(dbutils.widgets.get("global_max_points"))
DETERMINISTIC = dbutils.widgets.get("deterministic") == "true"
assert CATALOG, "catalog is a required job parameter"
FQ = f"{CATALOG}.{SCHEMA}"

SEED = 42            # sampling + PCA always seeded; UMAP only when DETERMINISTIC
MIN_BLOCK_UMAP = 30  # tiny blocks get PCA only

# COMMAND ----------

# MAGIC %md ## 1. Load vectors + display attributes

# COMMAND ----------

attrs_sdf = spark.sql(f"""
WITH gt AS (
  SELECT variant_part_id AS part_id, relationship AS gt_label FROM {FQ}.gold_ground_truth
  UNION ALL
  SELECT DISTINCT base_part_id AS part_id, 'base' AS gt_label FROM {FQ}.gold_ground_truth
),
gt1 AS (  -- a part can be both a base and a variant; prefer the variant label
  SELECT part_id, min_by(gt_label, CASE WHEN gt_label = 'base' THEN 1 ELSE 0 END) AS gt_label
  FROM gt GROUP BY part_id
)
SELECT f.part_id, p.part_number, p.description, f.part_category, f.material,
       p.model_id, m.plant_id, m.machine_type,
       mm.group_id, g.savings_potential AS group_savings, g.member_count AS group_size,
       gt1.gt_label,
       f.feature_vector
FROM {FQ}.gold_part_features f
JOIN {FQ}.silver_parts p ON p.part_id = f.part_id
JOIN {FQ}.silver_models m ON m.model_id = p.model_id
LEFT JOIN {FQ}.gold_match_group_members mm ON mm.part_id = f.part_id
LEFT JOIN {FQ}.gold_match_groups g ON g.group_id = mm.group_id
LEFT JOIN gt1 ON gt1.part_id = f.part_id
""")
pdf = attrs_sdf.toPandas()
X_all = np.vstack(pdf["feature_vector"].to_numpy()).astype(np.float32)
pdf["block_key"] = pdf["part_category"] + "|" + pdf["material"]
print(f"parts: {len(pdf):,}  dims: {X_all.shape[1]}  blocks: {pdf['block_key'].nunique()}")
print(f"grouped parts: {pdf['group_id'].notna().sum():,}  gt-labeled: {pdf['gt_label'].notna().sum():,}")

# COMMAND ----------

# MAGIC %md ## 2. Projection helpers

# COMMAND ----------

def scale_unit(coords: np.ndarray) -> np.ndarray:
    """Center and scale so the 99th-percentile radius is ~1 (robust to a few outliers)."""
    c = coords - np.median(coords, axis=0)
    r = np.percentile(np.linalg.norm(c, axis=1), 99) or 1.0
    return (c / r).astype(np.float32)


def project(X: np.ndarray, method: str, n_neighbors: int = 15, min_dist: float = 0.05) -> np.ndarray:
    if method == "pca":
        k = min(3, X.shape[0], X.shape[1])
        out = PCA(n_components=k, random_state=SEED).fit_transform(X)
        if k < 3:  # degenerate tiny block — pad to 3D
            out = np.hstack([out, np.zeros((out.shape[0], 3 - k))])
        return scale_unit(out)
    reducer = umap.UMAP(
        n_components=3, metric="euclidean", n_neighbors=min(n_neighbors, X.shape[0] - 1),
        min_dist=min_dist, random_state=SEED if DETERMINISTIC else None, low_memory=True,
    )
    return scale_unit(reducer.fit_transform(X))


out_frames = []

def collect(scope, block_key, method, part_ids, coords):
    out_frames.append(pd.DataFrame({
        "scope": scope, "block_key": block_key, "method": method, "part_id": part_ids,
        "x": coords[:, 0], "y": coords[:, 1], "z": coords[:, 2],
    }))

# COMMAND ----------

# MAGIC %md ## 3. Global scope (capped sample)
# MAGIC Keep every grouped and ground-truth-labeled part (they carry the story), then top up with
# MAGIC ungrouped parts sampled per block so every category is represented.

# COMMAND ----------

must = pdf["group_id"].notna() | pdf["gt_label"].notna()
rng = np.random.default_rng(SEED)
story = pdf.index[must]
story_cap = int(GLOBAL_MAX * 0.6)  # leave room for ungrouped parts so the "no duplicate" context shows
if len(story) > story_cap:
    story = pd.Index(rng.choice(story, story_cap, replace=False))
room = GLOBAL_MAX - len(story)
rest = pdf[~must]
frac = min(1.0, room / max(1, len(rest)))
topup = rest.groupby("block_key", group_keys=False).apply(lambda d: d.sample(frac=frac, random_state=SEED))
keep_idx = story.union(topup.index)
g_ids = pdf.loc[keep_idx, "part_id"].to_numpy()
Xg = X_all[keep_idx]
print(f"global sample: {len(g_ids):,} parts")

for method in ("pca", "umap"):
    t = time.time()
    # Wider neighborhood for the global view so category islands keep some structure.
    collect("global", "global", method, g_ids, project(Xg, method, n_neighbors=30, min_dist=0.1))
    print(f"  global {method}: {time.time() - t:.0f}s")

# COMMAND ----------

# MAGIC %md ## 4. Block scope — one projection per (category, material)

# COMMAND ----------

t0 = time.time()
for bk, d in pdf.groupby("block_key"):
    Xb = X_all[d.index]
    ids = d["part_id"].to_numpy()
    if len(d) < 4:
        continue
    collect("block", bk, "pca", ids, project(Xb, "pca"))
    if len(d) >= MIN_BLOCK_UMAP:
        # Small neighborhood + tight min_dist: duplicates (L2 < 0.12) collapse into visible knots.
        collect("block", bk, "umap", ids, project(Xb, "umap", n_neighbors=15, min_dist=0.02))
print(f"blocks done in {time.time() - t0:.0f}s")

# COMMAND ----------

# MAGIC %md ## 5. Write Delta

# COMMAND ----------

proj = pd.concat(out_frames, ignore_index=True)
spark.createDataFrame(proj).write.mode("overwrite").option("overwriteSchema", "true") \
    .saveAsTable(f"{FQ}.gold_part_projection")
spark.sql(f"COMMENT ON TABLE {FQ}.gold_part_projection IS "
          "'3D projections (UMAP/PCA) of gold_part_features, global sample + per (category, material) block. v2 viz.'")

attrs = pdf.drop(columns=["feature_vector"]).copy()
attrs["feature_vector_json"] = [json.dumps([round(float(v), 6) for v in row]) for row in X_all]
spark.createDataFrame(attrs).write.mode("overwrite").option("overwriteSchema", "true") \
    .saveAsTable(f"{FQ}.gold_part_viz_attrs")
spark.sql(f"COMMENT ON TABLE {FQ}.gold_part_viz_attrs IS "
          "'Per-part display attributes + feature vector (JSON) for the v2 3D view and live Vector Search lookups.'")

display(spark.sql(f"""
SELECT scope, method, count(DISTINCT block_key) AS blocks, count(*) AS points
FROM {FQ}.gold_part_projection GROUP BY ALL ORDER BY ALL"""))
