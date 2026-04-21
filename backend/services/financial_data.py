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


# ── yfinance Fallback (financialdatasets.ai 402 시 자동 전환) ────────────────

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

def fetch_all(ticker: str, ticker_id: str | None = None, db=None, market: str = "US_Stock", company_name: str = "") -> dict:
    """
    종목의 전체 재무 데이터 수집.
    market="KR_Stock"이면 kr_financial_data.py로 dispatch.
    db + ticker_id 제공 시 DB 캐시 우선 사용.
    참고: virattt/ai-hedge-fund/src/tools/api.py
    """
    if market == "KR_Stock":
        from services.kr_financial_data import fetch_all_kr
        return fetch_all_kr(ticker, ticker_id=ticker_id, db=db, company_name=company_name)

    if db and ticker_id:
        income_stmts   = _fetch_cached(db, ticker_id, ticker, "income",         _api_income)
        balance_sheets = _fetch_cached(db, ticker_id, ticker, "balance",        _api_balance)
        cash_flows     = _fetch_cached(db, ticker_id, ticker, "cashflow",       _api_cashflow)
        metrics_list   = _fetch_cached(db, ticker_id, ticker, "metrics",        _api_metrics)
        news           = _fetch_cached(db, ticker_id, ticker, "news",           _api_news)
        insider_trades = _fetch_cached(db, ticker_id, ticker, "insider_trades", _api_insider_trades)
        facts          = _fetch_cached(db, ticker_id, ticker, "facts",          _api_facts)
    else:
        income_stmts   = _api_income(ticker)
        balance_sheets = _api_balance(ticker)
        cash_flows     = _api_cashflow(ticker)
        metrics_list   = _api_metrics(ticker)
        news           = _api_news(ticker)
        insider_trades = _api_insider_trades(ticker)
        facts          = _api_facts(ticker)

    # 402 감지: income 또는 metrics가 quota exceeded면 yfinance로 전환
    if income_stmts is _QUOTA_EXCEEDED or metrics_list is _QUOTA_EXCEEDED:
        logger.info("financialdatasets quota exceeded, switching to yfinance for %s", ticker)
        result = _fetch_us_yfinance(ticker)
        if db and ticker_id and result.get("has_data"):
            _cache_set(db, ticker_id, "metrics", [result.get("_metrics", {})])
            if result.get("_news_raw"):
                _cache_set(db, ticker_id, "news", result["_news_raw"])
        return result

    # metrics: API는 list, facts: API는 dict — 캐시 저장 시 맞춰야 함
    if isinstance(metrics_list, list):
        metrics = metrics_list[0] if metrics_list else {}
    else:
        metrics = {}
    if not isinstance(facts, dict):
        facts = {}
    # 나머지 필드도 sentinel 정리
    if income_stmts   is _QUOTA_EXCEEDED: income_stmts   = []
    if balance_sheets is _QUOTA_EXCEEDED: balance_sheets = []
    if cash_flows     is _QUOTA_EXCEEDED: cash_flows     = []
    if news           is _QUOTA_EXCEEDED: news           = []
    if insider_trades is _QUOTA_EXCEEDED: insider_trades = []

    # ── Income Table ──────────────────────────────────────────────────────────
    income_rows = []
    for i, stmt in enumerate(income_stmts):
        period = (stmt.get("report_period") or "")[:4]
        prev = income_stmts[i + 1] if i + 1 < len(income_stmts) else None
        income_rows.append(
            f"  {period} | Revenue {_B(stmt.get('revenue'))} ({_yoy(stmt.get('revenue'), prev.get('revenue') if prev else None)})"
            f" | Gross {_B(stmt.get('gross_profit'))} ({_pct(stmt.get('gross_profit')/stmt.get('revenue') if stmt.get('revenue') else None)} margin)"
            f" | OpInc {_B(stmt.get('operating_income'))}"
            f" | NetInc {_B(stmt.get('net_income'))}"
            f" | EPS ${stmt.get('earnings_per_share_diluted') or 'N/A'}"
            f" | R&D {_B(stmt.get('research_and_development'))}"
        )

    # ── Cash Flow Table ───────────────────────────────────────────────────────
    cf_rows = []
    for idx, stmt in enumerate(cash_flows):
        period = (stmt.get("report_period") or "")[:4]
        ocf = stmt.get("net_cash_flow_from_operations")
        capex = stmt.get("capital_expenditure")
        fcf = stmt.get("free_cash_flow")
        if fcf is None and ocf is not None and capex is not None:
            fcf = ocf - abs(capex)
        buybacks = stmt.get("issuance_or_purchase_of_equity_shares")
        divs = stmt.get("dividends_and_other_cash_distributions")
        rev = income_stmts[idx].get("revenue") if idx < len(income_stmts) else None
        cf_rows.append(
            f"  {period} | OCF {_B(ocf)}"
            f" | Capex {_B(abs(capex) if capex else None)}"
            f" | FCF {_B(fcf)} ({_pct(fcf/rev if fcf and rev else None)} of rev)"
            f" | Buybacks {_B(abs(buybacks) if buybacks and buybacks < 0 else None)}"
            f" | Dividends {_B(abs(divs) if divs and divs < 0 else None)}"
        )

    # ── Balance Sheet Table ───────────────────────────────────────────────────
    bs_rows = []
    for idx, stmt in enumerate(balance_sheets):
        period = (stmt.get("report_period") or "")[:4]
        total_debt = stmt.get("total_debt")
        cash_eq = stmt.get("cash_and_equivalents")
        ebitda_approx = None
        matching_inc = next(
            (s for s in income_stmts if (s.get("report_period") or "")[:4] == period), None
        )
        if matching_inc:
            op_inc = matching_inc.get("operating_income")
            da = next(
                (c.get("depreciation_and_amortization") for c in cash_flows if (c.get("report_period") or "")[:4] == period),
                None,
            )
            if op_inc and da:
                ebitda_approx = op_inc + da
        net_debt = (total_debt or 0) - (cash_eq or 0)
        bs_rows.append(
            f"  {period} | Assets {_B(stmt.get('total_assets'))}"
            f" | Cash {_B(cash_eq)}"
            f" | TotalDebt {_B(total_debt)}"
            f" | Equity {_B(stmt.get('shareholders_equity'))}"
            f" | Net Debt {_B(net_debt)}"
            f" | NetDebt/EBITDA {_x(net_debt / ebitda_approx if total_debt and ebitda_approx else None)}"
        )

    # ── Key Metrics (TTM) ─────────────────────────────────────────────────────
    km = metrics
    key_metrics_text = f"""
  Valuation   : Market Cap {_B(km.get('market_cap'))} | EV {_B(km.get('enterprise_value'))}
                P/E {_x(km.get('price_to_earnings_ratio'))} | P/B {_x(km.get('price_to_book_ratio'))}
                P/S {_x(km.get('price_to_sales_ratio'))} | EV/EBITDA {_x(km.get('enterprise_value_to_ebitda_ratio'))}
                FCF Yield {_pct(km.get('free_cash_flow_yield'))} | PEG {_x(km.get('peg_ratio'))}
  Profitability: Gross {_pct(km.get('gross_margin'))} | Operating {_pct(km.get('operating_margin'))} | Net {_pct(km.get('net_margin'))}
  Returns     : ROE {_pct(km.get('return_on_equity'))} | ROA {_pct(km.get('return_on_assets'))} | ROIC {_pct(km.get('return_on_invested_capital'))}
  Growth (YoY): Revenue {_pct(km.get('revenue_growth'))} | Earnings {_pct(km.get('earnings_growth'))} | FCF {_pct(km.get('free_cash_flow_growth'))}
  Solvency    : Debt/Equity {_x(km.get('debt_to_equity'))} | Current Ratio {_x(km.get('current_ratio'))} | Interest Coverage {_x(km.get('interest_coverage'))}
  Per Share   : EPS {_dollar(km.get('earnings_per_share'))} | FCF/Share {_dollar(km.get('free_cash_flow_per_share'))} | BV/Share {_dollar(km.get('book_value_per_share'))}
"""

    # ── News ──────────────────────────────────────────────────────────────────
    news_list = news if isinstance(news, list) else []
    news_text = "\n".join(
        f"  [{n.get('date', '')[:10]}] {n.get('title', '')} ({n.get('source', '')})"
        for n in news_list[:10]
    ) or "  최근 뉴스 없음 (US 종목이 아니거나 데이터 미확인)"

    # ── Insider Trades ────────────────────────────────────────────────────────
    trades_list = insider_trades if isinstance(insider_trades, list) else []
    insider_rows = []
    buy_count = sell_count = 0
    for t in trades_list[:20]:
        tx_type = t.get("transaction_type", "")
        shares = t.get("transaction_shares")
        value = t.get("transaction_value")
        name = t.get("name", "Unknown")
        title = t.get("title", "")
        date = (t.get("transaction_date") or t.get("filing_date") or "")[:10]
        is_buy  = "purchase" in tx_type.lower() or tx_type.lower() == "buy"
        is_sell = "sale" in tx_type.lower() or tx_type.lower() == "sell"
        if is_buy:
            buy_count += 1
        elif is_sell:
            sell_count += 1
        shares_fmt = f"{int(shares):,}" if shares else "N/A"
        value_fmt = _B(value) if value else "N/A"
        insider_rows.append(
            f"  {date} | {tx_type[:30]:<30} | {name} ({title[:30]}) | Shares: {shares_fmt} | Value: {value_fmt}"
        )
    insider_summary = f"  순매수 {buy_count}건 / 순매도 {sell_count}건 / 총 {len(trades_list)}건 (최근)"
    insider_text = insider_summary + "\n" + ("\n".join(insider_rows) or "  데이터 없음")

    # ── Company Facts ─────────────────────────────────────────────────────────
    company_text = (
        f"  Sector: {facts.get('sector', 'N/A')} | Industry: {facts.get('industry', 'N/A')}"
        f" | Exchange: {facts.get('exchange', 'N/A')} | Location: {facts.get('location', 'N/A')}"
    )

    # filing URLs for SEC pipeline — annual이므로 period는 4자리 연도 (10-K 판별 기준)
    filing_refs = [
        {"period": (s.get("report_period") or "")[:4], "url": s.get("filing_url"), "accession": s.get("accession_number")}
        for s in income_stmts if s.get("filing_url")
    ]

    return {
        "income_table":   "\n".join(income_rows) or "  데이터 없음",
        "cf_table":       "\n".join(cf_rows) or "  데이터 없음",
        "bs_table":       "\n".join(bs_rows) or "  데이터 없음",
        "key_metrics":    key_metrics_text,
        "news":           news_text,
        "insider_trades": insider_text,
        "company_info":   company_text,
        "filing_refs":    filing_refs,
        "has_data":       bool(income_stmts or metrics_list),
        "_metrics":       km,
        "_income":        income_stmts,
        "_cf":            cash_flows,
    }
