"""
한국 주식 재무 데이터 — OpenDART API + pykrx.
financialdatasets.ai 대응 구조. fetch_all_kr() 반환 형식을 US와 동일하게 맞춤.

데이터 소스:
  OpenDART : 재무제표(XBRL) / 공시 목록(뉴스 대용) / 임원 주식 변동
  pykrx    : PER / PBR / EPS / 시가총액 등 시장 지표
"""
import io
import json
import logging
import os
import zipfile
from datetime import datetime, timedelta
from functools import lru_cache

import requests

logger = logging.getLogger(__name__)

_DART_BASE = "https://opendart.fss.or.kr/api"
_CORP_CODE_CACHE_PATH = "/tmp/dart_corp_codes.json"


def _dart_key() -> str:
    return os.environ.get("OPENDART_API_KEY", "")


def _dart_get(path: str, params: dict) -> dict:
    params["crtfc_key"] = _dart_key()
    try:
        resp = requests.get(f"{_DART_BASE}{path}", params=params, timeout=20)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("status") == "000":
                return data
            logger.warning("DART %s status=%s msg=%s", path, data.get("status"), data.get("message"))
        else:
            logger.warning("DART %s → HTTP %s", path, resp.status_code)
    except Exception as e:
        logger.warning("DART request failed %s: %s", path, e)
    return {}


# ── Corp Code 조회 ─────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _load_corp_code_map() -> dict[str, str]:
    """stock_code(6자리) → corp_code(8자리) 매핑. 파일 캐시 우선, 없으면 DART ZIP 다운로드."""
    if os.path.exists(_CORP_CODE_CACHE_PATH):
        try:
            with open(_CORP_CODE_CACHE_PATH) as f:
                mapping = json.load(f)
            if mapping:
                logger.debug("DART corp code map from file cache: %d entries", len(mapping))
                return mapping
        except Exception:
            pass

    key = _dart_key()
    if not key:
        logger.warning("OPENDART_API_KEY not set")
        return {}
    try:
        resp = requests.get(
            f"{_DART_BASE}/corpCode.xml",
            params={"crtfc_key": key},
            timeout=30,
        )
        if resp.status_code != 200:
            logger.warning("DART corpCode.xml → HTTP %s", resp.status_code)
            return {}
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            xml_bytes = zf.read("CORPCODE.xml")
        import xml.etree.ElementTree as ET
        mapping = {}
        for _, elem in ET.iterparse(io.BytesIO(xml_bytes)):
            if elem.tag == "list":
                stock_code = (elem.findtext("stock_code") or "").strip()
                corp_code = (elem.findtext("corp_code") or "").strip()
                if stock_code and corp_code:
                    mapping[stock_code] = corp_code
                elem.clear()
        logger.info("DART corp code map loaded: %d entries", len(mapping))
        try:
            with open(_CORP_CODE_CACHE_PATH, "w") as f:
                json.dump(mapping, f)
        except Exception as e:
            logger.warning("Failed to save corp code cache: %s", e)
        return mapping
    except Exception as e:
        logger.warning("DART corp code map load failed: %s", e)
        return {}


def _get_corp_code(symbol: str) -> str | None:
    """종목 코드(005930) → DART corp_code."""
    mapping = _load_corp_code_map()
    return mapping.get(symbol.zfill(6))


# ── 재무제표 파싱 헬퍼 ─────────────────────────────────────────────────────────

def _parse_amount(s) -> float | None:
    if not s:
        return None
    try:
        return float(str(s).replace(",", "").replace(" ", ""))
    except (ValueError, TypeError):
        return None


_ACCOUNT_MAP = {
    "revenue": ["매출액", "영업수익", "수익(매출액)", "매출"],
    "gross_profit": ["매출총이익", "매출총손익"],
    "operating_income": ["영업이익", "영업이익(손실)"],
    "net_income": ["당기순이익", "당기순이익(손실)", "연결당기순이익"],
    "total_assets": ["자산총계"],
    "total_liabilities": ["부채총계"],
    "shareholders_equity": ["자본총계", "지배기업소유주지분"],
    "cash_and_equivalents": ["현금및현금성자산"],
    "total_debt": ["단기차입금", "장기차입금", "사채"],  # 합산 처리
    "operating_cash_flow": ["영업활동현금흐름", "영업활동으로인한현금흐름"],
    "investing_cash_flow": ["투자활동현금흐름", "투자활동으로인한현금흐름"],
    "financing_cash_flow": ["재무활동현금흐름", "재무활동으로인한현금흐름"],
    "capex": ["유형자산의취득", "유형자산취득"],
}


def _find_account(rows: list[dict], *names: str) -> float | None:
    """계정명 목록 중 첫 번째 매칭되는 당기 금액 반환."""
    for name in names:
        for row in rows:
            acct = (row.get("account_nm") or "").replace(" ", "")
            if acct == name.replace(" ", ""):
                return _parse_amount(row.get("thstrm_amount"))
    return None


def _find_account_prev(rows: list[dict], *names: str) -> float | None:
    for name in names:
        for row in rows:
            acct = (row.get("account_nm") or "").replace(" ", "")
            if acct == name.replace(" ", ""):
                return _parse_amount(row.get("frmtrm_amount"))
    return None


def _extract_financials(dart_list: list[dict], sj_div: str) -> list:
    """DART fnlttSinglAcntAll 응답에서 특정 재무제표 섹션만 추출.
    손익계산서는 IS(손익계산서) 또는 CIS(포괄손익계산서) 모두 허용.
    """
    if sj_div == "IS":
        rows = [r for r in dart_list if r.get("sj_div") in ("IS", "CIS")]
    else:
        rows = [r for r in dart_list if r.get("sj_div") == sj_div]
    cfs = [r for r in rows if r.get("fs_div") == "CFS"]
    return cfs if cfs else rows


def _build_year_statement(dart_list: list[dict], bsns_year: str) -> dict:
    """특정 연도 재무 데이터 딕셔너리 구성."""
    is_rows = _extract_financials(dart_list, "IS")
    bs_rows = _extract_financials(dart_list, "BS")
    cf_rows = _extract_financials(dart_list, "CF")

    revenue = _find_account(is_rows, *_ACCOUNT_MAP["revenue"])
    gross = _find_account(is_rows, *_ACCOUNT_MAP["gross_profit"])
    op_inc = _find_account(is_rows, *_ACCOUNT_MAP["operating_income"])
    net_inc = _find_account(is_rows, *_ACCOUNT_MAP["net_income"])

    total_assets = _find_account(bs_rows, *_ACCOUNT_MAP["total_assets"])
    equity = _find_account(bs_rows, *_ACCOUNT_MAP["shareholders_equity"])
    cash = _find_account(bs_rows, *_ACCOUNT_MAP["cash_and_equivalents"])

    ocf = _find_account(cf_rows, *_ACCOUNT_MAP["operating_cash_flow"])
    inv_cf = _find_account(cf_rows, *_ACCOUNT_MAP["investing_cash_flow"])
    capex_raw = _find_account(cf_rows, *_ACCOUNT_MAP["capex"])
    capex = abs(capex_raw) if capex_raw else None

    fcf = (ocf - capex) if (ocf is not None and capex is not None) else None

    return {
        "report_period": bsns_year,
        "revenue": revenue,
        "gross_profit": gross,
        "operating_income": op_inc,
        "net_income": net_inc,
        "total_assets": total_assets,
        "shareholders_equity": equity,
        "cash_and_equivalents": cash,
        "net_cash_flow_from_operations": ocf,
        "capital_expenditure": -capex if capex else None,
        "free_cash_flow": fcf,
    }


# ── DART Raw API fetchers ──────────────────────────────────────────────────────

def _api_income_kr(symbol: str) -> list:
    corp_code = _get_corp_code(symbol)
    if not corp_code:
        logger.warning("corp_code not found for %s — OPENDART_API_KEY 확인 필요", symbol)
        return []
    results = []
    current_year = datetime.now().year
    seen_years = set()
    for year in [current_year - 1, current_year - 2]:
        # CFS(연결) 우선, 없으면 OFS(별도) fallback
        dart_list = []
        for fs_div in ("CFS", "OFS"):
            data = _dart_get("/fnlttSinglAcntAll.json", {
                "corp_code": corp_code,
                "bsns_year": str(year),
                "reprt_code": "11011",  # 사업보고서
                "fs_div": fs_div,
            })
            dart_list = data.get("list", [])
            if dart_list:
                logger.debug("DART income %s %s fs_div=%s OK (%d rows)", symbol, year, fs_div, len(dart_list))
                break
        if not dart_list:
            logger.debug("DART income %s %s: no data (both CFS/OFS empty)", symbol, year)
            continue
        # 당기(thstrm) + 전기(frmtrm) + 전전기(bfefrmtrm) 3년치 추출
        for bsns_year, amount_key in [
            (str(year), "thstrm_amount"),
            (str(year - 1), "frmtrm_amount"),
            (str(year - 2), "bfefrmtrm_amount"),
        ]:
            if bsns_year in seen_years:
                continue
            remapped = [{**row, "thstrm_amount": row.get(amount_key)} for row in dart_list]
            stmt = _build_year_statement(remapped, bsns_year)
            if stmt.get("revenue"):
                results.append(stmt)
                seen_years.add(bsns_year)
    results.sort(key=lambda x: x["report_period"], reverse=True)
    return results[:5]


def _api_balance_kr(symbol: str) -> list:
    # balance/cashflow는 income과 동일 DART 응답에서 추출 — fetch_all_kr에서 income 재사용
    return []


def _api_cashflow_kr(symbol: str) -> list:
    return []


def _api_metrics_kr(symbol: str) -> list:
    """yfinance로 PER/PBR/시가총액 조회. KOSPI는 .KS, KOSDAQ은 .KQ suffix."""
    import threading

    # KOSPI/KOSDAQ suffix 판별 — 실패하면 .KS 먼저 시도
    yf_symbols = [f"{symbol}.KS", f"{symbol}.KQ"]
    symbol_6 = symbol.zfill(6)

    _YF_EXCHANGE_MAP = {"KSC": "KOSPI", "KOE": "KOSDAQ"}

    def _fetch_yf(yf_sym: str, r: list):
        try:
            import yfinance as yf
            t = yf.Ticker(yf_sym)
            info = t.info
            if not info or info.get("quoteType") not in ("EQUITY", "ETF"):
                r.append(None)
                return
            # dividendYield: yfinance는 소수 형식(0.026 = 2.6%)으로 반환
            div_yield = info.get("dividendYield")
            yf_exch = info.get("exchange", "")
            r.append({
                "price_to_earnings_ratio": info.get("trailingPE") or info.get("forwardPE"),
                "price_to_book_ratio": info.get("priceToBook"),
                "earnings_per_share": info.get("trailingEps"),
                "market_cap": info.get("marketCap"),
                "dividend_yield": div_yield,
                "current_price": info.get("currentPrice") or info.get("regularMarketPrice"),
                "revenue_growth": info.get("revenueGrowth"),
                "earnings_growth": info.get("earningsGrowth"),
                "return_on_equity": info.get("returnOnEquity"),
                "return_on_assets": info.get("returnOnAssets"),
                "gross_margin": info.get("grossMargins"),
                "operating_margin": info.get("operatingMargins"),
                "exchange": _YF_EXCHANGE_MAP.get(yf_exch, yf_exch or "KRX"),
            })
        except Exception as e:
            logger.debug("yfinance %s: %s", yf_sym, e)
            r.append(None)

    for yf_sym in yf_symbols:
        result: list = []
        t = threading.Thread(target=_fetch_yf, args=(yf_sym, result), daemon=True)
        t.start()
        t.join(timeout=20)

        if t.is_alive():
            logger.warning("yfinance timeout for %s", yf_sym)
            continue

        if result and result[0] is not None:
            logger.info("yfinance metrics OK: %s", yf_sym)
            return [result[0]]

    logger.warning("yfinance metrics empty for %s (tried: %s)", symbol_6, yf_symbols)
    return []


def _api_dart_disclosures_kr(symbol: str) -> list:
    """DART 최근 60일 공시 목록 — 투자 맥락용 뉴스 피드 (모든 공시 유형)."""
    corp_code = _get_corp_code(symbol)
    if not corp_code:
        return []
    end_de = datetime.now().strftime("%Y%m%d")
    bgn_de = (datetime.now() - timedelta(days=60)).strftime("%Y%m%d")
    data = _dart_get("/list.json", {
        "corp_code": corp_code,
        "bgn_de": bgn_de,
        "end_de": end_de,
        "sort": "date",
        "sort_mth": "desc",
        "page_count": "20",
    })
    items = data.get("list", [])
    results = []
    for item in items:
        results.append({
            "date": item.get("rcept_dt", ""),
            "title": item.get("report_nm", ""),
            "source": "DART",
            "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={item.get('rcept_no', '')}",
            "rcept_no": item.get("rcept_no", ""),
        })
    return results


def _api_dart_annual_refs_kr(symbol: str) -> list:
    """DART 정기공시(사업보고서/반기보고서/분기보고서) 전용 조회 — DART 파이프라인용.
    pblntf_ty=A(정기공시)로 필터링, 400일 범위로 최근 연간/반기 보고서를 확실히 포함.
    """
    corp_code = _get_corp_code(symbol)
    if not corp_code:
        logger.warning("_api_dart_annual_refs_kr: corp_code not found for %s", symbol)
        return []
    end_de = datetime.now().strftime("%Y%m%d")
    bgn_de = (datetime.now() - timedelta(days=400)).strftime("%Y%m%d")
    data = _dart_get("/list.json", {
        "corp_code": corp_code,
        "bgn_de": bgn_de,
        "end_de": end_de,
        "pblntf_ty": "A",   # 정기공시만 (사업보고서, 반기보고서, 분기보고서)
        "sort": "date",
        "sort_mth": "desc",
        "page_count": "10",
    })
    items = data.get("list", [])
    if not items:
        logger.debug("_api_dart_annual_refs_kr: no 정기공시 found for %s (%s~%s)", symbol, bgn_de, end_de)
    results = []
    for item in items:
        report_nm = item.get("report_nm", "")
        if not any(kw in report_nm for kw in ["사업보고서", "반기보고서", "분기보고서"]):
            continue
        # filing_type 힌트 포함
        if "사업보고서" in report_nm:
            ft = "사업보고서"
        elif "반기보고서" in report_nm:
            ft = "반기보고서"
        else:
            ft = "분기보고서"
        rcept_no = item.get("rcept_no", "")
        rcept_dt = item.get("rcept_dt", "")
        results.append({
            "period": f"{rcept_dt[:4]}-{rcept_dt[4:6]}" if len(rcept_dt) >= 6 else rcept_dt,
            "filing_type": ft,
            "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}",
            "rcept_no": rcept_no,
        })
        logger.debug("Annual ref: %s %s rcept_no=%s", symbol, report_nm, rcept_no)
    return results


# 스케줄러 호환용 별칭 (light_refresh에서 _api_news_kr 이름으로 호출)
_api_news_kr = _api_dart_disclosures_kr


def _api_naver_news_kr(company_name: str) -> list:
    """네이버 뉴스 검색 API — KR 종목 최근 뉴스."""
    client_id = os.environ.get("NAVER_CLIENT_ID", "")
    client_secret = os.environ.get("NAVER_CLIENT_SECRET", "")
    if not client_id or not company_name:
        return []
    try:
        resp = requests.get(
            "https://openapi.naver.com/v1/search/news.json",
            headers={
                "X-Naver-Client-Id": client_id,
                "X-Naver-Client-Secret": client_secret,
            },
            params={"query": company_name, "display": 10, "sort": "date"},
            timeout=10,
        )
        if resp.status_code != 200:
            logger.warning("Naver news API %s → %s", company_name, resp.status_code)
            return []
        items = resp.json().get("items", [])
        results = []
        for item in items:
            # pubDate: "Mon, 21 Apr 2026 10:00:00 +0900"
            pub_date = item.get("pubDate", "")
            try:
                from email.utils import parsedate_to_datetime
                date_str = parsedate_to_datetime(pub_date).strftime("%Y-%m-%d")
            except Exception:
                date_str = pub_date[:10]
            import re as _re
            title = _re.sub(r"<[^>]+>", "", item.get("title", ""))
            results.append({
                "title": title,
                "date": date_str,
                "source": item.get("originallink", "").split("/")[2] if item.get("originallink") else "네이버뉴스",
                "url": item.get("originallink") or item.get("link", ""),
            })
        return results
    except Exception as e:
        logger.warning("Naver news failed for %s: %s", company_name, e)
        return []


def _api_insider_trades_kr(symbol: str) -> list:
    """DART 임원/주요주주 주식 변동 보고."""
    corp_code = _get_corp_code(symbol)
    if not corp_code:
        return []
    end_de = datetime.now().strftime("%Y%m%d")
    bgn_de = (datetime.now() - timedelta(days=180)).strftime("%Y%m%d")
    data = _dart_get("/majorstock.json", {
        "corp_code": corp_code,
        "bgn_de": bgn_de,
        "end_de": end_de,
    })
    items = data.get("list", [])
    results = []
    for item in items:
        reprt_nm = item.get("reprt_nm", "")
        change = _parse_amount(item.get("change_qy"))
        is_buy = change and change > 0
        results.append({
            "transaction_date": item.get("rcept_dt", ""),
            "name": item.get("repror_nm", ""),
            "title": item.get("isu_nm", ""),
            "transaction_type": "매수" if is_buy else "매도" if change and change < 0 else reprt_nm,
            "transaction_shares": abs(change) if change else None,
            "transaction_value": None,  # DART에서 금액 미제공
        })
    return results[:20]


def _api_facts_kr(symbol: str) -> dict:
    """DART 기업 기본 정보."""
    corp_code = _get_corp_code(symbol)
    if not corp_code:
        return {}
    data = _dart_get("/company.json", {"corp_code": corp_code})
    info = data  # company endpoint returns flat dict
    return {
        "sector": info.get("induty_code", "N/A"),
        "industry": info.get("induty_code", "N/A"),
        "exchange": info.get("stock_mkt", "KRX"),
        "location": info.get("adres", "N/A"),
        "description": info.get("est_dt", ""),
        "corp_name": info.get("corp_name", ""),
    }


# ── KR 포매터 ──────────────────────────────────────────────────────────────────

def _KRW(v) -> str:
    """원화 금액 → 조/억 단위 표시."""
    if v is None:
        return "N/A"
    if abs(v) >= 1e12:
        return f"₩{v/1e12:.2f}조"
    if abs(v) >= 1e8:
        return f"₩{v/1e8:.0f}억"
    if abs(v) >= 1e4:
        return f"₩{v/1e4:.0f}만"
    return f"₩{v:.0f}"


def _pct(v) -> str:
    if v is None:
        return "N/A"
    return f"{v*100:.1f}%"


def _yoy(curr, prev) -> str:
    if curr is None or prev is None or prev == 0:
        return "N/A"
    return f"{(curr - prev) / abs(prev) * 100:+.1f}%"


def _x(v, d: int = 1) -> str:
    if v is None or v == 0:
        return "N/A"
    return f"{v:.{d}f}x"


# ── 캐시 레이어 재사용 ─────────────────────────────────────────────────────────

def _cache_get_kr(db, ticker_id: str, data_type: str):
    from services.financial_data import _cache_get
    return _cache_get(db, ticker_id, data_type)


def _cache_set_kr(db, ticker_id: str, data_type: str, data):
    from services.financial_data import _cache_set
    _cache_set(db, ticker_id, data_type, data)


def _fetch_cached_kr(db, ticker_id: str, symbol: str, data_type: str, api_fn):
    cached = _cache_get_kr(db, ticker_id, data_type)
    if cached is not None:
        logger.debug("cache hit: %s/%s", symbol, data_type)
        return cached
    logger.info("cache miss, fetching KR: %s/%s", symbol, data_type)
    data = api_fn(symbol)
    if data:
        _cache_set_kr(db, ticker_id, data_type, data)
    return data


# ── 메인 집계 ──────────────────────────────────────────────────────────────────

def fetch_all_kr(symbol: str, ticker_id: str | None = None, db=None, company_name: str = "") -> dict:
    """
    한국 종목 전체 재무 데이터 수집.
    US fetch_all()과 동일한 반환 형식 → agent.py 변경 없음.
    balance/cashflow는 income과 동일 DART 응답에서 추출 — API 중복 호출 없음.
    """
    if db and ticker_id:
        income_stmts   = _fetch_cached_kr(db, ticker_id, symbol, "income",         _api_income_kr)
        metrics_list   = _fetch_cached_kr(db, ticker_id, symbol, "metrics",        _api_metrics_kr)
        dart_list      = _fetch_cached_kr(db, ticker_id, symbol, "news",           _api_dart_disclosures_kr)
        naver_news     = _fetch_cached_kr(db, ticker_id, symbol, "naver_news",     lambda s: _api_naver_news_kr(company_name or s))
        insider_trades = _fetch_cached_kr(db, ticker_id, symbol, "insider_trades", _api_insider_trades_kr)
        facts          = _fetch_cached_kr(db, ticker_id, symbol, "facts",          _api_facts_kr)
    else:
        income_stmts   = _api_income_kr(symbol)
        metrics_list   = _api_metrics_kr(symbol)
        dart_list      = _api_dart_disclosures_kr(symbol)
        naver_news     = _api_naver_news_kr(company_name or symbol)
        insider_trades = _api_insider_trades_kr(symbol)
        facts          = _api_facts_kr(symbol)

    # balance/cashflow는 income과 동일 DART fnlttSinglAcntAll 응답에서 추출
    balance_sheets = income_stmts
    cash_flows = income_stmts

    metrics = (metrics_list[0] if isinstance(metrics_list, list) and metrics_list else {})
    if not isinstance(facts, dict):
        facts = {}
    # yfinance에서 확인된 exchange 정보로 DART의 stock_mkt(None) 보완
    if metrics.get("exchange") and metrics["exchange"] != "KRX":
        facts["exchange"] = metrics["exchange"]

    # ── Income Table ──────────────────────────────────────────────────────────
    income_rows = []
    for i, stmt in enumerate(income_stmts):
        period = stmt.get("report_period", "")[:4]
        prev = income_stmts[i + 1] if i + 1 < len(income_stmts) else None
        rev = stmt.get("revenue")
        gross = stmt.get("gross_profit")
        income_rows.append(
            f"  {period} | 매출 {_KRW(rev)} ({_yoy(rev, prev.get('revenue') if prev else None)})"
            f" | 매출총이익 {_KRW(gross)}"
            f" ({_pct(gross / rev if gross and rev else None)} margin)"
            f" | 영업이익 {_KRW(stmt.get('operating_income'))}"
            f" | 순이익 {_KRW(stmt.get('net_income'))}"
        )

    # ── Cash Flow Table ───────────────────────────────────────────────────────
    cf_rows = []
    for idx, stmt in enumerate(income_stmts):  # 동일 stmt에서 추출
        period = stmt.get("report_period", "")[:4]
        ocf = stmt.get("net_cash_flow_from_operations")
        capex = stmt.get("capital_expenditure")
        fcf = stmt.get("free_cash_flow")
        rev = stmt.get("revenue")
        cf_rows.append(
            f"  {period} | 영업CF {_KRW(ocf)}"
            f" | Capex {_KRW(abs(capex) if capex else None)}"
            f" | FCF {_KRW(fcf)} ({_pct(fcf / rev if fcf and rev else None)} of rev)"
        )

    # ── Balance Sheet Table ───────────────────────────────────────────────────
    bs_rows = []
    for stmt in income_stmts:
        period = stmt.get("report_period", "")[:4]
        assets = stmt.get("total_assets")
        cash = stmt.get("cash_and_equivalents")
        equity = stmt.get("shareholders_equity")
        bs_rows.append(
            f"  {period} | 자산총계 {_KRW(assets)}"
            f" | 현금 {_KRW(cash)}"
            f" | 자본총계 {_KRW(equity)}"
        )

    # ── Key Metrics ───────────────────────────────────────────────────────────
    km = metrics
    key_metrics_text = f"""
  밸류에이션 : 시가총액 {_KRW(km.get('market_cap'))}
               PER {_x(km.get('price_to_earnings_ratio'))} | PBR {_x(km.get('price_to_book_ratio'))}
               배당수익률 {_pct(km.get('dividend_yield'))}
  Per Share  : EPS ₩{km.get('earnings_per_share', 'N/A')} | BPS ₩{km.get('book_value_per_share', 'N/A')}
"""

    # ── News (네이버 뉴스) ────────────────────────────────────────────────────
    naver_list = naver_news if isinstance(naver_news, list) else []
    news_text = "\n".join(
        f"  [{n.get('date', '')}] {n.get('title', '')} ({n.get('source', '')})"
        for n in naver_list[:10]
    ) or "  최근 뉴스 없음 (NAVER_CLIENT_ID 설정 필요)"

    # ── DART 공시 목록 ────────────────────────────────────────────────────────
    news_list = dart_list if isinstance(dart_list, list) else []

    # ── Insider Trades ────────────────────────────────────────────────────────
    trades_list = insider_trades if isinstance(insider_trades, list) else []
    insider_rows = []
    buy_count = sell_count = 0
    for t in trades_list[:20]:
        tx_type = t.get("transaction_type", "")
        shares = t.get("transaction_shares")
        name = t.get("name", "Unknown")
        title = t.get("title", "")
        date = (t.get("transaction_date") or "")[:8]
        if "매수" in tx_type:
            buy_count += 1
        elif "매도" in tx_type:
            sell_count += 1
        shares_fmt = f"{int(shares):,}" if shares else "N/A"
        insider_rows.append(
            f"  {date} | {tx_type[:20]:<20} | {name} ({title[:20]}) | {shares_fmt}주"
        )
    insider_summary = f"  매수 {buy_count}건 / 매도 {sell_count}건 / 총 {len(trades_list)}건"
    insider_text = insider_summary + "\n" + ("\n".join(insider_rows) or "  데이터 없음")

    # ── Company Facts ─────────────────────────────────────────────────────────
    company_text = (
        f"  업종: {facts.get('industry', 'N/A')}"
        f" | 거래소: {facts.get('exchange', 'KRX')}"
        f" | 소재지: {facts.get('location', 'N/A')}"
    )

    # DART 정기공시 refs — 뉴스 캐시와 분리해서 전용 조회 (400일 범위, pblntf_ty=A)
    filing_refs = _api_dart_annual_refs_kr(symbol)
    logger.info("DART annual refs for %s: %d filings", symbol, len(filing_refs))

    return {
        "income_table":      "\n".join(income_rows) or "  데이터 없음",
        "cf_table":          "\n".join(cf_rows) or "  데이터 없음",
        "bs_table":          "\n".join(bs_rows) or "  데이터 없음",
        "key_metrics":       key_metrics_text,
        "news":              news_text,
        "insider_trades":    insider_text,
        "company_info":      company_text,
        "filing_refs":       filing_refs,
        "has_data":          bool(income_stmts or metrics_list),
        "_metrics":          km,
        "_income":           income_stmts,
        "_cf":               income_stmts,
    }
