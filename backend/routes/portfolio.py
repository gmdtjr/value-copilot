import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from models.db import get_db, Portfolio, Ticker
from services.portfolio_sync import sync_portfolio
from services.telegram import notify_trades_detected

logger = logging.getLogger(__name__)
router = APIRouter()


class PortfolioResponse(BaseModel):
    id: str
    ticker_id: str
    symbol: str
    name: str
    market: str
    quantity: float
    avg_price: float
    current_price: float
    daily_pct: float
    updated_at: str


@router.get("", response_model=list[PortfolioResponse])
def list_portfolio(db: Session = Depends(get_db)):
    rows = (
        db.query(Portfolio, Ticker)
        .join(Ticker, Portfolio.ticker_id == Ticker.id)
        .order_by(Portfolio.updated_at.desc())
        .all()
    )
    return [
        PortfolioResponse(
            id=str(p.id),
            ticker_id=str(p.ticker_id),
            symbol=t.symbol,
            name=t.name,
            market=t.market.value,
            quantity=p.quantity,
            avg_price=p.avg_price,
            current_price=p.current_price,
            daily_pct=p.daily_pct,
            updated_at=p.updated_at.isoformat(),
        )
        for p, t in rows
    ]


@router.post("/sync", status_code=202)
def trigger_sync(background_tasks: BackgroundTasks):
    """KIS 전 계좌 동기화 트리거 (백그라운드)."""
    background_tasks.add_task(_run_sync)
    return {"message": "포트폴리오 동기화 시작됨"}


def _run_sync():
    try:
        result = sync_portfolio()
        logger.info("포트폴리오 동기화: %s", result)
        trades = result.get("trades", [])
        if trades:
            try:
                notify_trades_detected(trades)
            except Exception:
                logger.exception("거래 감지 알림 실패")
    except Exception:
        logger.exception("포트폴리오 동기화 실패")
