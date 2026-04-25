import logging
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from models.db import get_db, Thesis, Ticker, ThesisStatusEnum
from services.telegram import notify_thesis_confirmed

logger = logging.getLogger(__name__)
router = APIRouter()


class ThesisResponse(BaseModel):
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


class ThesisPatch(BaseModel):
    thesis: Optional[str] = None
    risk: Optional[str] = None
    key_assumptions: Optional[str] = None
    valuation: Optional[str] = None


@router.get("/{ticker_id}", response_model=ThesisResponse)
def get_thesis(ticker_id: str, db: Session = Depends(get_db)):
    thesis = db.query(Thesis).filter(Thesis.ticker_id == ticker_id).first()
    if not thesis:
        raise HTTPException(status_code=404, detail="Thesis not found")
    return _to_response(thesis)


@router.patch("/{ticker_id}", response_model=ThesisResponse)
def patch_thesis(ticker_id: str, body: ThesisPatch, db: Session = Depends(get_db)):
    """사람이 thesis 내용을 직접 편집."""
    thesis = db.query(Thesis).filter(Thesis.ticker_id == ticker_id).first()
    if not thesis:
        raise HTTPException(status_code=404, detail="Thesis not found")

    for field, value in body.model_dump(exclude_none=True).items():
        setattr(thesis, field, value)
    db.commit()
    db.refresh(thesis)
    return _to_response(thesis)


@router.post("/{ticker_id}/confirm", response_model=ThesisResponse)
def confirm_thesis(ticker_id: str, db: Session = Depends(get_db)):
    """사람이 confirmed 버튼을 눌러 상태 전환. AI가 임의로 호출 불가."""
    thesis = db.query(Thesis).filter(Thesis.ticker_id == ticker_id).first()
    if not thesis:
        raise HTTPException(status_code=404, detail="Thesis not found")
    if not thesis.thesis:
        raise HTTPException(status_code=400, detail="Thesis 내용이 없습니다. 먼저 AI 분석을 실행하세요.")

    thesis.confirmed = ThesisStatusEnum.CONFIRMED
    thesis.confirmed_at = datetime.utcnow()
    db.commit()
    db.refresh(thesis)
    logger.info("Thesis confirmed for ticker_id=%s", ticker_id)

    ticker = db.query(Ticker).filter(Ticker.id == thesis.ticker_id).first()
    if ticker:
        notify_thesis_confirmed(ticker.symbol, ticker.name, ticker.market.value)

    return _to_response(thesis)


def _to_response(thesis: Thesis) -> ThesisResponse:
    return ThesisResponse(
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
    )
