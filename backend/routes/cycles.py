from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from models.db import get_db, InvestmentCycle, CycleStatusEnum, ExitReasonEnum, Ticker, Thesis

router = APIRouter()


class CycleResponse(BaseModel):
    id: str
    ticker_id: str
    ticker_symbol: Optional[str]
    ticker_name: Optional[str]
    thesis_id: Optional[str]
    thesis_key_logic: Optional[str]
    status: str
    opened_at: str
    closed_at: Optional[str]
    exit_reason: Optional[str]
    exit_reason_note: Optional[str]
    pnl_pct: Optional[float]
    has_retrospective: bool


class ExitReasonBody(BaseModel):
    exit_reason: str
    exit_reason_note: Optional[str] = None


def _to_response(c: InvestmentCycle) -> CycleResponse:
    return CycleResponse(
        id=str(c.id),
        ticker_id=str(c.ticker_id),
        ticker_symbol=c.ticker.symbol if c.ticker else None,
        ticker_name=c.ticker.name if c.ticker else None,
        thesis_id=str(c.thesis_id) if c.thesis_id else None,
        thesis_key_logic=(
            (getattr(c.thesis, 'monitoring_contract', None) or getattr(c.thesis, 'key_logic', None))
            if c.thesis else None
        ),
        status=c.status.value if hasattr(c.status, 'value') else c.status,
        opened_at=c.opened_at.isoformat(),
        closed_at=c.closed_at.isoformat() if c.closed_at else None,
        exit_reason=c.exit_reason.value if c.exit_reason and hasattr(c.exit_reason, 'value') else c.exit_reason,
        exit_reason_note=c.exit_reason_note,
        pnl_pct=c.pnl_pct,
        has_retrospective=c.retrospective is not None,
    )


@router.get("", response_model=list[CycleResponse])
def list_cycles(
    ticker_id: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    limit: int = 50,
):
    q = db.query(InvestmentCycle)
    if ticker_id:
        q = q.filter(InvestmentCycle.ticker_id == ticker_id)
    if status:
        q = q.filter(InvestmentCycle.status == status)
    cycles = q.order_by(InvestmentCycle.opened_at.desc()).limit(limit).all()
    return [_to_response(c) for c in cycles]


@router.get("/{cycle_id}", response_model=CycleResponse)
def get_cycle(cycle_id: str, db: Session = Depends(get_db)):
    c = db.query(InvestmentCycle).filter(InvestmentCycle.id == cycle_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Investment cycle not found")
    return _to_response(c)


@router.patch("/{cycle_id}/exit-reason", response_model=CycleResponse)
def set_exit_reason(cycle_id: str, body: ExitReasonBody, db: Session = Depends(get_db)):
    """사람이 청산 이유를 입력."""
    c = db.query(InvestmentCycle).filter(InvestmentCycle.id == cycle_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Investment cycle not found")
    try:
        c.exit_reason = ExitReasonEnum(body.exit_reason)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"알 수 없는 exit_reason: {body.exit_reason}")
    if body.exit_reason_note is not None:
        c.exit_reason_note = body.exit_reason_note.strip() or None
    db.commit()
    db.refresh(c)
    return _to_response(c)
