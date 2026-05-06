from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from models.db import get_db, BreakSignal, VerdictEnum, Thesis, Ticker, ThesisStatusEnum

router = APIRouter()


class BreakSignalResponse(BaseModel):
    id: str
    thesis_id: str
    ticker_id: Optional[str]
    ticker_symbol: Optional[str]
    ticker_name: Optional[str]
    checked_at: str
    key_logic_snapshot: Optional[str]
    observations: str
    positive_signals: Optional[str]
    negative_signals: Optional[str]
    watch_items: Optional[str]
    verdict: Optional[str]
    human_note: Optional[str]
    reviewed_at: Optional[str]


class ThesisVersionResponse(BaseModel):
    id: str
    ticker_id: str
    confirmed: str
    confirmed_at: Optional[str]
    thesis: Optional[str]
    risk: Optional[str]
    key_assumptions: Optional[str]
    valuation: Optional[str]
    last_analyzed_at: Optional[str]
    stock_type: Optional[str]
    seed_memo: Optional[str]
    version_number: int
    parent_version_id: Optional[str]
    key_logic: Optional[str]
    monitoring_contract: Optional[str]
    exploration_note: Optional[str]
    retired_at: Optional[str]
    retirement_reason: Optional[str]


class VerdictBody(BaseModel):
    verdict: str
    human_note: Optional[str] = None


def _to_response(s: BreakSignal) -> BreakSignalResponse:
    thesis = s.thesis
    ticker = thesis.ticker if thesis else None
    return BreakSignalResponse(
        id=str(s.id),
        thesis_id=str(s.thesis_id),
        ticker_id=str(ticker.id) if ticker else None,
        ticker_symbol=ticker.symbol if ticker else None,
        ticker_name=ticker.name if ticker else None,
        checked_at=s.checked_at.isoformat(),
        key_logic_snapshot=s.key_logic_snapshot,
        observations=s.observations,
        positive_signals=s.positive_signals,
        negative_signals=s.negative_signals,
        watch_items=s.watch_items,
        verdict=s.verdict.value if s.verdict else None,
        human_note=s.human_note,
        reviewed_at=s.reviewed_at.isoformat() if s.reviewed_at else None,
    )


def _thesis_response(thesis: Thesis) -> ThesisVersionResponse:
    return ThesisVersionResponse(
        id=str(thesis.id),
        ticker_id=str(thesis.ticker_id),
        confirmed=thesis.confirmed.value,
        confirmed_at=thesis.confirmed_at.isoformat() if thesis.confirmed_at else None,
        thesis=thesis.thesis,
        risk=thesis.risk,
        key_assumptions=thesis.key_assumptions,
        valuation=thesis.valuation,
        last_analyzed_at=thesis.last_analyzed_at.isoformat() if thesis.last_analyzed_at else None,
        stock_type=thesis.stock_type.value if thesis.stock_type else None,
        seed_memo=thesis.seed_memo,
        version_number=thesis.version_number or 1,
        parent_version_id=str(thesis.parent_version_id) if thesis.parent_version_id else None,
        key_logic=thesis.key_logic,
        monitoring_contract=getattr(thesis, 'monitoring_contract', None),
        exploration_note=thesis.exploration_note,
        retired_at=thesis.retired_at.isoformat() if thesis.retired_at else None,
        retirement_reason=thesis.retirement_reason,
    )


def _signal_note(s: BreakSignal) -> str:
    parts = [
        "## Break Monitor 관찰",
        s.observations or "",
    ]
    if s.positive_signals:
        parts.extend(["", "## Thesis 강화 신호", s.positive_signals])
    if s.negative_signals:
        parts.extend(["", "## Thesis 약화 신호", s.negative_signals])
    if s.watch_items:
        parts.extend(["", "## 다음 확인 항목", s.watch_items])
    if s.verdict:
        parts.extend(["", "## 사람 판정", s.verdict.value])
    if s.human_note:
        parts.extend(["", "## 사람 메모", s.human_note])
    return "\n".join(parts).strip()


@router.get("", response_model=list[BreakSignalResponse])
def list_signals(
    ticker_id: Optional[str] = None,
    thesis_id: Optional[str] = None,
    pending_only: bool = False,
    db: Session = Depends(get_db),
    limit: int = 50,
):
    q = db.query(BreakSignal)
    if thesis_id:
        q = q.filter(BreakSignal.thesis_id == thesis_id)
    elif ticker_id:
        # thesis_id로 필터링 — 해당 ticker의 모든 thesis 버전 포함
        thesis_ids = [
            t.id for t in db.query(Thesis).filter(Thesis.ticker_id == ticker_id).all()
        ]
        if not thesis_ids:
            return []
        q = q.filter(BreakSignal.thesis_id.in_(thesis_ids))
    if pending_only:
        q = q.filter(BreakSignal.verdict.is_(None))
    signals = q.order_by(BreakSignal.checked_at.desc()).limit(limit).all()
    return [_to_response(s) for s in signals]


@router.get("/{signal_id}", response_model=BreakSignalResponse)
def get_signal(signal_id: str, db: Session = Depends(get_db)):
    s = db.query(BreakSignal).filter(BreakSignal.id == signal_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Break Signal not found")
    return _to_response(s)


@router.patch("/{signal_id}", response_model=BreakSignalResponse)
def set_verdict(signal_id: str, body: VerdictBody, db: Session = Depends(get_db)):
    """사람이 verdict 판정 입력."""
    s = db.query(BreakSignal).filter(BreakSignal.id == signal_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Break Signal not found")
    try:
        s.verdict = VerdictEnum(body.verdict)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"알 수 없는 verdict: {body.verdict}")
    if body.human_note is not None:
        s.human_note = body.human_note.strip() or None
    s.reviewed_at = datetime.utcnow()
    db.commit()
    db.refresh(s)
    return _to_response(s)


@router.post("/{signal_id}/thesis-version", response_model=ThesisVersionResponse)
def create_thesis_version_from_signal(signal_id: str, db: Session = Depends(get_db)):
    """Break Monitor 신호를 근거로 새 draft thesis 버전을 생성."""
    s = db.query(BreakSignal).filter(BreakSignal.id == signal_id).first()
    if not s or not s.thesis:
        raise HTTPException(status_code=404, detail="Break Signal or thesis not found")

    current = s.thesis
    max_version = (
        db.query(Thesis)
        .filter(Thesis.ticker_id == current.ticker_id)
        .order_by(Thesis.version_number.desc())
        .first()
    )
    new_v = ((max_version.version_number if max_version else current.version_number) or 1) + 1
    signal_note = _signal_note(s)
    existing_note = current.exploration_note or ""
    exploration_note = (
        f"{existing_note}\n\n---\n\n{signal_note}".strip()
        if existing_note else signal_note
    )

    new_thesis = Thesis(
        ticker_id=current.ticker_id,
        version_number=new_v,
        parent_version_id=current.id,
        confirmed=ThesisStatusEnum.DRAFT,
        thesis=current.thesis,
        risk=current.risk,
        key_assumptions=current.key_assumptions,
        valuation=current.valuation,
        stock_type=current.stock_type,
        seed_memo=current.seed_memo,
        exploration_note=exploration_note,
        key_logic=current.key_logic,
        monitoring_contract=getattr(current, 'monitoring_contract', None),
    )
    db.add(new_thesis)
    db.commit()
    db.refresh(new_thesis)
    return _thesis_response(new_thesis)


@router.delete("/{signal_id}", status_code=204)
def delete_signal(signal_id: str, db: Session = Depends(get_db)):
    s = db.query(BreakSignal).filter(BreakSignal.id == signal_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Break Signal not found")
    db.delete(s)
    db.commit()
