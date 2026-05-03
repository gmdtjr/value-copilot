"""
시장 지표 수집 — VIX, Fear & Greed, S&P500
외부 무료 API 사용 (키 불필요)
"""
import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)


def get_yahoo_quote(symbol: str) -> Optional[dict]:
    try:
        resp = requests.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
            params={"range": "2d", "interval": "1d"},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        result = resp.json()["chart"]["result"][0]
        meta = result["meta"]
        price = meta.get("regularMarketPrice", 0)
        prev_close = meta.get("regularMarketPreviousClose") or meta.get("chartPreviousClose") or 0
        if meta.get("regularMarketChangePercent") is not None:
            change_pct = round(meta["regularMarketChangePercent"], 2)
        elif prev_close:
            change_pct = round((price - prev_close) / prev_close * 100, 2)
        else:
            change_pct = 0.0
        return {
            "price": round(price, 2),
            "prev_close": round(prev_close, 2),
            "change_pct": change_pct,
        }
    except Exception as e:
        logger.warning("Yahoo quote 조회 실패 %s: %s", symbol, e)
        return None


def get_fear_greed() -> Optional[dict]:
    try:
        resp = requests.get(
            "https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9",
                "Origin": "https://www.cnn.com",
                "Referer": "https://www.cnn.com/markets/fear-and-greed",
            },
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        fg = data.get("fear_and_greed", {})
        score = round(float(fg.get("score", 0)), 1)
        rating = fg.get("rating", "")
        return {"score": score, "rating": rating}
    except Exception as e:
        logger.warning("Fear & Greed 조회 실패: %s", e)
        return None


def get_market_indicators() -> dict:
    """VIX, Fear&Greed, S&P500, KOSPI 지표 수집."""
    vix = get_yahoo_quote("%5EVIX")
    sp500 = get_yahoo_quote("%5EGSPC")
    kospi = get_yahoo_quote("%5EKS11")
    fg = get_fear_greed()

    return {
        "vix": vix,
        "sp500": sp500,
        "kospi": kospi,
        "fear_greed": fg,
    }
