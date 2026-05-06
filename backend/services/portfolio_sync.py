import logging
from datetime import datetime

import uuid as _uuid
from models.db import SessionLocal, Ticker, Thesis, Portfolio, MarketEnum, TickerStatusEnum, ThesisStatusEnum, TradeLog, TradeActionEnum, InvestmentCycle, CycleStatusEnum, Retrospective
from services.kis import KISClient, load_accounts, get_exchange_rate

logger = logging.getLogger(__name__)

_kis = KISClient()


def _get_portfolio_quote(symbol: str, market: MarketEnum) -> dict | None:
    """표시용 현재가/일일 등락률은 KIS 평가손익률이 아니라 Yahoo quote를 사용."""
    from services.market_data import get_yahoo_quote

    symbols = [symbol]
    if market == MarketEnum.KR_STOCK:
        base = symbol.zfill(6)
        symbols = [f"{base}.KS", f"{base}.KQ"]

    for yf_symbol in symbols:
        quote = get_yahoo_quote(yf_symbol)
        if quote and quote.get("price"):
            return quote
    return None


def sync_portfolio() -> dict:
    """전 계좌 잔고 조회 → 심볼별 집계 → Portfolio DB upsert.
    반환: {synced: int, accounts: int, errors: list, trades: list[dict]}
    """
    accounts = load_accounts()
    if not accounts:
        raise RuntimeError("KIS 계좌 환경변수가 설정되지 않았습니다.")

    exchange_rate = get_exchange_rate()
    logger.info("환율: %.2f원/USD", exchange_rate)

    # 전 계좌 holdings 수집 — 모든 계좌에서 국내/해외 모두 조회
    raw: list[dict] = []
    for account in accounts:
        raw.extend(_kis.get_domestic_portfolio(account))
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
    trades: list[dict] = []
    try:
        # 동기화 전 스냅샷
        before: dict[str, dict] = {}
        for p in db.query(Portfolio).join(Ticker).all():
            if p.quantity > 0:
                before[p.ticker.symbol] = {
                    "qty": p.quantity,
                    "avg": p.avg_price,
                    "name": p.ticker.name,
                    "ticker_id": str(p.ticker_id),
                }

        for sym, data in aggregated.items():
            try:
                qty = data["total_qty"]
                avg_price = data["total_cost"] / qty if qty else 0
                market = MarketEnum.KR_STOCK if data["currency"] == "KRW" else MarketEnum.US_STOCK
                quote = _get_portfolio_quote(sym, market)
                if quote:
                    data["current_price"] = quote["price"]
                    data["daily_pct"] = quote.get("change_pct") or 0

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

        # upsert 결과를 trade 감지 쿼리에서 볼 수 있도록 flush
        db.flush()

        # 청산 종목 처리 (DB에 있지만 KIS에 없는 종목 → qty=0, watchlist)
        synced_symbols = set(aggregated.keys())
        for p in db.query(Portfolio).join(Ticker).filter(Portfolio.quantity > 0).all():
            sym = p.ticker.symbol
            if sym not in synced_symbols:
                b = before.get(sym, {})
                trades.append({
                    "ticker_id": str(p.ticker_id),
                    "symbol": sym,
                    "name": p.ticker.name,
                    "action": TradeActionEnum.SELL,
                    "quantity_before": b.get("qty", p.quantity),
                    "quantity_after": 0.0,
                    "avg_price_before": b.get("avg", p.avg_price),
                    "avg_price_after": 0.0,
                })
                p.quantity = 0
                p.ticker.status = TickerStatusEnum.WATCHLIST
                logger.info("포지션 청산 감지: %s", sym)

        # 거래 감지 (신규 매수 / 추가 / 일부 매도)
        for sym, data in aggregated.items():
            ticker = db.query(Ticker).filter(Ticker.symbol == sym).first()
            if not ticker:
                continue
            portfolio = db.query(Portfolio).filter(Portfolio.ticker_id == ticker.id).first()
            if not portfolio:
                continue
            b = before.get(sym)
            qty_before = b["qty"] if b else 0.0
            qty_after = portfolio.quantity
            avg_before = b["avg"] if b else 0.0
            avg_after = portfolio.avg_price

            # qty 변화가 0.01 이하이면 무시 (부동소수점 오차)
            delta = abs(qty_after - qty_before)
            if delta < 0.01:
                continue

            if not b:
                action = TradeActionEnum.BUY
            elif qty_after > qty_before:
                action = TradeActionEnum.ADD
            else:
                action = TradeActionEnum.REDUCE

            trades.append({
                "ticker_id": str(ticker.id),
                "symbol": sym,
                "name": ticker.name,
                "action": action,
                "quantity_before": qty_before,
                "quantity_after": qty_after,
                "avg_price_before": avg_before,
                "avg_price_after": avg_after,
            })

        # TradeLog DB 저장 + InvestmentCycle 처리
        sell_cycles: list[tuple] = []  # (symbol, name, cycle) — 알림용
        for t in trades:
            ticker_id_val = _uuid.UUID(t["ticker_id"]) if t["ticker_id"] else None
            action = t["action"]

            # InvestmentCycle 처리
            cycle_id = None
            if ticker_id_val:
                cycle_id = _handle_investment_cycle(
                    db, ticker_id_val, t["symbol"], t["name"], action,
                    t.get("avg_price_before", 0), t.get("avg_price_after", 0),
                    sell_cycles,
                )

            log = TradeLog(
                ticker_id=ticker_id_val,
                symbol=t["symbol"],
                name=t["name"],
                action=action,
                quantity_before=t["quantity_before"],
                quantity_after=t["quantity_after"],
                avg_price_before=t["avg_price_before"],
                avg_price_after=t["avg_price_after"],
                cycle_id=cycle_id,
            )
            db.add(log)
            logger.info("거래 감지: %s %s %.2f→%.2f", t["symbol"], action.value, t["quantity_before"], t["quantity_after"])

        db.commit()

        # 청산 사이클 알림 (commit 후)
        for symbol, name, cycle in sell_cycles:
            try:
                from services.telegram import notify_cycle_closed
                notify_cycle_closed(symbol, name, cycle.pnl_pct, str(cycle.id))
            except Exception:
                pass
        logger.info("포트폴리오 동기화 완료: %d종목", synced)
    finally:
        db.close()

    return {"synced": synced, "accounts": len(accounts), "errors": errors, "trades": trades}


def _handle_investment_cycle(
    db, ticker_id, symbol: str, name: str, action,
    avg_price_before: float, avg_price_after: float,
    sell_cycles: list,
) -> _uuid.UUID | None:
    """거래 감지 시 InvestmentCycle을 생성하거나 종료. 사이클 ID 반환."""
    try:
        now = datetime.utcnow()

        if action in (TradeActionEnum.BUY, TradeActionEnum.ADD):
            # 이미 열린 사이클이 있으면 기존 것 재사용
            open_cycle = (
                db.query(InvestmentCycle)
                .filter(InvestmentCycle.ticker_id == ticker_id, InvestmentCycle.status == CycleStatusEnum.OPEN)
                .first()
            )
            if open_cycle:
                return open_cycle.id

            # 새 사이클 열기 — 현재 confirmed thesis 연결
            thesis = (
                db.query(Thesis)
                .filter(Thesis.ticker_id == ticker_id, Thesis.confirmed == 'confirmed')
                .order_by(Thesis.version_number.desc())
                .first()
            )
            cycle = InvestmentCycle(
                ticker_id=ticker_id,
                thesis_id=thesis.id if thesis else None,
                status=CycleStatusEnum.OPEN,
                opened_at=now,
            )
            db.add(cycle)
            db.flush()
            logger.info("InvestmentCycle 시작: %s (cycle_id=%s)", symbol, cycle.id)
            return cycle.id

        elif action in (TradeActionEnum.SELL,):
            # 전량 매도 → 사이클 종료
            open_cycle = (
                db.query(InvestmentCycle)
                .filter(InvestmentCycle.ticker_id == ticker_id, InvestmentCycle.status == CycleStatusEnum.OPEN)
                .first()
            )
            if not open_cycle:
                return None

            # pnl_pct 계산 (avg_price_before = cost basis, 현재가로 추정)
            pnl_pct = None
            if avg_price_before > 0:
                # Portfolio의 current_price가 있으면 사용
                from models.db import Portfolio
                portfolio = db.query(Portfolio).filter(Portfolio.ticker_id == ticker_id).first()
                sell_price = portfolio.current_price if portfolio and portfolio.current_price else avg_price_before
                pnl_pct = (sell_price - avg_price_before) / avg_price_before * 100

            open_cycle.status = CycleStatusEnum.CLOSED
            open_cycle.closed_at = now
            open_cycle.pnl_pct = round(pnl_pct, 2) if pnl_pct is not None else None
            db.flush()

            # Retrospective 초안 자동 생성
            original_logic = ""
            if open_cycle.thesis:
                original_logic = (
                    getattr(open_cycle.thesis, 'monitoring_contract', '') or
                    getattr(open_cycle.thesis, 'key_logic', '') or
                    ""
                )
            if original_logic:
                retro = Retrospective(
                    cycle_id=open_cycle.id,
                    is_draft=True,
                    original_logic=original_logic,
                )
                db.add(retro)
                db.flush()

            sell_cycles.append((symbol, name, open_cycle))
            logger.info("InvestmentCycle 종료: %s pnl=%.1f%%", symbol, pnl_pct or 0)
            return open_cycle.id

        elif action == TradeActionEnum.REDUCE:
            # 일부 매도 — 사이클 유지, 현재 open_cycle ID만 반환
            open_cycle = (
                db.query(InvestmentCycle)
                .filter(InvestmentCycle.ticker_id == ticker_id, InvestmentCycle.status == CycleStatusEnum.OPEN)
                .first()
            )
            return open_cycle.id if open_cycle else None

    except Exception:
        logger.exception("InvestmentCycle 처리 실패: %s", symbol)
        try:
            db.rollback()
        except Exception:
            pass
        return None
