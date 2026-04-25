import logging
import os
import re
from datetime import datetime, timedelta
from typing import Optional

import requests

from models.db import FinancialCache

logger = logging.getLogger(__name__)

BASE_API = "https://api.valley.town"
BASE_WWW = "https://www.valley.town"
VALLEY_CACHE_TYPE = "valley_url"
VALLEY_CACHE_TTL = timedelta(days=30)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/145.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "Referer": "https://www.valley.town/",
}

US_SUFFIX_TO_EXCHANGE = {
    "OQ": "NASD",
    "N": "NYSE",
    "P": "NYSE",
    "A": "AMEX",
}

KR_ETF_KEYWORDS = (
    "ETF", "ETN", "KODEX", "TIGER", "KOSEF", "KINDEX", "KBSTAR",
    "ARIRANG", "ACE", "SOL", "HANARO", "TIMEFOLIO", "PLUS",
)


class ValleyClient:
    def __init__(self, email: str, password: str):
        self.email = email
        self.password = password
        self._session: Optional[requests.Session] = None

    def _get_session(self) -> requests.Session:
        if self._session is None:
            self._session = requests.Session()
            self._session.headers.update(HEADERS)
            self._login()
        return self._session

    def _login(self) -> None:
        resp = self._session.post(
            f"{BASE_API}/auth/sign-in",
            json={"email": self.email, "password": self.password, "type": "session"},
            timeout=15,
        )
        resp.raise_for_status()

    def search_stock(self, ticker: str) -> Optional[dict]:
        s = self._get_session()
        resp = s.get(
            f"{BASE_WWW}/api/analysis/quote/stocks",
            params={
                "text": ticker,
                "type": "TOTAL",
                "maxCnt": 10,
                "exceptEtfs": "false",
                "exceptAdrs": "false",
                "exceptNonStocks": "false",
                "withFinancialValues": "false",
            },
            timeout=10,
        )
        resp.raise_for_status()
        stocks = resp.json().get("data", [])
        if not isinstance(stocks, list):
            return None

        for stock in stocks:
            if stock.get("ticker", "").upper() == ticker.upper() and stock.get("isExactMatch"):
                return stock
        for stock in stocks:
            if stock.get("ticker", "").upper() == ticker.upper():
                return stock
        return None

    def validate_url(self, url: str, symbol: str, name: str = "") -> bool:
        s = self._get_session()
        resp = s.get(url, allow_redirects=True, timeout=10)
        if resp.status_code != 200:
            return False
        final_url = str(resp.url)
        if "/login" in final_url:
            return False
        # Valley summary 페이지는 클라이언트 렌더링이며 정상 HTML 안에도 "404" 같은 문자열이
        # 포함될 수 있다. 여기서는 상태코드/리다이렉트만으로 유효성을 판단한다.
        return True


def _get_cached_url(db, ticker_id: str) -> Optional[str]:
    row = (
        db.query(FinancialCache)
        .filter(
            FinancialCache.ticker_id == ticker_id,
            FinancialCache.data_type == VALLEY_CACHE_TYPE,
        )
        .first()
    )
    if row and row.expires_at > datetime.utcnow():
        data = row.data or {}
        if isinstance(data, dict):
            return data.get("url")
    return None


def get_cached_valley_url(db, ticker_id: str) -> Optional[str]:
    return _get_cached_url(db, ticker_id)


def _set_cached_url(db, ticker_id: str, url: str) -> None:
    row = (
        db.query(FinancialCache)
        .filter(
            FinancialCache.ticker_id == ticker_id,
            FinancialCache.data_type == VALLEY_CACHE_TYPE,
        )
        .first()
    )
    expires = datetime.utcnow() + VALLEY_CACHE_TTL
    payload = {"url": url}
    if row:
        row.data = payload
        row.fetched_at = datetime.utcnow()
        row.expires_at = expires
    else:
        db.add(FinancialCache(
            ticker_id=ticker_id,
            data_type=VALLEY_CACHE_TYPE,
            data=payload,
            fetched_at=datetime.utcnow(),
            expires_at=expires,
        ))
    db.commit()


def _is_kr_etf_like(symbol: str, name: str) -> bool:
    title = f"{symbol} {name}".upper()
    return any(token in title for token in KR_ETF_KEYWORDS)


def _candidate_urls(symbol: str, name: str, market: str, stock: Optional[dict]) -> list[str]:
    urls: list[str] = []
    if market == "KR_Stock":
        kr_symbol = symbol.zfill(6)
        preferred = ["kospi", "KRX"] if _is_kr_etf_like(symbol, name) else ["KRX", "kospi", "kosdaq"]
        for exchange in preferred:
            urls.append(f"{BASE_WWW}/financials/quote/{kr_symbol}:{exchange}/summary")
        return urls

    stock_id = str((stock or {}).get("stockId", "") or "")
    if "." in stock_id:
        suffix = stock_id.split(".")[-1].upper()
        exchange = US_SUFFIX_TO_EXCHANGE.get(suffix)
        if exchange:
            urls.append(f"{BASE_WWW}/financials/quote/{symbol}:{exchange}/summary")

    for exchange in ("NASD", "NYSE", "XNYS", "AMEX"):
        candidate = f"{BASE_WWW}/financials/quote/{symbol}:{exchange}/summary"
        if candidate not in urls:
            urls.append(candidate)
    return urls


def resolve_valley_url(db, ticker_id: str, symbol: str, name: str, market: str) -> Optional[str]:
    url, _ = resolve_valley_url_with_reason(db, ticker_id, symbol, name, market)
    return url


def resolve_valley_url_with_reason(db, ticker_id: str, symbol: str, name: str, market: str) -> tuple[Optional[str], Optional[str]]:
    cached = _get_cached_url(db, ticker_id)
    if cached:
        return cached, None

    email = os.getenv("VALLEY_EMAIL", "")
    password = os.getenv("VALLEY_PASSWORD", "")
    if not email or not password:
        return None, "Valley 로그인 정보 없음"

    try:
        client = ValleyClient(email, password)
        stock = client.search_stock(symbol)
        if not stock:
            return None, "Valley 검색 결과 없음"

        attempts: list[str] = []
        for url in _candidate_urls(symbol, name, market, stock):
            try:
                if client.validate_url(url, symbol, name):
                    _set_cached_url(db, ticker_id, url)
                    return url, None
                attempts.append(url.rsplit("/", 2)[-2])
            except Exception as e:
                attempts.append(f"{url.rsplit('/', 2)[-2]}:{type(e).__name__}")
                logger.debug("Valley URL validation failed [%s]: %s", url, e)
        tried = ", ".join(attempts[:4]) if attempts else "후보 없음"
        return None, f"후보 검증 실패 ({tried})"
    except Exception as e:
        logger.warning("Valley URL resolve failed for %s: %s", symbol, e)
        return None, f"Valley API 오류: {type(e).__name__}"

    return None, "알 수 없는 오류"
