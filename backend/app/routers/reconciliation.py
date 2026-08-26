import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import EvaluationRun, ReconciliationRun
from ..services.evaluation.metrics import run_evaluation
from ..services.matching.deterministic import (
    get_reconciliation_run,
    start_reconciliation_run,
)

router = APIRouter(prefix="/api/reconciliation-runs", tags=["reconciliation"])


@router.get("")
def list_reconciliation_runs(db: Session = Depends(get_db)):
    runs = db.execute(
        select(ReconciliationRun).order_by(ReconciliationRun.created_at.desc()).limit(20)
    ).scalars().all()
    return [
        {
            "run_id": str(r.id),
            "status": r.status,
            "created_at": r.created_at.isoformat(),
            "summary": r.summary,
        }
        for r in runs
    ]


@router.get("/{run_id}/matches")
def list_run_matches(run_id: str, db: Session = Depends(get_db)):
    from ..models import MatchGroup, MatchMember, Transaction

    try:
        parsed = uuid.UUID(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="run_id must be a UUID") from exc

    run = db.get(ReconciliationRun, parsed)
    if run is None:
        raise HTTPException(status_code=404, detail="reconciliation run not found")

    groups = db.execute(
        select(MatchGroup)
        .where(MatchGroup.batch_id == parsed)
        .order_by(MatchGroup.created_at)
        .limit(300)
    ).scalars().all()

    member_rows = (
        db.execute(
            select(MatchMember, Transaction)
            .join(Transaction, Transaction.id == MatchMember.transaction_id)
            .where(MatchMember.match_group_id.in_([g.id for g in groups]))
            .limit(1200)
        ).all()
        if groups
        else []
    )

    members_by_group: dict = {}
    for member, txn in member_rows:
        members_by_group.setdefault(member.match_group_id, []).append(
            {
                "role": member.role,
                "transaction_id": str(txn.id),
                "external_id": txn.external_id,
                "amount_paise": int(txn.amount_paise),
                "allocated_paise": int(member.allocated_paise or 0),
                "effective_date": txn.effective_date.isoformat(),
                "utr": txn.utr,
            }
        )

    return [
        {
            "group_id": str(g.id),
            "strategy": g.strategy,
            "status": g.status,
            "deterministic_score": float(g.deterministic_score) if g.deterministic_score else None,
            "expected_amount_paise": g.expected_amount_paise,
            "actual_amount_paise": g.actual_amount_paise,
            "delta_paise": g.delta_paise,
            "members": members_by_group.get(g.id, []),
        }
        for g in groups
    ]


@router.post("", status_code=201)
def create_reconciliation_run(db: Session = Depends(get_db)):
    try:
        result = start_reconciliation_run(db)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return result


@router.get("/{run_id}")
def get_reconciliation_run_by_id(run_id: str, db: Session = Depends(get_db)):
    try:
        parsed = uuid.UUID(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="run_id must be a UUID") from exc
    result = get_reconciliation_run(db, parsed)
    if result is None:
        raise HTTPException(status_code=404, detail="reconciliation run not found")
    return result


@router.get("/{run_id}/metrics")
def get_reconciliation_run_metrics(
    run_id: str,
    evaluate: bool = True,
    db: Session = Depends(get_db),
    settings=Depends(get_settings),
):
    try:
        parsed = uuid.UUID(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="run_id must be a UUID") from exc

    run = db.get(ReconciliationRun, parsed)
    if run is None:
        raise HTTPException(status_code=404, detail="reconciliation run not found")

    latest_evaluation = None
    if evaluate:
        existing = (
            db.execute(
                select(EvaluationRun)
                .where(
                    EvaluationRun.metrics["reconciliation_run_id"].astext == str(parsed)
                )
                .order_by(EvaluationRun.created_at.desc())
                .limit(1)
            ).scalars().first()
        )
        if existing is not None:
            latest_evaluation = {"evaluation_run_id": str(existing.id), "metrics": existing.metrics}
        else:
            try:
                output = run_evaluation(
                    db,
                    ground_truth_path=settings.ground_truth_path,
                    reconciliation_run_id=parsed,
                )
                db.commit()
                latest_evaluation = {
                    "evaluation_run_id": output.evaluation_run_id,
                    "metrics": output.metrics,
                }
            except FileNotFoundError as exc:
                db.rollback()
                latest_evaluation = None
                del exc
            except Exception as exc:
                db.rollback()
                raise HTTPException(
                    status_code=500, detail=f"evaluation failed: {exc}"
                ) from exc

    return {
        "reconciliation_run_id": str(run.id),
        "status": run.status,
        "summary": run.summary,
        "evaluation": latest_evaluation,
    }
