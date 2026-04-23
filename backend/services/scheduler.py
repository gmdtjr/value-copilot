import logging
from datetime import datetime, timezone, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from models.db import SessionLocal, Ticker, Report, FinancialCache, Portfolio, TickerStatusEnum, ThesisStatusEnum, ReportTypeEnum
from services.agent import generate_daily_briefing, run_break_monitor
from services.telegram import notify_break_monitor, notify_daily_briefing

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

scheduler = AsyncIOScheduler(timezone="Asia/Seoul")


def _get_cache(db, ticker_id: str, data_type: str):
    """FinancialCache에서 유효한 캐시 데이터 조회."""
    from datetime import datetime
    row = (
        db.query(FinancialCache)
        .filter(
            FinancialCache.ticker_id == ticker_id,
            FinancialCache.data_type == data_type,
        )
        .first()
    )
    if row and row.expires_at > datetime.utcnow():
        return row.data
    return None


def _fmt_news_snippet(news_data, limit: int = 3) -> str:
    """뉴스 캐시 데이터 → 짧은 문자열."""
    if not news_data or not isinstance(news_data, list):
        return ""
    lines = []
    for n in news_data[:limit]:
        date = (n.get("date") or "")[:10]
        title = n.get("title", "").strip()
        if title:
            lines.append(f"  [{date}] {title}")
    return "\n".join(lines)


def _fmt_news_full(news_data, limit: int = 7) -> str:
    """Break Monitor용 — 뉴스 상세 포맷."""
    if not news_data or not isinstance(news_data, list):
        return ""
    lines = []
    for n in news_data[:limit]:
        date = (n.get("date") or "")[:10]
        title = n.get("title", "").strip()
        source = n.get("source", "")
        if title:
            lines.append(f"  [{date}] {title} ({source})")
    return "\n".join(lines)


def _fmt_metrics(metrics_data) -> str:
    """metrics 캐시 → Break Monitor용 핵심 수치 문자열."""
    if not metrics_data:
        return ""
    m = metrics_data[0] if isinstance(metrics_data, list) else metrics_data

    def pct(v):
        return f"{v*100:.1f}%" if v is not None else "N/A"
    def x(v):
        return f"{v:.1f}x" if v is not None else "N/A"

    return (
        f"  P/E {x(m.get('price_to_earnings_ratio'))} | "
        f"EV/EBITDA {x(m.get('enterprise_value_to_ebitda_ratio'))} | "
        f"FCF Yield {pct(m.get('free_cash_flow_yield'))}\n"
        f"  Revenue Growth {pct(m.get('revenue_growth'))} | "
        f"Earnings Growth {pct(m.get('earnings_growth'))} | "
        f"FCF Growth {pct(m.get('free_cash_flow_growth'))}\n"
        f"  ROE {pct(m.get('return_on_equity'))} | "
        f"ROIC {pct(m.get('return_on_invested_capital'))} | "
        f"Gross Margin {pct(m.get('gross_margin'))}"
    )


def run_daily_briefing():
    logger.info("Daily briefing job started")
    db = SessionLocal()
    try:
        # 매크로 지표
        macro_context = ""
        try:
            from services.market_data import get_market_indicators
            indicators = get_market_indicators()
            vix = indicators.get("vix")
            sp500 = indicators.get("sp500")
            kospi = indicators.get("kospi")
            fg = indicators.get("fear_greed")
            parts = []
            if vix:
                parts.append(f"VIX {vix.get('price', 'N/A')} ({vix.get('change_pct', 'N/A')}%)")
            if sp500:
                parts.append(f"S&P500 {sp500.get('price', 'N/A')} ({sp500.get('change_pct', 'N/A')}%)")
            if kospi:
                parts.append(f"KOSPI {kospi.get('price', 'N/A')} ({kospi.get('change_pct', 'N/A')}%)")
            if fg:
                parts.append(f"Fear&Greed {fg.get('score', 'N/A')} ({fg.get('rating', '')})")
            macro_context = " | ".join(parts)
        except Exception:
            logger.warning("Macro indicators fetch failed for briefing")

        tickers = db.query(Ticker).all()

        def build_ticker_dict(t) -> dict:
            d = {
                "symbol": t.symbol, "name": t.name, "market": t.market.value,
                "thesis_status": t.thesis.confirmed.value if t.thesis else None,
            }
            # 포트폴리오 가격 데이터
            if t.portfolio:
                d["current_price"] = t.portfolio.current_price
                d["daily_pct"] = t.portfolio.daily_pct
            # 뉴스 (캐시에서)
            news_data = _get_cache(db, str(t.id), "news")
            snippet = _fmt_news_snippet(news_data, limit=3)
            if snippet:
                d["news_snippet"] = snippet
            return d

        portfolio = [build_ticker_dict(t) for t in tickers if t.status == TickerStatusEnum.PORTFOLIO]
        watchlist = [build_ticker_dict(t) for t in tickers if t.status == TickerStatusEnum.WATCHLIST]

        sections = generate_daily_briefing(portfolio, watchlist, macro_context=macro_context)

        report = Report(ticker_id=None, type=ReportTypeEnum.DAILY_BRIEF, content=sections["full_text"])
        db.add(report)
        db.commit()
        logger.info("Daily briefing saved (report_id=%s)", report.id)

        notify_daily_briefing(str(report.id), sections.get("macro", ""))
    except Exception:
        logger.exception("Daily briefing job failed")
    finally:
        db.close()


def run_break_monitor_job():
    """confirmed + daily_alert=True 종목 Break Monitor 실행."""
    logger.info("Break Monitor job started")
    db = SessionLocal()
    try:
        tickers = (
            db.query(Ticker)
            .filter(Ticker.daily_alert == True)  # noqa: E712
            .all()
        )
        targets = [
            t for t in tickers
            if t.thesis and t.thesis.confirmed == ThesisStatusEnum.CONFIRMED
        ]
        logger.info("Break Monitor 대상: %d종목", len(targets))

        for ticker in targets:
            try:
                # 뉴스 + 지표 캐시에서 조회
                news_data = _get_cache(db, str(ticker.id), "news")
                metrics_data = _get_cache(db, str(ticker.id), "metrics")
                news_context = _fmt_news_full(news_data, limit=7)
                metrics_context = _fmt_metrics(metrics_data)

                result = run_break_monitor(
                    symbol=ticker.symbol,
                    name=ticker.name,
                    ticker_id=str(ticker.id),
                    thesis=ticker.thesis.thesis or "",
                    key_assumptions=ticker.thesis.key_assumptions or "",
                    news_context=news_context,
                    metrics_context=metrics_context,
                )
                notify_break_monitor(
                    ticker.symbol, ticker.name,
                    result["signal"], result.get("assessment", ""),
                    ticker_id=str(ticker.id),
                )
                logger.info("Break Monitor %s → %s", ticker.symbol, result["signal"])
            except Exception:
                logger.exception("Break Monitor 실패: %s", ticker.symbol)
    finally:
        db.close()


def run_light_refresh():
    """
    매일 06:00 KST — 전체 종목의 news / metrics / insider_trades 캐시 갱신.
    재무제표(income/balance/cashflow)는 건드리지 않음.
    """
    logger.info("Light refresh job started")
    db = SessionLocal()
    try:
        tickers = db.query(Ticker).all()
        logger.info("Light refresh 대상: %d종목", len(tickers))

        for ticker in tickers:
            try:
                _refresh_light_cache(db, ticker.symbol, str(ticker.id), ticker.market.value, ticker.name)
                if ticker.portfolio:
                    _refresh_portfolio_quote(db, ticker)
            except Exception:
                logger.exception("Light refresh 실패: %s", ticker.symbol)
    finally:
        db.close()
    logger.info("Light refresh job complete")


def _refresh_portfolio_quote(db, ticker: Ticker) -> bool:
    """yfinance/Yahoo quote로 Portfolio 현재가와 일간 등락률만 갱신."""
    from services.market_data import get_yahoo_quote

    symbols = [ticker.symbol]
    if ticker.market.value == "KR_Stock":
        base = ticker.symbol.zfill(6)
        symbols = [f"{base}.KS", f"{base}.KQ"]

    quote = None
    for yf_symbol in symbols:
        quote = get_yahoo_quote(yf_symbol)
        if quote and quote.get("price"):
            break

    if not quote or not quote.get("price"):
        logger.debug("Portfolio quote empty: %s", ticker.symbol)
        return False

    portfolio = db.query(Portfolio).filter(Portfolio.ticker_id == ticker.id).first()
    if not portfolio:
        return False

    portfolio.current_price = quote["price"]
    portfolio.daily_pct = quote.get("change_pct") or 0
    portfolio.updated_at = datetime.utcnow()
    db.commit()
    logger.debug(
        "Portfolio quote updated: %s price=%s daily_pct=%s",
        ticker.symbol,
        portfolio.current_price,
        portfolio.daily_pct,
    )
    return True


def _refresh_light_cache(db, symbol: str, ticker_id: str, market: str = "US_Stock", company_name: str = ""):
    """단일 종목의 news / metrics / insider_trades 캐시 강제 갱신."""
    from models.db import FinancialCache
    from services.financial_data import _cache_set, _QUOTA_EXCEEDED

    if market == "KR_Stock":
        from services.kr_financial_data import (
            _api_dart_disclosures_kr,
            _api_metrics_kr,
            _api_insider_trades_kr,
            _api_naver_news_kr,
        )
        LIGHT_TYPES = {
            "news": _api_dart_disclosures_kr,
            "metrics": _api_metrics_kr,
            "insider_trades": _api_insider_trades_kr,
        }
        for data_type, api_fn in LIGHT_TYPES.items():
            db.query(FinancialCache).filter(
                FinancialCache.ticker_id == ticker_id,
                FinancialCache.data_type == data_type,
            ).delete()
            db.commit()
            data = api_fn(symbol)
            if data:
                _cache_set(db, ticker_id, data_type, data)
                logger.debug("Light refresh OK: %s/%s", symbol, data_type)
            else:
                logger.debug("Light refresh empty: %s/%s", symbol, data_type)
        # 네이버 뉴스 갱신
        if company_name:
            db.query(FinancialCache).filter(
                FinancialCache.ticker_id == ticker_id,
                FinancialCache.data_type == "naver_news",
            ).delete()
            db.commit()
            naver_data = _api_naver_news_kr(company_name)
            if naver_data:
                _cache_set(db, ticker_id, "naver_news", naver_data)
                logger.debug("Light refresh naver_news OK: %s", symbol)
    else:
        from services.financial_data import _api_news, _api_metrics, _api_insider_trades, _fetch_us_yfinance

        LIGHT_TYPES = {"news": _api_news, "metrics": _api_metrics, "insider_trades": _api_insider_trades}
        quota_hit = False
        for data_type, api_fn in LIGHT_TYPES.items():
            db.query(FinancialCache).filter(
                FinancialCache.ticker_id == ticker_id,
                FinancialCache.data_type == data_type,
            ).delete()
            db.commit()
            data = api_fn(symbol)
            if data is _QUOTA_EXCEEDED:
                quota_hit = True
            elif data:
                _cache_set(db, ticker_id, data_type, data)
                logger.debug("Light refresh OK: %s/%s", symbol, data_type)
            else:
                logger.debug("Light refresh empty: %s/%s", symbol, data_type)

        # financialdatasets.ai 한도 초과 시 yfinance로 news + metrics 갱신
        if quota_hit:
            logger.info("Light refresh yfinance fallback: %s", symbol)
            result = _fetch_us_yfinance(symbol)
            if result.get("_metrics"):
                _cache_set(db, ticker_id, "metrics", [result["_metrics"]])
                logger.debug("Light refresh yfinance metrics OK: %s", symbol)
            if result.get("_news_raw"):
                _cache_set(db, ticker_id, "news", result["_news_raw"])
                logger.debug("Light refresh yfinance news OK: %s", symbol)


def start_scheduler():
    scheduler.add_job(
        run_light_refresh,
        CronTrigger(hour=6, minute=0, timezone="Asia/Seoul"),
        id="light_refresh",
        replace_existing=True,
    )
    scheduler.add_job(
        run_daily_briefing,
        CronTrigger(hour=7, minute=0, timezone="Asia/Seoul"),
        id="daily_briefing",
        replace_existing=True,
    )
    scheduler.add_job(
        run_break_monitor_job,
        CronTrigger(hour=8, minute=0, timezone="Asia/Seoul"),
        id="break_monitor",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler started — light_refresh 06:00 / briefing 07:00 / break_monitor 08:00 KST")


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
