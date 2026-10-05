"""API routes for AI Parts Wizard."""
import asyncio
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

from .db import db
from . import genie

router = APIRouter(prefix="/api")

VALID_STATUSES = {"new", "reviewed", "consolidated", "dismissed"}


def current_reviewer(request: Request) -> str:
    """Resolve the acting user.

    In a Databricks App the user's identity arrives in headers. Fall back to a
    generic name locally.
    """
    email = request.headers.get("x-forwarded-email") or request.headers.get(
        "x-forwarded-preferred-username"
    )
    if email:
        return email.split("@")[0]
    return "local-user"


@router.get("/me")
async def me(request: Request):
    return {"reviewer": current_reviewer(request)}


@router.get("/filters")
async def filters():
    """Distinct values used to populate the filter controls."""
    categories = await db.fetch(
        "SELECT DISTINCT part_category FROM match_groups ORDER BY 1"
    )
    materials = await db.fetch(
        "SELECT DISTINCT material FROM match_groups ORDER BY 1"
    )
    models = await db.fetch(
        "SELECT DISTINCT model_id FROM match_group_members ORDER BY 1"
    )
    plants = await db.fetch(
        "SELECT DISTINCT plant_id FROM match_group_members ORDER BY 1"
    )
    suppliers = await db.fetch(
        "SELECT DISTINCT supplier_name FROM supplier_offers ORDER BY 1"
    )
    return {
        "part_categories": [r["part_category"] for r in categories],
        "materials": [r["material"] for r in materials],
        "machine_types": ["Harvester", "Tractor"],
        "models": [r["model_id"] for r in models],
        "plants": [r["plant_id"] for r in plants],
        "suppliers": [r["supplier_name"] for r in suppliers],
        "statuses": ["new", "reviewed", "consolidated", "dismissed"],
    }


SORT_COLUMNS = {
    "savings_potential": "mg.savings_potential",
    "avg_similarity": "mg.avg_similarity",
    "member_count": "mg.member_count",
    "models_spanned": "mg.models_spanned",
    "total_current_spend": "mg.total_current_spend",
}


@router.get("/queue")
async def queue(
    part_category: Optional[str] = None,
    material: Optional[str] = None,
    machine_type: Optional[str] = None,
    spans_models: bool = False,
    spans_machine_types: bool = False,
    spans_plants: bool = False,
    model: Optional[str] = None,
    plant: Optional[str] = None,
    supplier: Optional[str] = None,
    min_savings: Optional[float] = None,
    min_similarity: Optional[float] = None,
    status: Optional[str] = None,
    normalized: Optional[str] = None,  # 'yes' | 'no'
    min_group_size: Optional[int] = None,
    sort: str = "savings_potential",
    direction: str = "desc",
    limit: int = 100,
    offset: int = 0,
):
    where = []
    args: list = []

    def add(clause: str, *vals):
        # Renumber placeholders as we append.
        nonlocal args
        start = len(args)
        for i, v in enumerate(vals):
            clause = clause.replace(f"${i+1}", f"${start + i + 1}")
            args.append(v)
        where.append(clause)

    if part_category:
        add("mg.part_category = $1", part_category)
    if material:
        add("mg.material = $1", material)
    if spans_models:
        where.append("mg.models_spanned > 1")
    if spans_machine_types:
        where.append("mg.machine_types_spanned > 1")
    if spans_plants:
        where.append("mg.plants_spanned > 1")
    if min_savings is not None:
        add("mg.savings_potential >= $1", min_savings)
    if min_similarity is not None:
        add("mg.avg_similarity >= $1", min_similarity)
    if min_group_size is not None:
        add("mg.member_count >= $1", min_group_size)
    if machine_type:
        add(
            "EXISTS (SELECT 1 FROM match_group_members m WHERE m.group_id = mg.group_id AND m.machine_type = $1)",
            machine_type,
        )
    if model:
        add(
            "EXISTS (SELECT 1 FROM match_group_members m WHERE m.group_id = mg.group_id AND m.model_id = $1)",
            model,
        )
    if plant:
        add(
            "EXISTS (SELECT 1 FROM match_group_members m WHERE m.group_id = mg.group_id AND m.plant_id = $1)",
            plant,
        )
    if supplier:
        add(
            "EXISTS (SELECT 1 FROM match_group_members m JOIN supplier_offers so ON so.part_id = m.part_id "
            "WHERE m.group_id = mg.group_id AND so.supplier_name = $1)",
            supplier,
        )
    if status:
        if status == "new":
            add("COALESCE(rd.status, 'new') = $1", status)
        else:
            add("rd.status = $1", status)
    if normalized == "yes":
        where.append("na.group_id IS NOT NULL")
    elif normalized == "no":
        where.append("na.group_id IS NULL")

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    sort_col = SORT_COLUMNS.get(sort, "mg.savings_potential")
    dir_sql = "ASC" if direction.lower() == "asc" else "DESC"

    base = f"""
        FROM match_groups mg
        LEFT JOIN review_dispositions rd ON rd.group_id = mg.group_id
        LEFT JOIN normalized_assignments na ON na.group_id = mg.group_id
        {where_sql}
    """

    total_rows = await db.fetch(f"SELECT count(*) AS n {base}", *args)
    total = total_rows[0]["n"]

    limit = max(1, min(limit, 500))
    rows = await db.fetch(
        f"""
        SELECT mg.group_id, mg.part_category, mg.material, mg.member_count,
               mg.models_spanned, mg.machine_types_spanned, mg.plants_spanned,
               mg.avg_similarity, mg.group_best_price, mg.total_current_spend,
               mg.savings_potential,
               COALESCE(rd.status, 'new') AS status,
               (na.group_id IS NOT NULL) AS normalized,
               na.enterprise_part_number
        {base}
        ORDER BY {sort_col} {dir_sql} NULLS LAST, mg.group_id
        LIMIT {limit} OFFSET {offset}
        """,
        *args,
    )
    return {"total": total, "rows": rows}


@router.get("/groups/{group_id}")
async def group_detail(group_id: str):
    groups = await db.fetch(
        """
        SELECT mg.*, COALESCE(rd.status, 'new') AS status, rd.reviewer, rd.notes,
               rd.updated_at,
               na.enterprise_part_number, na.assigned_by, na.assigned_at,
               na.notes AS normalize_notes
        FROM match_groups mg
        LEFT JOIN review_dispositions rd ON rd.group_id = mg.group_id
        LEFT JOIN normalized_assignments na ON na.group_id = mg.group_id
        WHERE mg.group_id = $1
        """,
        group_id,
    )
    if not groups:
        raise HTTPException(status_code=404, detail="group not found")

    members = await db.fetch(
        """
        SELECT part_id, part_number, description, model_id, machine_type,
               plant_id, similarity, member_best_price, annual_volume
        FROM match_group_members
        WHERE group_id = $1
        ORDER BY similarity DESC NULLS LAST, part_number
        """,
        group_id,
    )

    offers = await db.fetch(
        """
        SELECT so.part_id, m.part_number, so.supplier_name, so.price_per_unit,
               so.unit_discount,
               so.price_per_unit * (1 - COALESCE(so.unit_discount, 0)) AS net_price,
               so.lead_time_days, so.currency
        FROM match_group_members m
        JOIN supplier_offers so ON so.part_id = m.part_id
        WHERE m.group_id = $1
        ORDER BY net_price ASC NULLS LAST
        """,
        group_id,
    )

    return {"group": groups[0], "members": members, "offers": offers}


class DispositionBody(BaseModel):
    status: str
    notes: Optional[str] = None


@router.post("/groups/{group_id}/disposition")
async def set_disposition(group_id: str, body: DispositionBody, request: Request):
    if body.status not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"invalid status {body.status}")
    reviewer = current_reviewer(request)
    now = datetime.now(timezone.utc)
    await db.execute(
        """
        INSERT INTO review_dispositions (group_id, status, reviewer, notes, updated_at)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (group_id)
        DO UPDATE SET status = EXCLUDED.status, reviewer = EXCLUDED.reviewer,
                      notes = EXCLUDED.notes, updated_at = EXCLUDED.updated_at
        """,
        group_id,
        body.status,
        reviewer,
        body.notes,
        now,
    )
    return {"group_id": group_id, "status": body.status, "reviewer": reviewer,
            "notes": body.notes, "updated_at": now.isoformat()}


class ChatBody(BaseModel):
    question: str
    conversation_id: Optional[str] = None


@router.post("/chat")
async def chat(body: ChatBody):
    q = body.question.strip()
    if not q:
        raise HTTPException(status_code=400, detail="question required")
    try:
        return await asyncio.to_thread(genie.ask, q, body.conversation_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Genie error: {exc}")


class NormalizeBody(BaseModel):
    enterprise_part_number: str
    notes: Optional[str] = None


@router.post("/groups/{group_id}/normalize")
async def set_normalize(group_id: str, body: NormalizeBody, request: Request):
    if not body.enterprise_part_number.strip():
        raise HTTPException(status_code=400, detail="enterprise_part_number required")
    assigned_by = current_reviewer(request)
    now = datetime.now(timezone.utc)
    await db.execute(
        """
        INSERT INTO normalized_assignments
            (group_id, enterprise_part_number, assigned_by, assigned_at, notes)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (group_id)
        DO UPDATE SET enterprise_part_number = EXCLUDED.enterprise_part_number,
                      assigned_by = EXCLUDED.assigned_by,
                      assigned_at = EXCLUDED.assigned_at,
                      notes = EXCLUDED.notes
        """,
        group_id,
        body.enterprise_part_number.strip(),
        assigned_by,
        now,
        body.notes,
    )
    return {"group_id": group_id,
            "enterprise_part_number": body.enterprise_part_number.strip(),
            "assigned_by": assigned_by, "assigned_at": now.isoformat()}
