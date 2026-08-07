from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..config import get_settings
from ..persistence.repositories import Repository
from ..rekordbox.diagnostics import diagnose
from ..rekordbox.writer import (
    ExecuteResult,
    PlanItem,
    WritePlan,
    build_write_plan,
    execute_write_plan,
)
from ..domain.enums import WriteAction
from ..rekordbox.xml_export import export_rekordbox_xml
from ..schemas.jobs import (
    BuildPlanRequest,
    ExecutePlanRequest,
    ExecutePlanResponse,
    ExportXmlRequest,
    ExportXmlResponse,
    PlanItemOut,
    WritePlanResponse,
)
from .deps import get_repo, require_token

router = APIRouter(prefix="/api/v1", tags=["write"], dependencies=[Depends(require_token)])


@router.post("/write/plan", response_model=WritePlanResponse)
def build_plan(req: BuildPlanRequest, repo: Repository = Depends(get_repo)) -> WritePlanResponse:
    if repo.get_job(req.job_id) is None:
        raise HTTPException(status_code=404, detail="job not found")
    rows = repo.list_accepted_decisions_for_job(req.job_id)
    decisions = []
    for r in rows:
        d = dict(r)
        time_ms = d["edited_time_ms"] if d["edited_time_ms"] is not None else d["orig_time_ms"]
        decisions.append(
            {
                "track_id": d["track_id"],
                "cue_kind": d["cue_kind"],
                "time_ms": int(time_ms),
                "slot": d["slot"],
            }
        )
    plan = build_write_plan(decisions, existing_by_track={})
    plan_id = repo.create_write_plan(job_id=req.job_id, confirmation_hash=plan.confirmation_hash)
    repo.add_write_plan_items(
        plan_id,
        [
            {
                "track_id": i.track_id,
                "action": i.action.value,
                "cue_kind": i.cue_kind,
                "slot": i.slot,
                "before": i.before,
                "after": i.after,
                "reason": i.reason,
            }
            for i in plan.items
        ],
    )
    repo.add_audit(actor="user", action="build_plan", result="ok", target=plan_id,
                   job_id=req.job_id, after={"items": len(plan.items)})
    return WritePlanResponse(
        plan_id=plan_id,
        confirmation_hash=plan.confirmation_hash,
        add=plan.add_count,
        replace=plan.replace_count,
        conflict=plan.conflict_count,
        items=[
            PlanItemOut(
                track_id=i.track_id,
                cue_kind=i.cue_kind,
                action=i.action.value,
                time_ms=i.time_ms,
                slot=i.slot,
                reason=i.reason,
            )
            for i in plan.items
        ],
    )


@router.post("/write/execute", response_model=ExecutePlanResponse)
def execute_plan(req: ExecutePlanRequest, repo: Repository = Depends(get_repo)) -> ExecutePlanResponse:
    plan_row = repo.get_write_plan(req.plan_id)
    if plan_row is None:
        raise HTTPException(status_code=404, detail="plan not found")
    item_rows = repo.list_write_plan_items(req.plan_id)
    items = tuple(
        PlanItem(
            track_id=r["track_id"],
            cue_kind=r["cue_kind"],
            action=WriteAction(r["action"]),
            time_ms=_time_of(r),
            slot=r["slot"],
            reason=r["reason"] or "",
        )
        for r in item_rows
    )
    plan = WritePlan(items=items, confirmation_hash=str(plan_row["confirmation_hash"]))

    diagnostics = diagnose(backup_dir=get_settings().data_dir)
    result: ExecuteResult = execute_write_plan(
        plan, confirmation_hash=req.confirmation_hash, diagnostics=diagnostics
    )
    status = "EXECUTED" if result.ok else "BLOCKED"
    repo.set_write_plan_status(req.plan_id, status, executed=result.ok)
    repo.add_audit(
        actor="user",
        action="execute_plan",
        result="ok" if result.ok else "blocked",
        target=req.plan_id,
        error_id=result.error_code.value if result.error_code else None,
        after={"written": result.written, "message": result.message},
    )
    return ExecutePlanResponse(
        ok=result.ok,
        error_code=result.error_code.value if result.error_code else None,
        message=result.message,
        written=result.written,
        details=result.details,
    )


@router.post("/write/export-xml", response_model=ExportXmlResponse)
def export_xml(req: ExportXmlRequest, repo: Repository = Depends(get_repo)) -> ExportXmlResponse:
    if repo.get_job(req.job_id) is None:
        raise HTTPException(status_code=404, detail="job not found")
    result = export_rekordbox_xml(repo, req.job_id, export_root=get_settings().export_dir)
    if result["tracks"] == 0:
        raise HTTPException(status_code=400, detail="採用キューがありません（書き出し対象なし）")
    repo.add_audit(
        actor="user",
        action="export_xml",
        result="ok",
        target=result["folder"],
        job_id=req.job_id,
        after={"tracks": result["tracks"], "cues": result["cues"], "copied": result["copied"]},
    )
    return ExportXmlResponse(**result)


def _time_of(row) -> int:
    import json

    after = json.loads(row["after_json"]) if row["after_json"] else {}
    return int(after.get("time_ms", 0))
