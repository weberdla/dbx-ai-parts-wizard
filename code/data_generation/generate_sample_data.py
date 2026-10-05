# Databricks notebook source
# MAGIC %md
# MAGIC # AI Parts Wizard — Sample Data Generation (Phase 2)
# MAGIC
# MAGIC Deterministic (hash-derived) generation into
# MAGIC `<catalog>.<schema>` (job parameters). See spec §4.
# MAGIC
# MAGIC **Design (v2):** dimensional & functional attributes are drawn from **continuous
# MAGIC ranges** (fine resolution) rather than a few discrete sizes, so two independent parts
# MAGIC almost never coincide — coincidental duplicates ≈ 0. Seeded duplicates are the same
# MAGIC part re-emitted with **±1% jitter** (manufacturing/measurement noise), so matching is
# MAGIC tested as *near*-duplicate detection. Expected matches ≈ the seeded duplicate pairs.

# COMMAND ----------

# Target location — passed as job parameters (see DEPLOY.md).
dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema", "ai_parts_wizard")
CATALOG = dbutils.widgets.get("catalog")
SCHEMA = dbutils.widgets.get("schema")
assert CATALOG, "catalog is a required job parameter"
FQ = f"{CATALOG}.{SCHEMA}"
N_BASE = 185000  # base parts before seeded variants

# COMMAND ----------

# MAGIC %md ## Build the per-category attribute SQL (continuous ranges)

# COMMAND ----------

# --- Plants & models -------------------------------------------------------
# Plant ids: HV0/HV1 harvesters, TR0/TR1 tractors. model_id is plant-linked, e.g. HV0_M001.
PLANTS = [
    ('HV0', 'North Harvester Works', 'Northern Region', 'harvester'),
    ('HV1', 'South Harvester Works', 'Southern Region', 'harvester'),
    ('TR0', 'East Tractor Works',    'Eastern Region',  'tractor'),
    ('TR1', 'West Tractor Works',    'Western Region',  'tractor'),
]
MODELS_PER_PLANT = 4
SERIES = ['Field', 'Ranger', 'Pro', 'Max']
MODELS = []  # (model_id, plant_id, machine_type, model_name)
for _pid, _pname, _loc, _focus in PLANTS:
    _machine = 'Harvester' if _pid.startswith('HV') else 'Tractor'
    for _n in range(1, MODELS_PER_PLANT + 1):
        MODELS.append((f"{_pid}_M{_n:03d}", _pid, _machine, f"{_machine} {SERIES[_n-1]} v{(_n % 3) + 1}"))

N_MODELS = len(MODELS)
MODEL_ARRAY = "array(" + ",".join(f"'{m[0]}'" for m in MODELS) + ")"
PLANTS_VALUES = ",\n  ".join(f"('{p}','{n}','{l}','{f}')" for p, n, l, f in PLANTS)
MODELS_VALUES = ",\n  ".join(f"('{mid}','{pid}','{mt}','{mn}')" for mid, pid, mt, mn in MODELS)

CATEGORIES = ['Bolt','Pin/Shaft','Hose','Bushing/Bearing','Gasket','Bracket/Plate','Wire/Cable','Seal/O-ring']

# nullable feature columns, in table order
NULLABLE_COLS = ['length','width','thickness','diameter','inner_diameter','outer_diameter',
    'nominal_diameter','cross_section_diameter','head_width','gauge','thread_pitch',
    'tensile_strength','hardness','pressure_rating','load_rating','temperature_rating',
    'hole_count','voltage_rating','conductor_count']
INT_COLS = {'hole_count','conductor_count'}

# per category: column -> (lo, hi, precision) continuous, or ('int', lo, hi). '_wall' is
# internal (feeds outer_diameter). head_width is derived from nominal_diameter.
SPECS = {
  'Bolt':            {'nominal_diameter':(5,24,1),'length':(15,120,1),'thread_pitch':(0.8,3.0,2),'tensile_strength':(350,1300,0)},
  'Pin/Shaft':       {'diameter':(4,28,1),'length':(25,220,1),'hardness':(25,62,0)},
  'Hose':            {'inner_diameter':(5,35,1),'_wall':(3,8,1),'length':(400,3200,0),'pressure_rating':(40,360,0)},
  'Bushing/Bearing': {'inner_diameter':(8,45,1),'_wall':(6,18,1),'width':(6,20,1),'load_rating':(4,45,1)},
  'Gasket':          {'inner_diameter':(18,110,1),'_wall':(8,35,1),'thickness':(0.8,3.5,2),'temperature_rating':(100,420,0)},
  'Bracket/Plate':   {'length':(45,220,1),'width':(25,110,1),'thickness':(2.5,11,1),'hole_count':('int',2,8)},
  'Wire/Cable':      {'length':(800,11000,0),'gauge':(0.4,4.5,2),'voltage_rating':(250,1100,0),'conductor_count':('int',1,5)},
  'Seal/O-ring':     {'inner_diameter':(4,45,1),'cross_section_diameter':(1.2,4.0,2),'hardness':(55,95,0)},
}

def gen_expr(cidx, col, spec):
    """Deterministic value for a column from the row id (continuous or small int)."""
    if isinstance(spec[0], str) and spec[0] == 'int':
        _, lo, hi = spec
        return f"CAST({lo} + pmod(hash(id,'{cidx}_{col}'), {hi-lo+1}) AS INT)"
    lo, hi, prec = spec
    return f"round({lo} + (pmod(hash(id,'{cidx}_{col}'),100000)/100000.0)*({hi-lo}), {prec})"

col_cases = {c: [] for c in NULLABLE_COLS}
for cidx, cat in enumerate(CATEGORIES):
    sp = SPECS[cat]
    for col, spec in sp.items():
        if col == '_wall':
            continue
        col_cases[col].append((cidx, gen_expr(cidx, col, spec)))
    if '_wall' in sp and 'inner_diameter' in sp:  # outer_diameter = inner + wall
        inner = gen_expr(cidx, 'inner_diameter', sp['inner_diameter'])
        wall = gen_expr(cidx, '_wall', sp['_wall'])
        col_cases['outer_diameter'].append((cidx, f"round(({inner}) + ({wall}), 1)"))
    if 'nominal_diameter' in sp:                  # head_width = nominal * 1.6
        nom = gen_expr(cidx, 'nominal_diameter', sp['nominal_diameter'])
        col_cases['head_width'].append((cidx, f"round(({nom})*1.6, 2)"))

def col_sql(col):
    cases = col_cases[col]
    typ = 'INT' if col in INT_COLS else 'DOUBLE'
    if not cases:
        return f"CAST(NULL AS {typ}) AS {col}"
    whens = " ".join(f"WHEN {cidx} THEN {e}" for cidx, e in cases)
    return f"CASE ci {whens} ELSE NULL END AS {col}"

COLS_SQL = ",\n    ".join(col_sql(c) for c in NULLABLE_COLS)

DENSITY = """CASE material
  WHEN 'Steel' THEN 7.85 WHEN 'Stainless Steel' THEN 8.0 WHEN 'Alloy Steel' THEN 7.85
  WHEN 'Titanium' THEN 4.5 WHEN 'Rubber' THEN 1.2 WHEN 'PTFE' THEN 2.2 WHEN 'Nylon' THEN 1.15
  WHEN 'Bronze' THEN 8.8 WHEN 'Brass' THEN 8.5 WHEN 'Cork' THEN 0.24 WHEN 'Graphite' THEN 1.8
  WHEN 'Aluminum' THEN 2.7 WHEN 'Copper' THEN 8.96 WHEN 'Nitrile' THEN 1.0 WHEN 'Viton' THEN 1.8
  WHEN 'Silicone' THEN 1.1 WHEN 'Silver' THEN 10.49 WHEN 'Inconel' THEN 8.44 ELSE 5.0 END"""

# ±1% jitter for seeded duplicates (doubles only; ints copied unchanged)
def jitter(col):
    if col in INT_COLS:
        return col
    return f"round({col} * (1 + (pmod(hash(part_id,'j_{col}'),41)-20)/2000.0), 3) AS {col}"

DUP_COLS_SQL = ", ".join(jitter(c) for c in NULLABLE_COLS)
WEIGHT_JITTER = "round(weight * (1 + (pmod(hash(part_id,'j_weight'),41)-20)/2000.0), 3)"
print("SQL builders ready")

# COMMAND ----------

# MAGIC %md ## Clear existing data (idempotent)

# COMMAND ----------

for t in ["silver_supplier_catalogs", "silver_parts", "silver_suppliers",
          "silver_models", "silver_plants", "gold_ground_truth"]:
    spark.sql(f"TRUNCATE TABLE {FQ}.{t}")

# COMMAND ----------

# MAGIC %md ## Plants (HV0/HV1 harvesters, TR0/TR1 tractors) & Models (4 per plant, e.g. HV0_M001)

# COMMAND ----------

spark.sql(f"INSERT INTO {FQ}.silver_plants VALUES\n  {PLANTS_VALUES}")
spark.sql(f"INSERT INTO {FQ}.silver_models VALUES\n  {MODELS_VALUES}")

# COMMAND ----------

# MAGIC %md ## Suppliers (200)

# COMMAND ----------

spark.sql(f"""
INSERT INTO {FQ}.silver_suppliers
SELECT concat('S', lpad(cast(id AS STRING), 3, '0')),
       concat('Supplier ', cast(id AS STRING)),
       element_at(array('North','South','East','West','Central'), pmod(cast(id AS INT),5)+1)
FROM range(0, 200)
""")

# COMMAND ----------

# MAGIC %md ## Base parts (~185K) — continuous attributes; `description` filled later

# COMMAND ----------

spark.sql(f"""
INSERT INTO {FQ}.silver_parts
WITH raw AS (
  SELECT id, pmod(cast(id AS INT),8) AS ci,
    element_at(array('Bolt','Pin/Shaft','Hose','Bushing/Bearing','Gasket','Bracket/Plate','Wire/Cable','Seal/O-ring'), pmod(cast(id AS INT),8)+1) AS part_category,
    CASE pmod(cast(id AS INT), 8)
      WHEN 0 THEN element_at(array('Steel','Stainless Steel','Alloy Steel','Titanium'), pmod(hash(id,3),4)+1)
      WHEN 1 THEN element_at(array('Steel','Alloy Steel','Titanium'), pmod(hash(id,3),3)+1)
      WHEN 2 THEN element_at(array('Rubber','PTFE','Nylon'), pmod(hash(id,3),3)+1)
      WHEN 3 THEN element_at(array('Bronze','Steel','Brass'), pmod(hash(id,3),3)+1)
      WHEN 4 THEN element_at(array('Rubber','Cork','Graphite','PTFE'), pmod(hash(id,3),4)+1)
      WHEN 5 THEN element_at(array('Steel','Stainless Steel','Aluminum'), pmod(hash(id,3),3)+1)
      WHEN 6 THEN element_at(array('Copper','Aluminum'), pmod(hash(id,3),2)+1)
      WHEN 7 THEN element_at(array('Nitrile','Viton','Silicone'), pmod(hash(id,3),3)+1)
    END AS material,
    element_at({MODEL_ARRAY}, pmod(hash(id,201),{N_MODELS})+1) AS model_id,
    concat(element_at(array('BLT','PIN','HOS','BSH','GSK','BRK','WIR','SEL'), pmod(cast(id AS INT),8)+1),
           '-', lpad(cast(pmod(cast(id AS INT),20000) AS STRING), 5, '0')) AS part_number,
    {COLS_SQL}
  FROM range(0, {N_BASE})
),
raw2 AS (SELECT *, {DENSITY} AS material_density FROM raw)
SELECT
  concat('P', lpad(cast(id AS STRING), 7, '0')) AS part_id,
  model_id, part_number, part_category, material, material_density,
  round(material_density
        * greatest(coalesce(length, outer_diameter, diameter, inner_diameter, 10.0), 1.0)
        * greatest(coalesce(width, thickness, cross_section_diameter, gauge, head_width, 5.0), 1.0)
        / 1000.0, 3) AS weight,
  CAST(NULL AS STRING) AS description,
  length, width, thickness, diameter, inner_diameter, outer_diameter, nominal_diameter,
  cross_section_diameter, head_width, gauge, thread_pitch, tensile_strength, hardness,
  pressure_rating, load_rating, temperature_rating, hole_count, voltage_rating, conductor_count,
  CAST(NULL AS STRING) AS normalized_part_id,
  CAST(NULL AS INT) AS annual_volume
FROM raw2
""")

# COMMAND ----------

# MAGIC %md ## Seeded DUPLICATES (~5%): same part in a different model, ±1% jitter

# COMMAND ----------

spark.sql(f"""
INSERT INTO {FQ}.silver_parts
SELECT
  concat(part_id, '-D'),
  element_at({MODEL_ARRAY}, CAST(pmod((array_position({MODEL_ARRAY}, model_id) - 1) + 1 + pmod(hash(part_id,'vm'), {N_MODELS-1}), {N_MODELS}) + 1 AS INT)),
  concat(part_number, 'D'), part_category, material, material_density,
  {WEIGHT_JITTER}, CAST(NULL AS STRING),
  {DUP_COLS_SQL},
  CAST(NULL AS STRING), CAST(NULL AS INT)
FROM {FQ}.silver_parts
WHERE part_id NOT LIKE '%-%' AND pmod(hash(part_id), 20) = 0
""")

# COMMAND ----------

# MAGIC %md ## Seeded FUNCTIONAL HARD-NEGATIVES (~2%): identical geometry, one functional value changed

# COMMAND ----------

spark.sql(f"""
INSERT INTO {FQ}.silver_parts
SELECT
  concat(part_id, '-H'), model_id, concat(part_number, 'H'), part_category, material,
  material_density, weight, CAST(NULL AS STRING),
  length, width, thickness, diameter, inner_diameter, outer_diameter, nominal_diameter,
  cross_section_diameter, head_width, gauge,
  CASE WHEN part_category='Bolt' THEN round(thread_pitch*1.6,3) ELSE thread_pitch END,
  tensile_strength,
  CASE WHEN part_category IN ('Pin/Shaft','Seal/O-ring') THEN round(hardness*1.4,1) ELSE hardness END,
  CASE WHEN part_category='Hose' THEN round(pressure_rating*1.5,1) ELSE pressure_rating END,
  CASE WHEN part_category='Bushing/Bearing' THEN round(load_rating*1.5,1) ELSE load_rating END,
  CASE WHEN part_category='Gasket' THEN round(temperature_rating*1.5,1) ELSE temperature_rating END,
  CASE WHEN part_category='Bracket/Plate' THEN hole_count+2 ELSE hole_count END,
  CASE WHEN part_category='Wire/Cable' THEN voltage_rating*2 ELSE voltage_rating END,
  conductor_count, CAST(NULL AS STRING), CAST(NULL AS INT)
FROM {FQ}.silver_parts
WHERE part_id NOT LIKE '%-%' AND pmod(hash(part_id,'hn'), 50) = 0
""")

# COMMAND ----------

# MAGIC %md ## Seeded CROSS-MATERIAL NEAR-MISSES (~1%): identical geometry, different material

# COMMAND ----------

spark.sql(f"""
INSERT INTO {FQ}.silver_parts
SELECT
  concat(part_id, '-N'), model_id, concat(part_number, 'N'), part_category,
  CASE part_category
    WHEN 'Bolt' THEN 'Brass' WHEN 'Pin/Shaft' THEN 'Brass' WHEN 'Hose' THEN 'Silicone'
    WHEN 'Bushing/Bearing' THEN 'Nylon' WHEN 'Gasket' THEN 'Steel' WHEN 'Bracket/Plate' THEN 'Brass'
    WHEN 'Wire/Cable' THEN 'Silver' WHEN 'Seal/O-ring' THEN 'PTFE'
  END,
  CASE part_category
    WHEN 'Bolt' THEN 8.5 WHEN 'Pin/Shaft' THEN 8.5 WHEN 'Hose' THEN 1.1
    WHEN 'Bushing/Bearing' THEN 1.15 WHEN 'Gasket' THEN 7.85 WHEN 'Bracket/Plate' THEN 8.5
    WHEN 'Wire/Cable' THEN 10.49 WHEN 'Seal/O-ring' THEN 2.2
  END,
  weight, CAST(NULL AS STRING),
  length, width, thickness, diameter, inner_diameter, outer_diameter, nominal_diameter,
  cross_section_diameter, head_width, gauge, thread_pitch, tensile_strength, hardness,
  pressure_rating, load_rating, temperature_rating, hole_count, voltage_rating, conductor_count,
  CAST(NULL AS STRING), CAST(NULL AS INT)
FROM {FQ}.silver_parts
WHERE part_id NOT LIKE '%-%' AND pmod(hash(part_id,'nm'), 100) = 0
""")

# COMMAND ----------

# MAGIC %md ## Fill `description` for every part (base + variants) from its own columns

# COMMAND ----------

spark.sql(f"""
UPDATE {FQ}.silver_parts SET description = concat_ws(', ',
  concat(material, ' ', part_category),
  CASE part_category
    WHEN 'Bolt' THEN concat('M', cast(round(nominal_diameter,1) AS STRING), ' x ', cast(cast(length AS INT) AS STRING), ' mm, pitch ', cast(thread_pitch AS STRING), ' mm, ', cast(cast(tensile_strength AS INT) AS STRING), ' MPa')
    WHEN 'Pin/Shaft' THEN concat('dia ', cast(round(diameter,1) AS STRING), ' x ', cast(cast(length AS INT) AS STRING), ' mm, ', cast(cast(hardness AS INT) AS STRING), ' HRC')
    WHEN 'Hose' THEN concat('ID ', cast(round(inner_diameter,1) AS STRING), ' / OD ', cast(round(outer_diameter,1) AS STRING), ' x ', cast(cast(length AS INT) AS STRING), ' mm, ', cast(cast(pressure_rating AS INT) AS STRING), ' bar')
    WHEN 'Bushing/Bearing' THEN concat('ID ', cast(round(inner_diameter,1) AS STRING), ' / OD ', cast(round(outer_diameter,1) AS STRING), ' x ', cast(round(width,1) AS STRING), ' mm, ', cast(cast(load_rating AS INT) AS STRING), ' kN')
    WHEN 'Gasket' THEN concat('ID ', cast(round(inner_diameter,1) AS STRING), ' / OD ', cast(round(outer_diameter,1) AS STRING), ' x ', cast(thickness AS STRING), ' mm, ', cast(cast(temperature_rating AS INT) AS STRING), ' C')
    WHEN 'Bracket/Plate' THEN concat(cast(round(length,1) AS STRING), ' x ', cast(round(width,1) AS STRING), ' x ', cast(thickness AS STRING), ' mm, ', cast(hole_count AS STRING), ' holes')
    WHEN 'Wire/Cable' THEN concat(cast(gauge AS STRING), ' mm2 x ', cast(cast(length AS INT) AS STRING), ' mm, ', cast(cast(voltage_rating AS INT) AS STRING), ' V, ', cast(conductor_count AS STRING), ' cond')
    WHEN 'Seal/O-ring' THEN concat('ID ', cast(round(inner_diameter,1) AS STRING), ' x CS ', cast(cross_section_diameter AS STRING), ' mm, ', cast(cast(hardness AS INT) AS STRING), ' Shore A')
  END,
  concat('PN ', part_number))
""")

# COMMAND ----------

# MAGIC %md ## Annual purchase volume (units/year) for every part
# MAGIC Log-uniform within a per-category range (fasteners and seals are bought in far larger
# MAGIC quantities than brackets or hoses). Each part — including seeded duplicates — gets its
# MAGIC own volume, since each model buys its own copy. Savings are price gap × annual volume.

# COMMAND ----------

spark.sql(f"""
UPDATE {FQ}.silver_parts SET annual_volume = CAST(round(
  CASE part_category
    WHEN 'Bolt' THEN 20 WHEN 'Seal/O-ring' THEN 20 WHEN 'Gasket' THEN 10 ELSE 5 END
  * power(
      CASE part_category
        WHEN 'Bolt' THEN 100.0 WHEN 'Seal/O-ring' THEN 100.0 WHEN 'Gasket' THEN 60.0 ELSE 80.0 END,
      pmod(hash(part_id,'vol'),100000)/100000.0)
  ) AS INT)
""")

# COMMAND ----------

# MAGIC %md ## Ground-truth labels (from the -D/-H/-N suffix convention)

# COMMAND ----------

spark.sql(f"""
INSERT INTO {FQ}.gold_ground_truth
SELECT substring(part_id, 1, length(part_id) - 2), part_id,
  CASE right(part_id, 2) WHEN '-D' THEN 'duplicate' WHEN '-H' THEN 'hard_negative' WHEN '-N' THEN 'near_miss' END,
  part_category
FROM {FQ}.silver_parts
WHERE part_id RLIKE '-[DHN]$'
""")

# COMMAND ----------

# MAGIC %md ## Supplier catalogs (1-3 offers/part, USD, with price + lead-time spread)
# MAGIC List price = per-category USD range, interpolated log-scale by the part's size rank
# MAGIC within its category (weight percentile), times a material multiplier. Each supplier offer
# MAGIC then varies ±20% around list, so duplicates bought from different suppliers show gaps.

# COMMAND ----------

spark.sql(f"""
INSERT INTO {FQ}.silver_supplier_catalogs
WITH sized AS (
  SELECT part_id, part_category, material,
         percent_rank() OVER (PARTITION BY part_category ORDER BY weight) AS size_pct
  FROM {FQ}.silver_parts
),
listed AS (
  SELECT part_id,
    CASE part_category
      WHEN 'Bolt' THEN 0.30 WHEN 'Pin/Shaft' THEN 4.0 WHEN 'Hose' THEN 18.0
      WHEN 'Bushing/Bearing' THEN 6.0 WHEN 'Gasket' THEN 2.5 WHEN 'Bracket/Plate' THEN 12.0
      WHEN 'Wire/Cable' THEN 8.0 WHEN 'Seal/O-ring' THEN 0.60 END
    * power(CASE part_category
      WHEN 'Bolt' THEN 30.0 WHEN 'Pin/Shaft' THEN 40.0 WHEN 'Hose' THEN 14.0
      WHEN 'Bushing/Bearing' THEN 53.0 WHEN 'Gasket' THEN 34.0 WHEN 'Bracket/Plate' THEN 35.0
      WHEN 'Wire/Cable' THEN 42.0 WHEN 'Seal/O-ring' THEN 47.0 END, size_pct)
    * CASE material
      WHEN 'Titanium' THEN 4.0 WHEN 'Stainless Steel' THEN 1.6 WHEN 'Alloy Steel' THEN 1.3
      WHEN 'Bronze' THEN 1.5 WHEN 'Brass' THEN 1.4 WHEN 'PTFE' THEN 2.2 WHEN 'Viton' THEN 2.5
      WHEN 'Silicone' THEN 1.6 WHEN 'Graphite' THEN 1.8 WHEN 'Silver' THEN 6.0
      WHEN 'Aluminum' THEN 0.9 WHEN 'Nylon' THEN 0.9 WHEN 'Cork' THEN 0.8 ELSE 1.0 END
    AS list_price
  FROM sized
)
SELECT
  concat('S', lpad(cast(pmod(hash(part_id, oi), 200) AS STRING), 3, '0')),
  part_id,
  round(list_price * (0.80 + pmod(hash(part_id,oi,'p'),41)/100.0), 2),
  round(pmod(hash(part_id,oi,'d'),15)/100.0, 2),
  element_at(array(7,14,21,30,45,60), pmod(hash(part_id,oi,'l'),6)+1),
  'USD',
  element_at(array('A','B','C'), pmod(hash(part_id,oi,'q'),3)+1)
FROM listed
  LATERAL VIEW explode(sequence(0, pmod(hash(part_id), 3))) o AS oi
""")

# COMMAND ----------

# MAGIC %md ## Verify

# COMMAND ----------

for t in ["silver_plants","silver_models","silver_suppliers","silver_parts","silver_supplier_catalogs","gold_ground_truth"]:
    print(f"{t:28}", spark.table(f"{FQ}.{t}").count())

# Coincidental exact-attribute collisions among BASE parts (want near 0)
coll = spark.sql(f"""
  SELECT count(*) AS colliding_base_parts FROM (
    SELECT count(*) c FROM {FQ}.silver_parts
    WHERE part_id NOT LIKE '%-%'
    GROUP BY part_category, material, length, width, thickness, diameter, inner_diameter,
             outer_diameter, nominal_diameter, cross_section_diameter, head_width, gauge,
             thread_pitch, tensile_strength, hardness, pressure_rating, load_rating,
             temperature_rating, hole_count, voltage_rating, conductor_count
    HAVING count(*) > 1)
""").collect()[0][0]
print("base parts sharing an identical feature tuple (want ~0):", coll)
display(spark.sql(f"SELECT part_category, description FROM {FQ}.silver_parts LIMIT 6"))
