"""
한국투자증권 Open API 클라이언트
ref: value-investing-copilot/modules/kis_client.py
"""
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

KIS_BASE_URL = "https://openapi.koreainvestment.com:9443"

KIS_ACCOUNTS_CFG = [
    {"name": "ISA계좌",  "env_prefix": "DOMESTIC", "type": "domestic"},
    {"name": "연금계좌", "env_prefix": "PENSION",  "type": "domestic"},
    {"name": "IRP계좌",  "env_prefix": "IRP",      "type": "domestic"},
    {"name": "일반계좌", "env_prefix": "OVERSEAS",  "type": "overseas"},
    {"name": "이레계좌", "env_prefix": "IRE",       "type": "overseas"},
    # type 필드는 참고용 — 실제 조회는 모든 계좌에서 국내+해외 모두 실행
]


@dataclass
class Account:
    name: str
    acc_no: str
    api_key: str
    api_secret: str
    account_type: str  # "domestic" | "overseas"
    cano: str = field(init=False)
    acnt_prdt_cd: str = field(init=False)

    def __post_init__(self):
        if "-" in self.acc_no:
            parts = self.acc_no.split("-")
            self.cano, self.acnt_prdt_cd = parts[0], parts[1]
        else:
            self.cano, self.acnt_prdt_cd = self.acc_no, "01"


def load_accounts() -> List[Account]:
    accounts = []
    for cfg in KIS_ACCOUNTS_CFG:
        prefix = cfg["env_prefix"]
        acc_no    = os.getenv(f"KOREA_INVESTMENT_ACC_NO_{prefix}", "")
        api_key   = os.getenv(f"KOREA_INVESTMENT_API_KEY_{prefix}", "")
        api_secret = os.getenv(f"KOREA_INVESTMENT_API_SECRET_{prefix}", "")
        if not all([acc_no, api_key, api_secret]):
            logger.warning("%s 환경변수 누락 — 스킵", cfg["name"])
            continue
        accounts.append(Account(
            name=cfg["name"], acc_no=acc_no,
            api_key=api_key, api_secret=api_secret,
            account_type=cfg["type"],
        ))
    return accounts


def get_exchange_rate() -> float:
    try:
        resp = requests.get("https://api.exchangerate-api.com/v4/latest/USD", timeout=10)
        if resp.status_code == 200:
            return float(resp.json()["rates"]["KRW"])
    except Exception:
        pass
    logger.warning("환율 조회 실패 — 기본값 1300원 사용")
    return 1300.0


class KISClient:

    def __init__(self):
        self.base_url = KIS_BASE_URL
        self._tokens: Dict[str, str] = {}
        self._token_expiry: Dict[str, datetime] = {}

    def get_access_token(self, account: Account) -> str:
        cache_key = account.api_key
        if (cache_key in self._tokens
                and datetime.now() < self._token_expiry.get(cache_key, datetime.min)):
            return self._tokens[cache_key]

        for attempt in range(3):
            try:
                resp = requests.post(
                    f"{self.base_url}/oauth2/tokenP",
                    headers={"content-type": "application/json"},
                    data=json.dumps({
                        "grant_type": "client_credentials",
                        "appkey": account.api_key,
                        "appsecret": account.api_secret,
                    }),
                )
                if resp.status_code == 200:
                    token = resp.json()["access_token"]
                    self._tokens[cache_key] = token
                    self._token_expiry[cache_key] = datetime.now() + timedelta(hours=23)
                    logger.info("%s 토큰 발급 완료", account.name)
                    return token
                logger.warning("%s 토큰 발급 실패: %s", account.name, resp.text)
            except Exception as e:
                logger.error("%s 토큰 오류: %s", account.name, e)
            if attempt < 2:
                time.sleep((attempt + 1) * 30)

        raise RuntimeError(f"{account.name} 토큰 발급 실패 (3회)")

    def get_domestic_portfolio(self, account: Account) -> List[Dict]:
        """국내 잔고 조회. CTX_AREA_NK100 페이지네이션 처리."""
        try:
            token = self.get_access_token(account)
            result = []
            ctx_fk = ""
            ctx_nk = ""
            while True:
                resp = requests.get(
                    f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-balance",
                    headers={
                        "Content-Type": "application/json",
                        "authorization": f"Bearer {token}",
                        "appKey": account.api_key,
                        "appSecret": account.api_secret,
                        "tr_id": "TTTC8434R",
                        "custtype": "P",
                    },
                    params={
                        "CANO": account.cano, "ACNT_PRDT_CD": account.acnt_prdt_cd,
                        "AFHR_FLPR_YN": "N", "OFL_YN": "", "INQR_DVSN": "02",
                        "UNPR_DVSN": "01", "FUND_STTL_ICLD_YN": "N",
                        "FNCG_AMT_AUTO_RDPT_YN": "N", "PRCS_DVSN": "01",
                        "CTX_AREA_FK100": ctx_fk, "CTX_AREA_NK100": ctx_nk,
                    },
                )
                if resp.status_code != 200:
                    break
                data = resp.json()
                if data.get("rt_cd") != "0":
                    logger.error("%s 국내 잔고 실패: %s", account.name, data.get("msg1", ""))
                    break

                for item in data.get("output1", []):
                    qty = int(float(item.get("hldg_qty", "0")))
                    if qty <= 0:
                        continue
                    result.append({
                        "symbol": item.get("pdno", ""),
                        "name": item.get("prdt_name", ""),
                        "quantity": qty,
                        "avg_price": round(float(item.get("pchs_avg_pric", "0"))),
                        "current_price": int(float(item.get("prpr", "0"))),
                        "daily_pct": 0.0,
                        "kis_pnl_pct": round(float(item.get("evlu_pfls_rt", "0")), 2),
                        "currency": "KRW",
                        "account": account.name,
                    })

                # 다음 페이지 토큰 확인
                ctx_nk = (data.get("ctx_area_nk100") or "").strip()
                ctx_fk = (data.get("ctx_area_fk100") or "").strip()
                if not ctx_nk:
                    break  # 마지막 페이지

            logger.info("%s 국내 %d종목", account.name, len(result))
            return result
        except Exception as e:
            logger.error("%s 국내 잔고 오류: %s", account.name, e)
            return []

    def get_overseas_portfolio(self, account: Account, exchange_rate: float = 1300.0) -> List[Dict]:
        """해외 잔고 조회. NASD/NYSE/AMEX 거래소 순회 + CTX_AREA_NK200 페이지네이션 처리."""
        # KIS는 거래소별 조회 — 주요 미국 거래소 순회
        EXCHANGES = ["NASD", "NYSE", "AMEX"]
        seen_symbols: set[str] = set()
        all_result: List[Dict] = []

        try:
            token = self.get_access_token(account)
        except Exception as e:
            logger.error("%s 토큰 오류: %s", account.name, e)
            return []

        for excg in EXCHANGES:
            try:
                ctx_fk = ""
                ctx_nk = ""
                while True:
                    resp = requests.get(
                        f"{self.base_url}/uapi/overseas-stock/v1/trading/inquire-balance",
                        headers={
                            "Content-Type": "application/json",
                            "authorization": f"Bearer {token}",
                            "appKey": account.api_key,
                            "appSecret": account.api_secret,
                            "tr_id": "TTTS3012R",
                        },
                        params={
                            "CANO": account.cano, "ACNT_PRDT_CD": account.acnt_prdt_cd,
                            "OVRS_EXCG_CD": excg, "TR_CRCY_CD": "USD",
                            "CTX_AREA_FK200": ctx_fk, "CTX_AREA_NK200": ctx_nk,
                        },
                    )
                    if resp.status_code != 200:
                        break
                    data = resp.json()
                    if data.get("rt_cd") != "0":
                        # 잔고 없는 거래소는 오류 아님 — 조용히 스킵
                        break

                    for item in data.get("output1", []):
                        qty = int(float(item.get("ovrs_cblc_qty", "0")))
                        sym = item.get("ovrs_pdno", "")
                        if qty <= 0 or not sym:
                            continue
                        if sym in seen_symbols:
                            continue  # 같은 계좌 내 거래소 중복 방지
                        seen_symbols.add(sym)
                        all_result.append({
                            "symbol": sym,
                            "name": item.get("ovrs_item_name", ""),
                            "quantity": qty,
                            "avg_price": round(float(item.get("pchs_avg_pric", "0")), 2),
                            "current_price": round(float(item.get("now_pric2", "0")), 2),
                            "daily_pct": 0.0,
                            "kis_pnl_pct": round(float(item.get("evlu_pfls_rt", "0")), 2),
                            "currency": "USD",
                            "account": account.name,
                        })

                    ctx_nk = (data.get("ctx_area_nk200") or "").strip()
                    ctx_fk = (data.get("ctx_area_fk200") or "").strip()
                    if not ctx_nk:
                        break  # 마지막 페이지

            except Exception as e:
                logger.error("%s %s 해외 잔고 오류: %s", account.name, excg, e)

        logger.info("%s 해외 %d종목 (NASD+NYSE+AMEX)", account.name, len(all_result))
        return all_result
