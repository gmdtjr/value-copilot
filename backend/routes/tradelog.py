import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from models.db import get_db, TradeLog, Ticker, TradeActionEnum

logger = logging.getLogger(__name__)
router = APIRouter()


class TradeLogResponse(BaseModel):
    id: str
    ticker_id: Optional[str]
    symbol: str
    name: str
    action: str
    quantity_before: float
    quantity_after: float
    avg_price_before: float
    avg_price_after: float
    note: Optional[str]
    detected_at: str
    noted_at: Optional[str]


class NoteBody(BaseModel):
    note: str


class TradeLogCreate(BaseModel):
    ticker_id: str
    action: str  # buy | sell | add | reduce
    quantity_before: float
    quantity_after: float
    avg_price_before: float
    avg_price_after: float
    detected_at: Optional[str] = None  # ISO 날짜 문자열, 없으면 현재 시각
    note: Optional[str] = None


@router.post("", response_model=TradeLogResponse, status_code=201)
def create_trade_log(body: TradeLogCreate, db: Session = Depends(get_db)):
    """수동 거래 기록 생성."""
    ticker = db.query(Ticker).filter(Ticker.id == body.ticker_id).first()
    if not ticker:
        raise HTTPException(status_code=404, detail="Ticker not found")

    try:
        action = TradeActionEnum(body.action)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"유효하지 않은 action: {body.action}")

    detected_at = datetime.utcnow()
    if body.detected_at:
        try:
            detected_at = datetime.fromisoformat(body.detected_at.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            raise HTTPException(status_code=400, detail="detected_at 형식이 올바르지 않습니다 (ISO 8601)")

    log = TradeLog(
        ticker_id=ticker.id,
        symbol=ticker.symbol,
        name=ticker.name,
        action=action,
        quantity_before=body.quantity_before,
        quantity_after=body.quantity_after,
        avg_price_before=body.avg_price_before,
        avg_price_after=body.avg_price_after,
        note=body.note.strip() if body.note else None,
        detected_at=detected_at,
        noted_at=datetime.utcnow() if body.note else None,
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    logger.info("수동 거래 기록 생성: %s %s", ticker.symbol, action.value)
    return _to_response(log)


@router.get("", response_model=list[TradeLogResponse])
def list_trade_logs(db: Session = Depends(get_db), limit: int = 100):
    logs = (
        db.query(TradeLog)
        .order_by(TradeLog.detected_at.desc())
        .limit(limit)
        .all()
    )
    return [_to_response(t) for t in logs]


@router.patch("/{log_id}/note", response_model=TradeLogResponse)
def update_note(log_id: str, body: NoteBody, db: Session = Depends(get_db)):
    log = db.query(TradeLog).filter(TradeLog.id == log_id).first()
    if not log:
        raise HTTPException(status_code=404, detail="거래 기록을 찾을 수 없습니다")
    log.note = body.note.strip()
    log.noted_at = datetime.utcnow()
    db.commit()
    return _to_response(log)


@router.delete("/{log_id}", status_code=204)
def delete_trade_log(log_id: str, db: Session = Depends(get_db)):
    log = db.query(TradeLog).filter(TradeLog.id == log_id).first()
    if not log:
        raise HTTPException(status_code=404, detail="거래 기록을 찾을 수 없습니다")
    db.delete(log)
    db.commit()


def _to_response(t: TradeLog) -> TradeLogResponse:
    return TradeLogResponse(
        id=str(t.id),
        ticker_id=str(t.ticker_id) if t.ticker_id else None,
        symbol=t.symbol,
        name=t.name,
        action=t.action.value,
        quantity_before=t.quantity_before,
        quantity_after=t.quantity_after,
        avg_price_before=t.avg_price_before,
        avg_price_after=t.avg_price_after,
        note=t.note,
        detected_at=t.detected_at.isoformat(),
        noted_at=t.noted_at.isoformat() if t.noted_at else None,
    )
