"""
financialdatasets.ai API 래퍼 + PostgreSQL 캐시 레이어.
참고: virattt/ai-hedge-fund/src/tools/api.py

캐시 TTL:
  income / balance / cashflow : 90일  (분기 공시 주기)
  metrics / news               : 24시간
  insider_trades               : 3일
  facts                        : 30일
"""
import logging
import os
import time
from datetime import datetime, timedelta

import requests

logger = logging.getLogger(__name__)

_BASE = "https://api.financialdatasets.ai"

_TTL: dict[str, timedelta] = {
    "income":         timedelta(days=90),
    "balance":        timedelta(days=90),
    "cashflow":       timedelta(days=90),
    "metrics":        timedelta(hours=24),
    "news":           timedelta(hours=24),
    "naver_news":     timedelta(hours=24),
    "insider_trades": timedelta(days=3),
    "facts":          timedelta(days=30),
    "yfinance_data":  timedelta(hours=24),  # US yfinance 통합 캐시
}


def _headers() -> dict:
    key = os.environ.get("FINANCIAL_DATASETS_API_KEY", "")
    return {"X-API-KEY": key} if key else {}


_QUOTA_EXCEEDED = object()  # sentinel: 402 Payment Required


def _get(path: str, params: dict | None = None):
    try:
        resp = requests.get(f"{_BASE}{path}", headers=_headers(), params=params, timeout=15)
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 402:
            logger.warning("financialdatasets quota exceeded (402): %s", path)
            return _QUOTA_EXCEEDED
        logger.warning("financialdatasets %s → %s", path, resp.status_code)
        return {}
    except Exception as e:
        logger.warning("financialdatasets request failed %s: %s", path, e)
        return {}


# ── Raw API fetchers ──────────────────────────────────────────────────────────

def _api_income(ticker: str):
    r = _get("/financials/income-statements/", {"ticker": ticker, "period": "annual", "limit": 5})
    if r is _QUOTA_EXCEEDED: return _QUOTA_EXCEEDED
    return r.get("income_statements", [])

def _api_balance(ticker: str):
    r = _get("/financials/balance-sheets/", {"ticker": ticker, "period": "annual", "limit": 5})
    if r is _QUOTA_EXCEEDED: return _QUOTA_EXCEEDED
    return r.get("balance_sheets", [])

def _api_cashflow(ticker: str):
    r = _get("/financials/cash-flow-statements/", {"ticker": ticker, "period": "annual", "limit": 5})
    if r is _QUOTA_EXCEEDED: return _QUOTA_EXCEEDED
    return r.get("cash_flow_statements", [])

def _api_metrics(ticker: str):
    r = _get("/financial-metrics/", {"ticker": ticker, "period": "ttm", "limit": 1})
    if r is _QUOTA_EXCEEDED: return _QUOTA_EXCEEDED
    return r.get("financial_metrics", [])

def _api_news(ticker: str):
    r = _get("/news/", {"ticker": ticker, "limit": 10})
    if r is _QUOTA_EXCEEDED: return _QUOTA_EXCEEDED
    return r.get("news", [])

def _api_insider_trades(ticker: str):
    r = _get("/insider-trades/", {"ticker": ticker, "limit": 20})
    if r is _QUOTA_EXCEEDED: return _QUOTA_EXCEEDED
    return r.get("insider_trades", [])

def _api_facts(ticker: str) -> dict:
    return _get("/company/facts/", {"ticker": ticker}).get("company_facts", {})


# ── DB Cache Layer ────────────────────────────────────────────────────────────

def _cache_get(db, ticker_id: str, data_type: str):
    """캐시 조회. 유효하면 data 반환, 만료/미존재면 None."""
    from models.db import FinancialCache
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


def _cache_set(db, ticker_id: str, data_type: str, data):
    """캐시 저장 또는 갱신."""
    from models.db import FinancialCache
    row = (
        db.query(FinancialCache)
        .filter(
            FinancialCache.ticker_id == ticker_id,
            FinancialCache.data_type == data_type,
        )
        .first()
    )
    expires = datetime.utcnow() + _TTL.get(data_type, timedelta(hours=24))
    if row:
        row.data = data
        row.fetched_at = datetime.utcnow()
        row.expires_at = expires
    else:
        db.add(FinancialCache(
            ticker_id=ticker_id,
            data_type=data_type,
            data=data,
            fetched_at=datetime.utcnow(),
            expires_at=expires,
        ))
    db.commit()


def _fetch_cached(db, ticker_id: str, ticker: str, data_type: str, api_fn):
    """캐시 우선 조회, 없으면 API 호출 후 저장. 402 시 _QUOTA_EXCEEDED 반환."""
    cached = _cache_get(db, ticker_id, data_type)
    if cached is not None:
        logger.debug("cache hit: %s/%s", ticker, data_type)
        return cached
    logger.info("cache miss, fetching: %s/%s", ticker, data_type)
    data = api_fn(ticker)
    if data is _QUOTA_EXCEEDED:
        return _QUOTA_EXCEEDED
    if data:
        _cache_set(db, ticker_id, data_type, data)
    return data


# ── Formatters ────────────────────────────────────────────────────────────────

def _B(v) -> str:
    if v is None:
        return "N/A"
    if abs(v) >= 1e12:
        return f"${v/1e12:.2f}T"
    if abs(v) >= 1e9:
        return f"${v/1e9:.1f}B"
    if abs(v) >= 1e6:
        return f"${v/1e6:.0f}M"
    return f"${v:.0f}"

def _dollar(v) -> str:
    if v is None:
        return "N/A"
    return f"${v:.2f}"

def _pct(v) -> str:
    if v is None:
        return "N/A"
    return f"{v*100:.1f}%"

def _x(v, d: int = 2) -> str:
    if v is None or abs(v) < 0.001:
        return "N/A"
    return f"{v:.{d}f}x"

def _yoy(curr, prev) -> str:
    if curr is None or prev is None or prev == 0:
        return "N/A"
    return f"{(curr - prev) / abs(prev) * 100:+.1f}%"


# ── EDGAR CIK lookup + filing refs (yfinance fallback용) ─────────────────────

_EDGAR_HEADERS = {
    "User-Agent": "value-copilot research@example.com",
    "Accept-Encoding": "gzip, deflate",
}

def _get_edgar_filing_refs(ticker: str) -> list:
    """EDGAR API로 최근 10-K/10-Q filing index URL 목록 반환 (최대 4건)."""
    try:
        # Step 1: ticker → CIK
        r = requests.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers=_EDGAR_HEADERS, timeout=10,
        )
        if r.status_code != 200:
            return []
        cik = None
        for entry in r.json().values():
            if entry.get("ticker", "").upper() == ticker.upper():
                cik = str(entry["cik_str"]).zfill(10)
                break
        if not cik:
            logger.warning("EDGAR: CIK not found for %s", ticker)
            return []

        # Step 2: recent filings from submissions API
        r2 = requests.get(
            f"https://data.sec.gov/submissions/CIK{cik}.json",
            headers=_EDGAR_HEADERS, timeout=10,
        )
        if r2.status_code != 200:
            return []
        recent = r2.json().get("filings", {}).get("recent", {})
        forms        = recent.get("form", [])
        accessions   = recent.get("accessionNumber", [])
        report_dates = recent.get("reportDate", [])
        primary_docs = recent.get("primaryDocument", [])

        refs = []
        for i, form in enumerate(forms):
            if form not in ("10-K", "10-Q"):
                continue
            acc_clean = accessions[i].replace("-", "")
            cik_int = int(cik)
            raw_date = report_dates[i] if i < len(report_dates) else ""
            # 10-K period: "2024" (4자), 10-Q period: "2024-03" (7자)
            period = raw_date[:4] if form == "10-K" else raw_date[:7]
            primary_doc = primary_docs[i] if i < len(primary_docs) else ""
            # primaryDocument로 직접 주 문서 URL 구성 (index 파싱 불필요)
            if primary_doc and primary_doc.endswith(('.htm', '.html')):
                doc_url = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_clean}/{primary_doc}"
            else:
                doc_url = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_clean}/"
            refs.append({
                "period":    period,
                "url":       doc_url,
                "accession": accessions[i],
            })
            if len(refs) >= 6:
                break
        logger.info("EDGAR filing refs for %s: %d found", ticker, len(refs))
        return refs
    except Exception as e:
        logger.warning("EDGAR filing refs failed for %s: %s", ticker, e)
        return []


# ── financialdatasets.ai US fetcher ──────────────────────────────────────────

def _fetch_us_financialdatasets(ticker: str, ticker_id: str, db) -> dict:
    """financialdatasets.ai로 US 종목 재무 데이터 수집."""
    income_data   = _fetch_cached(db, ticker_id, ticker, "income", _api_income)
    balance_data  = _fetch_cached(db, ticker_id, ticker, "balance", _api_balance)
    cashflow_data = _fetch_cached(db, ticker_id, ticker, "cashflow", _api_cashflow)
    metrics_data  = _fetch_cached(db, ticker_id, ticker, "metrics", _api_metrics)
    news_data     = _fetch_cached(db, ticker_id, ticker, "news", _api_news)
    insider_data  = _fetch_cached(db, ticker_id, ticker, "insider_trades", _api_insider_trades)

    for d in [income_data, balance_data, cashflow_data, metrics_data, news_data, insider_data]:
        if d is _QUOTA_EXCEEDED:
            logger.warning("financialdatasets quota exceeded for %s", ticker)
            return {"has_data": False}

    # Income
    income_rows = []
    stmts = income_data or []
    for i, s in enumerate(stmts[:5]):
        rev = s.get('revenue')
        gp  = s.get('gross_profit')
        op  = s.get('operating_income')
        ni  = s.get('net_income')
        prev_rev = stmts[i + 1].get('revenue') if i + 1 < len(stmts) else None
        income_rows.append(
            f"  {s.get('report_period','?')} | Revenue {_B(rev)} ({_yoy(rev, prev_rev)})"
            f" | Gross {_B(gp)} ({_pct(gp / rev if gp and rev else None)} margin)"
            f" | OpInc {_B(op)} | NetInc {_B(ni)}"
        )

    # Cash flow
    cf_rows = []
    for s in (cashflow_data or [])[:5]:
        ocf   = s.get('operating_cash_flow')
        capex = s.get('capital_expenditure')
        fcf   = s.get('free_cash_flow')
        cf_rows.append(
            f"  {s.get('report_period','?')} | OCF {_B(ocf)}"
            f" | Capex {_B(abs(capex) if capex else None)}"
            f" | FCF {_B(fcf)}"
        )

    # Balance sheet
    bs_rows = []
    for s in (balance_data or [])[:5]:
        assets   = s.get('total_assets')
        cash     = s.get('cash_and_equivalents')
        debt     = s.get('total_debt')
        equity   = s.get('shareholders_equity')
        net_debt = (debt or 0) - (cash or 0)
        bs_rows.append(
            f"  {s.get('report_period','?')} | Assets {_B(assets)} | Cash {_B(cash)}"
            f" | TotalDebt {_B(debt)} | Equity {_B(equity)} | Net Debt {_B(net_debt)}"
        )

    # Metrics
    km = (metrics_data or [{}])[0] if metrics_data else {}
    mktcap = km.get('market_capitalization')
    key_metrics_text = f"""
  Valuation   : Market Cap {_B(mktcap)} | EV {_B(km.get('enterprise_value'))}
                P/E {_x(km.get('price_to_earnings_ratio'))} | P/B {_x(km.get('price_to_book_ratio'))}
                P/S {_x(km.get('price_to_sales_ratio'))} | EV/EBITDA {_x(km.get('enterprise_value_to_ebitda_ratio'))}
                FCF Yield {_pct(km.get('free_cash_flow_yield'))}
  Profitability: Gross {_pct(km.get('gross_margin'))} | Operating {_pct(km.get('operating_margin'))} | Net {_pct(km.get('net_profit_margin'))}
  Returns     : ROE {_pct(km.get('return_on_equity'))} | ROA {_pct(km.get('return_on_assets'))}
  Growth (YoY): Revenue {_pct(km.get('revenue_growth'))} | Earnings {_pct(km.get('earnings_growth'))}
  Solvency    : Debt/Equity {_x(km.get('debt_to_equity'))} | Current Ratio {_x(km.get('current_ratio'))}
  Per Share   : EPS {_dollar(km.get('earnings_per_share'))} | BV/Share {_dollar(km.get('book_value_per_share'))}
  Price       : {_dollar(km.get('current_price'))}
  Source      : financialdatasets.ai
"""

    # News
    news_rows = []
    news_parsed = []
    for n in (news_data or [])[:10]:
        title = n.get('title', '')
        date  = (n.get('date') or '')[:10]
        src   = n.get('source', '')
        news_rows.append(f"  [{date}] {title} ({src})")
        news_parsed.append({"title": title, "date": date, "source": src})

    # Insider trades
    insider_rows = []
    for t in (insider_data or [])[:10]:
        insider_rows.append(
            f"  {(t.get('transaction_date') or '?')[:10]} | {t.get('insider_name','?')} ({t.get('title','?')})"
            f" | {t.get('transaction_type','?')} {_B(t.get('value'))}"
        )

    filing_refs = _get_edgar_filing_refs(ticker)
    has_data = bool(income_rows or mktcap)

    return {
        "income_table":   "\n".join(income_rows) or "  데이터 없음",
        "cf_table":       "\n".join(cf_rows) or "  데이터 없음",
        "bs_table":       "\n".join(bs_rows) or "  데이터 없음",
        "key_metrics":    key_metrics_text,
        "news":           "\n".join(news_rows) or "  뉴스 없음",
        "insider_trades": "\n".join(insider_rows) or "  내부자 거래 없음",
        "company_info":   "",
        "filing_refs":    filing_refs,
        "has_data":       has_data,
        "_metrics":       km,
        "_income":        income_rows,
        "_cf":            cf_rows,
        "_news_raw":      news_parsed,
    }


# ── yfinance US fetcher ───────────────────────────────────────────────────────

def _fetch_us_yfinance(ticker: str) -> dict:
    """yfinance로 US 종목 재무 데이터 수집 (financialdatasets.ai 한도 초과 시 fallback)."""
    import yfinance as yf
    import datetime as dt
    logger.info("yfinance fallback for US ticker: %s", ticker)
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}

        # ── Income Statement ──────────────────────────────────────────────────
        income_rows = []
        try:
            fin = t.financials  # rows=metrics, cols=dates newest-first
            cols = list(fin.columns)[:5]
            for i, col in enumerate(cols):
                year = str(col.year)
                def _g(row, c=col):
                    for name in ([row] if isinstance(row, str) else row):
                        try:
                            v = fin.loc[name, c]
                            return None if (v != v) else v  # NaN → None
                        except Exception:
                            pass
                    return None
                rev = _g(['Total Revenue'])
                gp  = _g(['Gross Profit'])
                op  = _g(['Operating Income', 'Total Operating Income As Reported'])
                ni  = _g(['Net Income', 'Net Income Common Stockholders'])
                prev_col = cols[i + 1] if i + 1 < len(cols) else None
                prev_rev = None
                if prev_col is not None:
                    try:
                        v = fin.loc['Total Revenue', prev_col]
                        prev_rev = None if (v != v) else v
                    except Exception:
                        pass
                income_rows.append(
                    f"  {year} | Revenue {_B(rev)} ({_yoy(rev, prev_rev)})"
                    f" | Gross {_B(gp)} ({_pct(gp / rev if gp and rev else None)} margin)"
                    f" | OpInc {_B(op)} | NetInc {_B(ni)}"
                )
        except Exception as e:
            logger.warning("yfinance income failed %s: %s", ticker, e)

        # ── Cash Flow ─────────────────────────────────────────────────────────
        cf_rows = []
        try:
            cf = t.cashflow
            cols_cf = list(cf.columns)[:5]
            for col in cols_cf:
                year = str(col.year)
                def _gcf(row, c=col):
                    for name in ([row] if isinstance(row, str) else row):
                        try:
                            v = cf.loc[name, c]
                            return None if (v != v) else v
                        except Exception:
                            pass
                    return None
                ocf   = _gcf(['Operating Cash Flow', 'Cash Flow From Continuing Operating Activities'])
                capex = _gcf(['Capital Expenditure'])
                fcf   = _gcf(['Free Cash Flow'])
                if fcf is None and ocf is not None and capex is not None:
                    fcf = ocf + capex  # yfinance capex is negative
                cf_rows.append(
                    f"  {year} | OCF {_B(ocf)}"
                    f" | Capex {_B(abs(capex) if capex is not None else None)}"
                    f" | FCF {_B(fcf)}"
                )
        except Exception as e:
            logger.warning("yfinance cashflow failed %s: %s", ticker, e)

        # ── Balance Sheet ─────────────────────────────────────────────────────
        bs_rows = []
        try:
            bs = t.balance_sheet
            cols_bs = list(bs.columns)[:5]
            for col in cols_bs:
                year = str(col.year)
                def _gbs(row, c=col):
                    for name in ([row] if isinstance(row, str) else row):
                        try:
                            v = bs.loc[name, c]
                            return None if (v != v) else v
                        except Exception:
                            pass
                    return None
                assets  = _gbs(['Total Assets'])
                cash    = _gbs(['Cash And Cash Equivalents', 'Cash Cash Equivalents And Short Term Investments'])
                debt    = _gbs(['Total Debt', 'Long Term Debt'])
                equity  = _gbs(['Stockholders Equity', 'Common Stock Equity'])
                net_debt = (debt or 0) - (cash or 0)
                bs_rows.append(
                    f"  {year} | Assets {_B(assets)} | Cash {_B(cash)}"
                    f" | TotalDebt {_B(debt)} | Equity {_B(equity)} | Net Debt {_B(net_debt)}"
                )
        except Exception as e:
            logger.warning("yfinance balance failed %s: %s", ticker, e)

        # ── Metrics ───────────────────────────────────────────────────────────
        km = {
            'market_cap':                       info.get('marketCap'),
            'market_capitalization':            info.get('marketCap'),
            'enterprise_value':                 info.get('enterpriseValue'),
            'price_to_earnings_ratio':          info.get('trailingPE') or info.get('forwardPE'),
            'price_to_book_ratio':              info.get('priceToBook'),
            'price_to_sales_ratio':             info.get('priceToSalesTrailing12Months'),
            'enterprise_value_to_ebitda_ratio': info.get('enterpriseToEbitda'),
            'return_on_equity':                 info.get('returnOnEquity'),
            'return_on_assets':                 info.get('returnOnAssets'),
            'operating_margin':                 info.get('operatingMargins'),
            'gross_margin':                     info.get('grossMargins'),
            'net_margin':                       info.get('profitMargins'),
            'revenue_growth':                   info.get('revenueGrowth'),
            'earnings_growth':                  info.get('earningsGrowth'),
            'dividend_yield':                   info.get('dividendYield'),
            'current_price':                    info.get('currentPrice') or info.get('regularMarketPrice'),
            'debt_to_equity':                   (info.get('debtToEquity') or 0) / 100 if info.get('debtToEquity') else None,
            'current_ratio':                    info.get('currentRatio'),
            'earnings_per_share':               info.get('trailingEps'),
            'book_value_per_share':             info.get('bookValue'),
        }
        fcf_ttm = info.get('freeCashflow')
        mktcap  = km.get('market_cap')
        if fcf_ttm and mktcap:
            km['free_cash_flow_yield'] = fcf_ttm / mktcap

        key_metrics_text = f"""
  Valuation   : Market Cap {_B(km.get('market_cap'))} | EV {_B(km.get('enterprise_value'))}
                P/E {_x(km.get('price_to_earnings_ratio'))} | P/B {_x(km.get('price_to_book_ratio'))}
                P/S {_x(km.get('price_to_sales_ratio'))} | EV/EBITDA {_x(km.get('enterprise_value_to_ebitda_ratio'))}
                FCF Yield {_pct(km.get('free_cash_flow_yield'))}
  Profitability: Gross {_pct(km.get('gross_margin'))} | Operating {_pct(km.get('operating_margin'))} | Net {_pct(km.get('net_margin'))}
  Returns     : ROE {_pct(km.get('return_on_equity'))} | ROA {_pct(km.get('return_on_assets'))}
  Growth (YoY): Revenue {_pct(km.get('revenue_growth'))} | Earnings {_pct(km.get('earnings_growth'))}
  Solvency    : Debt/Equity {_x(km.get('debt_to_equity'))} | Current Ratio {_x(km.get('current_ratio'))}
  Per Share   : EPS {_dollar(km.get('earnings_per_share'))} | BV/Share {_dollar(km.get('book_value_per_share'))}
  Price       : {_dollar(km.get('current_price'))}
  Source      : Yahoo Finance (yfinance fallback)
"""

        # ── News ──────────────────────────────────────────────────────────────
        # yfinance >= 0.2.50: {'id': ..., 'content': {'title': ..., 'pubDate': ..., 'provider': {...}}}
        # yfinance < 0.2.50:  {'title': ..., 'publisher': ..., 'providerPublishTime': int}
        news_text = "  뉴스 없음"
        news_parsed = []
        try:
            news_list = t.news or []
            rows = []
            for n in news_list[:10]:
                content = n.get('content') or n  # 신/구 포맷 모두 처리
                title = content.get('title', '')
                if not title:
                    continue
                pub_date = content.get('pubDate', '')  # "2026-04-20T03:41:32Z"
                if pub_date:
                    date_str = pub_date[:10]
                else:
                    ts = n.get('providerPublishTime')
                    date_str = dt.datetime.fromtimestamp(ts).strftime('%Y-%m-%d') if ts else ''
                provider = (
                    content.get('provider', {}).get('displayName', '')
                    or n.get('publisher', '')
                )
                rows.append(f"  [{date_str}] {title} ({provider})")
                news_parsed.append({"title": title, "date": date_str, "source": provider})
            news_text = "\n".join(rows) or "  뉴스 없음"
        except Exception as e:
            logger.warning("yfinance news failed %s: %s", ticker, e)

        # ── Company info ──────────────────────────────────────────────────────
        company_text = (
            f"  Sector: {info.get('sector', 'N/A')} | Industry: {info.get('industry', 'N/A')}"
            f" | Exchange: {info.get('exchange', 'N/A')}"
            f" | Location: {info.get('city', 'N/A')}, {info.get('country', 'N/A')}"
        )

        # EDGAR filing refs — SEC 파이프라인이 이걸 보고 10-K/10-Q 요약 실행
        filing_refs = _get_edgar_filing_refs(ticker)

        has_data = bool(income_rows or km.get('market_cap'))
        return {
            "income_table":   "\n".join(income_rows) or "  데이터 없음",
            "cf_table":       "\n".join(cf_rows) or "  데이터 없음",
            "bs_table":       "\n".join(bs_rows) or "  데이터 없음",
            "key_metrics":    key_metrics_text,
            "news":           news_text,
            "insider_trades": "  내부자 거래: financialdatasets.ai 유료 플랜에서 지원",
            "company_info":   company_text,
            "filing_refs":    filing_refs,
            "has_data":       has_data,
            "_metrics":       km,
            "_income":        income_rows,
            "_cf":            cf_rows,
            "_news_raw":      news_parsed,
        }
    except Exception as e:
        logger.error("yfinance fallback failed for %s: %s", ticker, e)
        return {
            "has_data": False, "_metrics": {}, "_income": [], "_cf": [],
            "income_table": "  데이터 없음", "cf_table": "  데이터 없음",
            "bs_table": "  데이터 없음", "key_metrics": "", "news": "  데이터 없음",
            "insider_trades": "  데이터 없음", "company_info": "  데이터 없음", "filing_refs": [],
        }


# ── Main aggregator ───────────────────────────────────────────────────────────

def _get_us_data_source(db) -> str:
    """DB 설정에서 US 데이터 소스 조회. 기본값 yfinance."""
    if not db:
        return "yfinance"
    try:
        from models.db import Settings
        row = db.query(Settings).filter(Settings.key == "us_data_source").first()
        return row.value if row else "yfinance"
    except Exception:
        return "yfinance"


def fetch_all(ticker: str, ticker_id: str | None = None, db=None, market: str = "US_Stock", company_name: str = "") -> dict:
    """
    종목의 전체 재무 데이터 수집.
    market="KR_Stock"이면 kr_financial_data.py로 dispatch.
    US 주식은 설정에 따라 yfinance 또는 financialdatasets.ai 사용.
    db + ticker_id 제공 시 DB 캐시 우선 사용.
    """
    if market == "KR_Stock":
        from services.kr_financial_data import fetch_all_kr
        return fetch_all_kr(ticker, ticker_id=ticker_id, db=db, company_name=company_name)

    source = _get_us_data_source(db)
    logger.info("US data source for %s: %s", ticker, source)

    if source == "financialdatasets" and db and ticker_id:
        result = _fetch_us_financialdatasets(ticker, ticker_id, db)
        if result.get("has_data"):
            return result
        logger.warning("financialdatasets failed for %s, falling back to yfinance", ticker)

    # yfinance path (default or fallback)
    if db and ticker_id:
        cached = _cache_get(db, ticker_id, "yfinance_data")
        if cached is not None:
            logger.debug("yfinance_data cache hit: %s", ticker)
            return cached

    time.sleep(1)
    result = _fetch_us_yfinance(ticker)

    if db and ticker_id and result.get("has_data"):
        _cache_set(db, ticker_id, "yfinance_data", result)

    return result
