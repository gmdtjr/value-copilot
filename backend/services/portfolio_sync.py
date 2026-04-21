import logging
from datetime import datetime

from models.db import SessionLocal, Ticker, Thesis, Portfolio, MarketEnum, TickerStatusEnum, ThesisStatusEnum
from services.kis import KISClient, load_accounts, get_exchange_rate

logger = logging.getLogger(__name__)

_kis = KISClient()


def sync_portfolio() -> dict:
    """전 계좌 잔고 조회 → 심볼별 집계 → Portfolio DB upsert.
    반환: {synced: int, accounts: int, errors: list}
    """
    accounts = load_accounts()
    if not accounts:
        raise RuntimeError("KIS 계좌 환경변수가 설정되지 않았습니다.")

    exchange_rate = get_exchange_rate()
    logger.info("환율: %.2f원/USD", exchange_rate)

    # 전 계좌 holdings 수집
    raw: list[dict] = []
    for account in accounts:
        if account.account_type == "domestic":
            raw.extend(_kis.get_domestic_portfolio(account))
        else:
            raw.extend(_kis.get_overseas_portfolio(account, exchange_rate))

    # 심볼별 집계 (여러 계좌에 같은 종목 있을 수 있음)
    aggregated: dict[str, dict] = {}
    for item in raw:
        sym = item["symbol"]
        if not sym:
            continue
        if sym not in aggregated:
            aggregated[sym] = {
                "symbol": sym,
                "name": item["name"],
                "currency": item["currency"],
                "total_qty": 0,
                "total_cost": 0.0,
                "current_price": item["current_price"],
                "daily_pct": item["daily_pct"],
            }
        aggregated[sym]["total_qty"] += item["quantity"]
        aggregated[sym]["total_cost"] += item["quantity"] * item["avg_price"]

    db = SessionLocal()
    synced = 0
    errors = []
    try:
        for sym, data in aggregated.items():
            try:
                qty = data["total_qty"]
                avg_price = data["total_cost"] / qty if qty else 0
                market = MarketEnum.KR_STOCK if data["currency"] == "KRW" else MarketEnum.US_STOCK

                # Ticker 없으면 자동 생성
                ticker = db.query(Ticker).filter(Ticker.symbol == sym).first()
                if not ticker:
                    ticker = Ticker(
                        symbol=sym,
                        name=data["name"],
                        market=market,
                        status=TickerStatusEnum.PORTFOLIO,
                    )
                    db.add(ticker)
                    db.flush()
                    db.add(Thesis(ticker_id=ticker.id, confirmed=ThesisStatusEnum.DRAFT))
                    logger.info("Ticker 자동 생성: %s", sym)
                else:
                    ticker.status = TickerStatusEnum.PORTFOLIO

                # Portfolio upsert
                portfolio = db.query(Portfolio).filter(Portfolio.ticker_id == ticker.id).first()
                if portfolio:
                    portfolio.quantity = qty
                    portfolio.avg_price = avg_price
                    portfolio.current_price = data["current_price"]
                    portfolio.daily_pct = data["daily_pct"]
                    portfolio.updated_at = datetime.utcnow()
                else:
                    portfolio = Portfolio(
                        ticker_id=ticker.id,
                        quantity=qty,
                        avg_price=avg_price,
                        current_price=data["current_price"],
                        daily_pct=data["daily_pct"],
                    )
                    db.add(portfolio)
                synced += 1
            except Exception as e:
                logger.error("포트폴리오 upsert 실패 %s: %s", sym, e)
                errors.append(sym)

        db.commit()
        logger.info("포트폴리오 동기화 완료: %d종목", synced)
    finally:
        db.close()

    return {"synced": synced, "accounts": len(accounts), "errors": errors}
