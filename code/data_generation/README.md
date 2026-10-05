# Data generation (Phase 2)

Generates the synthetic catalog for AI Parts Wizard — spec §4. Deterministic
(hash-derived), so re-running reproduces the same data and the ground-truth labels stay
consistent.

## What it produces

Into `<catalog>.<schema>` (job parameters; default schema `ai_parts_wizard`):

| Table | ~Rows | Notes |
|---|---|---|
| `silver_plants` | 4 | Harvesters: `HV0` North, `HV1` South · Tractors: `TR0` East, `TR1` West (`… Harvester/Tractor Works`). |
| `silver_models` | 16 | 4 per plant; plant-linked ids, e.g. `HV0_M001`. |
| `silver_suppliers` | 200 | `Supplier 0` … `Supplier 199`, five regions (North/South/East/West/Central). |
| `silver_parts` | ~200K | ~185K base + seeded variants, ~25K per category across the 8 categories. Each part has an `annual_volume` (units/yr). |
| `silver_supplier_catalogs` | ~400K | 1–3 offers/part in **USD** with price + lead-time spread (so duplicates show savings). |
| `gold_ground_truth` | ~15K | Seeded relationships for evaluation (§9.5, §1.4). |

## Seeded ground truth (labels in `gold_ground_truth`)

- **duplicate** (~9.3K) — same physical part re-emitted in a different model (varied span:
  cross-model / cross-type / cross-plant) under a new `part_number`. *Should match.*
- **hard_negative** (~3.8K) — identical geometry, one functional discriminator changed
  (e.g. bolt `thread_pitch`, hose `pressure_rating`). *Should NOT match.*
- **near_miss** (~2K) — identical geometry, different `material`. *Excluded by blocking.*

Variant `part_id`s use suffixes `-D` / `-H` / `-N`; labels are derived from that convention.

## Design notes

- Dimensional & functional attributes are drawn from **continuous ranges** (fine
  resolution), so two independent parts almost never coincide — coincidental duplicates
  ≈ 0. Seeded duplicates are the same part re-emitted with **±1% jitter**, so matching is
  tested as *near*-duplicate detection. **Expected matches ≈ the ~9.3K seeded duplicate
  pairs** (not the whole catalog).
- `part_number` is intentionally **reused** across parts/models (not globally unique) to
  exercise the join-safety rule (§3.1) — up to ~10 parts can share one number.
- Blocking keys `part_category` + `material` are always populated.
- **Pricing (USD)** — per-category list-price range interpolated log-wise by the part's size
  rank (weight percentile within its category) × a material multiplier, then ±20% per supplier
  offer. Typical ranges: bolts ~$0.30–9, seals ~$0.60–28, gaskets ~$2.50–85, pins/shafts
  ~$4–160, hoses ~$18–250, bushings/bearings ~$6–320, wire/cable ~$8–340, brackets ~$12–420.
- **Annual volume** — log-uniform per category: bolts and seals 20–2,000 units/yr, gaskets
  10–600, everything else 5–400. Seeded duplicates get their own volume (each model buys its
  own copy). Savings = (member best unit price − group best unit price) × annual volume.

## Run

Deployed and run by `deploy/deploy.sh` (`notebooks` imports it, `data` runs it as a serverless
job with the `catalog` / `schema` parameters). To run it by hand, import it and submit a job:

```bash
databricks workspace import <dir>/generate_sample_data --file generate_sample_data.py --language PYTHON --format SOURCE --overwrite -p <profile>
databricks jobs submit -p <profile> --json '{"run_name":"apw_generate_sample_data","tasks":[{"task_key":"main",
  "notebook_task":{"notebook_path":"<dir>/generate_sample_data","base_parameters":{"catalog":"<catalog>","schema":"ai_parts_wizard"}}}]}'
```


`../data_model/run_sql.py` remains available for ad-hoc SQL (e.g. verification queries)
against a SQL warehouse.
