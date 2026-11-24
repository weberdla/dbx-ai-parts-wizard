"""v2 3D view: projection points (Lakebase) + live nearest neighbors (Vector Search).

Projection coordinates are precomputed by code/matching/build_projection.py and synced to
Lakebase (part_projection, part_viz_attrs). Neighbor lookups query the Vector Search index
over gold_part_features with the clicked part's own vector, restricted to its
(category, material) block - the same space the batch matcher searches.
"""
import asyncio
import json
import math
import os
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import config
from .db import db

router = APIRouter(prefix="/api/viz")

VS_INDEX_NAME = os.environ.get("VS_INDEX_NAME", "")  # set in app.yaml
L2_THRESHOLD = 0.12  # matcher threshold (code/matching/build_matches.py)


def _round(v, n=4):
    return None if v is None else round(float(v), n)


@router.get("/blocks")
async def blocks():
    """(category, material) blocks with part / group counts and savings, biggest savings first."""
    rows = await db.fetch(
        """
        SELECT block_key, part_category, material,
               count(*) AS parts, count(DISTINCT group_id) AS groups
        FROM part_viz_attrs
        GROUP BY block_key, part_category, material
        """
    )
    # Savings per block: sum over distinct groups (computed separately to avoid double counting).
    sav = await db.fetch(
        """
        SELECT block_key, sum(group_savings) AS savings FROM (
          SELECT DISTINCT block_key, group_id, group_savings
          FROM part_viz_attrs WHERE group_id IS NOT NULL
        ) g GROUP BY block_key
        """
    )
    by_block = {r["block_key"]: r["savings"] for r in sav}
    out = [
        {"block_key": r["block_key"], "part_category": r["part_category"], "material": r["material"],
         "parts": r["parts"], "groups": r["groups"], "savings": float(by_block.get(r["block_key"]) or 0)}
        for r in rows
    ]
    out.sort(key=lambda r: r["savings"], reverse=True)
    return out


@router.get("/projection")
async def projection(scope: str = "global", block_key: Optional[str] = None, method: str = "umap"):
    """Columnar point payload for the 3D renderer.

    Categorical fields are dictionary-encoded (index into a lookup list) to keep the
    payload small; -1 means null.
    """
    if scope not in ("global", "block") or method not in ("umap", "pca"):
        raise HTTPException(400, "scope must be global|block, method umap|pca")
    bk = "global" if scope == "global" else block_key
    if not bk:
        raise HTTPException(400, "block_key required for scope=block")

    rows = await db.fetch(
        """
        SELECT p.part_id, p.x, p.y, p.z,
               a.part_number, a.part_category, a.material, a.plant_id, a.machine_type,
               a.group_id, a.group_savings, a.group_size, a.gt_label
        FROM part_projection p
        JOIN part_viz_attrs a ON a.part_id = p.part_id
        WHERE p.scope = $1 AND p.block_key = $2 AND p.method = $3
        """,
        scope, bk, method,
    )
    if not rows and method == "umap" and scope == "block":
        # Tiny blocks only have PCA.
        return await projection(scope, block_key, "pca")

    dicts: dict[str, list] = {k: [] for k in ("category", "material", "plant", "machine_type", "gt_label", "group")}
    index: dict[str, dict] = {k: {} for k in dicts}

    def enc(kind: str, val):
        if val is None:
            return -1
        m = index[kind]
        if val not in m:
            m[val] = len(dicts[kind])
            dicts[kind].append(val)
        return m[val]

    cols = {k: [] for k in ("part_id", "part_number", "x", "y", "z",
                            "category", "material", "plant", "machine_type", "gt_label", "group")}
    group_meta: dict[str, dict] = {}
    for r in rows:
        cols["part_id"].append(r["part_id"])
        cols["part_number"].append(r["part_number"])
        cols["x"].append(_round(r["x"]))
        cols["y"].append(_round(r["y"]))
        cols["z"].append(_round(r["z"]))
        cols["category"].append(enc("category", r["part_category"]))
        cols["material"].append(enc("material", r["material"]))
        cols["plant"].append(enc("plant", r["plant_id"]))
        cols["machine_type"].append(enc("machine_type", r["machine_type"]))
        cols["gt_label"].append(enc("gt_label", r["gt_label"]))
        cols["group"].append(enc("group", r["group_id"]))
        if r["group_id"] and r["group_id"] not in group_meta:
            group_meta[r["group_id"]] = {"savings": _round(r["group_savings"], 2), "size": r["group_size"]}

    return {
        "scope": scope, "block_key": bk, "method": method if rows else "pca", "count": len(rows),
        "columns": cols,
        "dicts": dicts,
        "groups": [{"group_id": g, **group_meta.get(g, {})} for g in dicts["group"]],
    }


def _vs_query(vector: list[float], category: str, material: str, k: int) -> list[str]:
    api = config.get_workspace_client().api_client
    res = api.do(
        "POST",
        f"/api/2.0/vector-search/indexes/{VS_INDEX_NAME}/query",
        body={
            "query_vector": vector,
            "columns": ["part_id"],
            "num_results": k + 1,  # +1: the part itself comes back first
            "filters_json": json.dumps({"part_category": category, "material": material}),
        },
    )
    return [row[0] for row in res.get("result", {}).get("data_array", []) or []]


@router.get("/parts/{part_id}/neighbors")
async def neighbors(part_id: str, k: int = 10):
    """Live top-K nearest neighbors from Vector Search, with exact L2 for each."""
    if not VS_INDEX_NAME:
        raise HTTPException(503, "VS_INDEX_NAME is not configured")
    k = max(1, min(k, 50))
    src = await db.fetch(
        "SELECT part_id, part_category, material, feature_vector_json FROM part_viz_attrs WHERE part_id = $1",
        part_id,
    )
    if not src:
        raise HTTPException(404, "part not found")
    s = src[0]
    vec = json.loads(s["feature_vector_json"])
    try:
        ids = await asyncio.to_thread(_vs_query, vec, s["part_category"], s["material"], k)
    except Exception as exc:
        raise HTTPException(502, f"Vector Search error: {exc}")
    ids = [i for i in ids if i != part_id][:k]
    if not ids:
        return {"part_id": part_id, "threshold": L2_THRESHOLD, "neighbors": []}

    rows = await db.fetch(
        """
        SELECT part_id, part_number, plant_id, group_id, gt_label, feature_vector_json
        FROM part_viz_attrs WHERE part_id = ANY($1::text[])
        """,
        ids,
    )
    by_id = {r["part_id"]: r for r in rows}
    out = []
    for nid in ids:  # keep Vector Search rank order
        r = by_id.get(nid)
        if not r:
            continue
        nv = json.loads(r["feature_vector_json"])
        l2 = math.sqrt(sum((a - b) ** 2 for a, b in zip(vec, nv)))
        out.append({"part_id": nid, "part_number": r["part_number"], "plant_id": r["plant_id"],
                    "group_id": r["group_id"], "gt_label": r["gt_label"], "l2": round(l2, 4),
                    "is_duplicate": l2 <= L2_THRESHOLD})
    return {"part_id": part_id, "threshold": L2_THRESHOLD, "neighbors": out}


class LocateBody(BaseModel):
    group_ids: list[str] = []
    part_ids: list[str] = []
    part_numbers: list[str] = []


@router.post("/locate")
async def locate(body: LocateBody):
    """Resolve ids coming from the queue, group drawer or a Genie answer to map points.

    Returns the matching part_ids, plus the (category, material) blocks they fall in so the
    client can open a single block when everything lives in one, or the global view otherwise.
    """
    g = [x for x in body.group_ids if x][:500]
    p = [x for x in body.part_ids if x][:2000]
    n = [x for x in body.part_numbers if x][:2000]
    if not (g or p or n):
        return {"part_ids": [], "group_ids": [], "blocks": []}
    rows = await db.fetch(
        """
        SELECT part_id, group_id, block_key FROM part_viz_attrs
        WHERE group_id = ANY($1::text[]) OR part_id = ANY($2::text[]) OR part_number = ANY($3::text[])
        LIMIT 5000
        """,
        g, p, n,
    )
    blocks: dict[str, int] = {}
    for r in rows:
        blocks[r["block_key"]] = blocks.get(r["block_key"], 0) + 1
    return {
        "part_ids": [r["part_id"] for r in rows],
        "group_ids": sorted({r["group_id"] for r in rows if r["group_id"]}),
        "blocks": sorted(({"block_key": k, "parts": v} for k, v in blocks.items()),
                         key=lambda b: -b["parts"]),
    }


# Vector order of gold_part_features.feature_vector (code/matching/build_matches.py FEATURES).
FEATURES = ["weight", "material_density", "length", "width", "thickness", "diameter",
    "inner_diameter", "outer_diameter", "nominal_diameter", "cross_section_diameter", "head_width",
    "gauge", "thread_pitch", "tensile_strength", "hardness", "pressure_rating", "load_rating",
    "temperature_rating", "hole_count", "voltage_rating", "conductor_count"]


def _feature_label(name: str) -> str:
    return name.replace("_", " ")


def _mds3(D):
    """Classical MDS of a distance matrix into 3D (coords keep true L2 scale)."""
    import numpy as np
    n = D.shape[0]
    J = np.eye(n) - np.ones((n, n)) / n
    B = -0.5 * J @ (D ** 2) @ J
    vals, vecs = np.linalg.eigh(B)
    order = np.argsort(vals)[::-1][:3]
    vals = np.clip(vals[order], 0, None)
    X = vecs[:, order] * np.sqrt(vals)
    if X.shape[1] < 3:
        X = np.hstack([X, np.zeros((n, 3 - X.shape[1]))])
    return X


@router.get("/groups/{group_id}/closeup")
async def closeup(group_id: str, k: int = 8):
    """Members of one match group + its nearest non-member neighbors, laid out by TRUE distance.

    Coordinates come from classical MDS on the 21-dim L2 distance matrix, so how far apart
    two dots are in the close-up is (very nearly) how far apart the parts really are.
    """
    import numpy as np

    k = max(0, min(k, 20))
    members = await db.fetch(
        """
        SELECT a.part_id, a.part_number, a.plant_id, a.machine_type, a.part_category, a.material,
               a.feature_vector_json, m.member_best_price, m.annual_volume, m.description
        FROM part_viz_attrs a
        JOIN match_group_members m ON m.part_id = a.part_id AND m.group_id = a.group_id
        WHERE a.group_id = $1
        """,
        group_id,
    )
    if not members:
        raise HTTPException(404, "group not found")
    grp = await db.fetch(
        "SELECT savings_potential, total_current_spend, group_best_price, plants_spanned FROM match_groups WHERE group_id = $1",
        group_id,
    )
    mvecs = np.array([json.loads(m["feature_vector_json"]) for m in members])
    centroid = mvecs.mean(axis=0)
    cat, mat = members[0]["part_category"], members[0]["material"]
    member_ids = {m["part_id"] for m in members}

    neighbors = []
    if k and VS_INDEX_NAME:
        try:
            ids = await asyncio.to_thread(_vs_query, centroid.tolist(), cat, mat, k + len(members))
        except Exception as exc:
            raise HTTPException(502, f"Vector Search error: {exc}")
        ids = [i for i in ids if i not in member_ids][:k]
        if ids:
            rows = await db.fetch(
                """SELECT part_id, part_number, plant_id, machine_type, group_id, gt_label, feature_vector_json
                   FROM part_viz_attrs WHERE part_id = ANY($1::text[])""",
                ids,
            )
            by_id = {r["part_id"]: r for r in rows}
            neighbors = [by_id[i] for i in ids if i in by_id]

    nvecs = np.array([json.loads(n["feature_vector_json"]) for n in neighbors]) if neighbors else np.zeros((0, mvecs.shape[1]))
    allv = np.vstack([mvecs, nvecs])
    D = np.sqrt(((allv[:, None, :] - allv[None, :, :]) ** 2).sum(-1))
    X = _mds3(D)
    X -= X[: len(members)].mean(axis=0)  # center on the group

    nm = len(members)
    out_members = [{
        "part_id": m["part_id"], "part_number": m["part_number"], "plant_id": m["plant_id"],
        "machine_type": m["machine_type"], "description": m["description"],
        "best_price": _round(m["member_best_price"], 2), "annual_volume": m["annual_volume"],
        "pos": [round(float(v), 5) for v in X[i]],
    } for i, m in enumerate(members)]

    edges = [{"a": i, "b": j, "l2": round(float(D[i, j]), 4)}
             for i in range(nm) for j in range(i + 1, nm)]

    out_neighbors = []
    for t, n in enumerate(neighbors):
        idx = nm + t
        dists = D[idx, :nm]
        near = int(np.argmin(dists))
        diff = np.abs(nvecs[t] - mvecs[near])
        top = int(np.argmax(diff))
        out_neighbors.append({
            "part_id": n["part_id"], "part_number": n["part_number"], "plant_id": n["plant_id"],
            "machine_type": n["machine_type"], "in_other_group": bool(n["group_id"]),
            "gt_label": n["gt_label"],
            "nearest_member": near, "l2": round(float(dists[near]), 4),
            "differs_on": _feature_label(FEATURES[top]) if top < len(FEATURES) else None,
            "pos": [round(float(v), 5) for v in X[idx]],
        })

    g = grp[0] if grp else {}
    return {
        "group_id": group_id, "part_category": cat, "material": mat,
        "threshold": L2_THRESHOLD,
        "savings": _round(g.get("savings_potential"), 2),
        "current_spend": _round(g.get("total_current_spend"), 2),
        "best_price": _round(g.get("group_best_price"), 2),
        "plants_spanned": g.get("plants_spanned"),
        "members": out_members, "edges": edges, "neighbors": out_neighbors,
    }
