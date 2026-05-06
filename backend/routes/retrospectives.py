from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.orm import Session

from models.db import get_db, Retrospective, InvestmentCycle, BreakSignal

router = APIRouter()


class RetrospectiveResponse(BaseModel):
    id: str
    cycle_id: str
    is_draft: bool
    original_logic: str
    what_changed: Optional[str]
    logic_held: Optional[bool]
    weak_link: Optional[str]
    if_wrong_why: Optional[str]
    if_right_why: Optional[str]
    next_time: Optional[str]
    completed_at: Optional[str]


class RetrospectivePatch(BaseModel):
    what_changed: Optional[str] = None
    logic_held: Optional[bool] = None
    weak_link: Optional[str] = None
    if_wrong_why: Optional[str] = None
    if_right_why: Optional[str] = None
    next_time: Optional[str] = None
    is_draft: Optional[bool] = None


def _to_response(r: Retrospective) -> RetrospectiveResponse:
    return RetrospectiveResponse(
        id=str(r.id),
        cycle_id=str(r.cycle_id),
        is_draft=r.is_draft,
        original_logic=r.original_logic,
        what_changed=r.what_changed,
        logic_held=r.logic_held,
        weak_link=r.weak_link,
        if_wrong_why=r.if_wrong_why,
        if_right_why=r.if_right_why,
        next_time=r.next_time,
        completed_at=r.completed_at.isoformat() if r.completed_at else None,
    )


@router.get("/{cycle_id}", response_model=RetrospectiveResponse)
def get_retrospective(cycle_id: str, db: Session = Depends(get_db)):
    r = db.query(Retrospective).filter(Retrospective.cycle_id == cycle_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Retrospective not found")
    return _to_response(r)


@router.patch("/{cycle_id}", response_model=RetrospectiveResponse)
def update_retrospective(cycle_id: str, body: RetrospectivePatch, db: Session = Depends(get_db)):
    r = db.query(Retrospective).filter(Retrospective.cycle_id == cycle_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Retrospective not found")

    for field, value in body.model_dump(exclude_none=True).items():
        setattr(r, field, value)

    # 확정 처리
    if body.is_draft is False:
        r.is_draft = False
        r.completed_at = datetime.utcnow()

    db.commit()
    db.refresh(r)
    return _to_response(r)


@router.post("/{cycle_id}/generate", response_model=RetrospectiveResponse)
def generate_retrospective_draft(cycle_id: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """AI로 복기 초안 생성. 이미 존재하면 재생성."""
    cycle = db.query(InvestmentCycle).filter(InvestmentCycle.id == cycle_id).first()
    if not cycle:
        raise HTTPException(status_code=404, detail="Investment cycle not found")
    if cycle.status == 'open':
        raise HTTPException(status_code=400, detail="진행 중인 사이클입니다. 청산 후 복기를 작성하세요.")

    # original_logic 결정: thesis의 key_logic (체크 시점 스냅샷 우선)
    original_logic = ""
    if cycle.thesis:
        original_logic = (
            getattr(cycle.thesis, 'monitoring_contract', '') or
            getattr(cycle.thesis, 'key_logic', '') or
            ""
        )
    if not original_logic:
        original_logic = "(key_logic 없음 — thesis 확인 필요)"

    # 기존 retrospective 없으면 draft로 생성
    r = db.query(Retrospective).filter(Retrospective.cycle_id == cycle_id).first()
    if not r:
        r = Retrospective(
            cycle_id=cycle.id,
            is_draft=True,
            original_logic=original_logic,
        )
        db.add(r)
        db.commit()
        db.refresh(r)

    # Break Signal 이력 수집 (background에서 AI 초안 생성)
    break_signals = (
        db.query(BreakSignal)
        .filter(BreakSignal.thesis_id == cycle.thesis_id)
        .filter(BreakSignal.checked_at >= cycle.opened_at)
        .filter(BreakSignal.checked_at <= (cycle.closed_at or datetime.utcnow()))
        .order_by(BreakSignal.checked_at.asc())
        .all()
    ) if cycle.thesis_id else []

    signal_summaries = [
        f"[{s.checked_at.strftime('%Y-%m-%d')}] {s.observations[:200]}"
        for s in break_signals
    ]

    background_tasks.add_task(
        _generate_retro_async,
        str(r.id),
        original_logic,
        cycle.pnl_pct,
        cycle.exit_reason.value if cycle.exit_reason and hasattr(cycle.exit_reason, 'value') else str(cycle.exit_reason or ""),
        signal_summaries,
    )

    return _to_response(r)


def _generate_retro_async(
    retro_id: str,
    original_logic: str,
    pnl_pct: Optional[float],
    exit_reason: str,
    signal_summaries: list[str],
):
    from models.db import SessionLocal
    from services.agent import generate_retrospective
    db = SessionLocal()
    try:
        result = generate_retrospective(
            original_logic=original_logic,
            pnl_pct=pnl_pct,
            exit_reason=exit_reason,
            signal_summaries=signal_summaries,
        )
        r = db.query(Retrospective).filter(Retrospective.id == retro_id).first()
        if r:
            r.what_changed = result.get("what_changed", "")
            r.weak_link = result.get("weak_link", "")
            r.next_time = result.get("next_time", "")
            db.commit()
    except Exception:
        import logging
        logging.getLogger(__name__).exception("Retrospective 생성 실패: retro_id=%s", retro_id)
    finally:
        db.close()
