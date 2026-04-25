import copy
import json
import logging
import threading
import time
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from models.db import (
    get_db, Ticker, Thesis, Report, MarketEnum, TickerStatusEnum, ThesisStatusEnum, ReportTypeEnum,
)
from services.agent import generate_thesis_stream, refine_thesis_stream, generate_ticker_report, run_break_monitor
from services.telegram import notify_report_generated, notify_break_monitor, notify_thesis_needs_review
from services.valley import get_cached_valley_url, resolve_valley_url, resolve_valley_url_with_reason

logger = logging.getLogger(__name__)
router = APIRouter()

# ── 진행 상태 추적기 (in-memory, 단일 Job) ─────────────────────────────────────
_job_lock = threading.Lock()
_current_job: dict | None = None  # {action, items: [{ticker_id, symbol, name, status, msg}], started_at, finished_at}


def _job_try_init(action: str, items: list[dict]) -> tuple[bool, dict | None, bool]:
    """
    Start a bulk job unless another one is still active.

    Returns (started, existing_job, is_same_request). Repeated clicks or browser
    retries should restore the in-flight job instead of scheduling duplicates.
    """
    global _current_job
    with _job_lock:
        if _current_job is not None and _current_job.get("finished_at") is None:
            in_progress = any(
                item.get("status") in {"waiting", "running"}
                for item in _current_job.get("items", [])
            )
            if in_progress:
                existing = copy.deepcopy(_current_job)
                existing_ids = [item.get("ticker_id") for item in existing.get("items", [])]
                new_ids = [item.get("ticker_id") for item in items]
                same_request = existing.get("action") == action and existing_ids == new_ids
                return False, existing, same_request

        _current_job = {
            "action": action,
            "items": [dict(item) for item in items],
            "started_at": datetime.utcnow().isoformat(),
            "finished_at": None,
        }
        return True, copy.deepcopy(_current_job), False


def _job_update(ticker_id: str, status: str, msg: str | None = None):
    with _job_lock:
        if _current_job is None:
            return
        for item in _current_job["items"]:
            if item["ticker_id"] == ticker_id:
                item["status"] = status
                item["msg"] = msg
                break


def _job_finish():
    with _job_lock:
        if _current_job is not None:
            _current_job["finished_at"] = datetime.utcnow().isoformat()


def _format_financial_context(fin: dict) -> str:
    """fetch_all() 결과를 thesis 프롬프트용 문자열로 변환."""
    return (
        f"## 실제 재무 데이터 (반드시 인용하여 분석하세요)\n\n"
        f"### 기업 정보\n{fin['company_info']}\n\n"
        f"### Income Statement (연간, 최근 5년)\n{fin['income_table']}\n\n"
        f"### Cash Flow Statement\n{fin['cf_table']}\n\n"
        f"### Balance Sheet\n{fin['bs_table']}\n\n"
        f"### Key Metrics (TTM)\n{fin['key_metrics']}\n\n"
        f"### 최근 뉴스 (최근 10건)\n{fin['news']}"
    )


# ── Schemas ───────────────────────────────────────────────────────────────────

class TickerCreate(BaseModel):
    symbol: str
    name: str
    market: MarketEnum
    status: TickerStatusEnum = TickerStatusEnum.WATCHLIST


class TickerPatch(BaseModel):
    daily_alert: Optional[bool] = None


class AnalyzeBody(BaseModel):
    stock_type: str
    seed_memo: str


class RefineBody(BaseModel):
    feedback: str


class BulkRefreshBody(BaseModel):
    ticker_ids: list[str]


class BulkAnalyzeBody(BaseModel):
    ticker_ids: list[str] = []  # 비어 있으면 thesis 없는 전체 종목


class TickerResponse(BaseModel):
    id: str
    symbol: str
    name: str
    market: str
    status: str
    daily_alert: bool
    thesis_status: Optional[str] = None
    has_content: bool = False
    created_at: str
    # Portfolio fields (None for watchlist tickers)
    portfolio_quantity: Optional[float] = None
    portfolio_avg_price: Optional[float] = None
    portfolio_current_price: Optional[float] = None
    portfolio_daily_pct: Optional[float] = None
    portfolio_pnl_pct: Optional[float] = None
    valley_url: Optional[str] = None

    class Config:
        from_attributes = True


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("", response_model=list[TickerResponse])
def list_tickers(db: Session = Depends(get_db)):
    tickers = db.query(Ticker).order_by(Ticker.created_at.desc()).all()
    result = []
    for t in tickers:
        p = t.portfolio
        pnl_pct = None
        daily_pct = p.daily_pct if p else None
        if p and p.avg_price and p.current_price:
            pnl_pct = (p.current_price - p.avg_price) / p.avg_price * 100
            # 과거 KIS 동기화가 평가손익률(evlu_pfls_rt)을 daily_pct에 저장한 적이 있음.
            # 그 값이 총 수익률과 사실상 같으면 일일 등락률로 내려보내지 않는다.
            if daily_pct is not None and abs(daily_pct - pnl_pct) < 0.05 and abs(daily_pct) > 50:
                daily_pct = None
        result.append(TickerResponse(
            id=str(t.id),
            symbol=t.symbol,
            name=t.name,
            market=t.market.value,
            status=t.status.value,
            daily_alert=t.daily_alert,
            thesis_status=t.thesis.confirmed.value if t.thesis else None,
            has_content=bool(t.thesis and t.thesis.thesis),
            created_at=t.created_at.isoformat(),
            portfolio_quantity=p.quantity if p else None,
            portfolio_avg_price=p.avg_price if p else None,
            portfolio_current_price=p.current_price if p else None,
            portfolio_daily_pct=daily_pct,
            portfolio_pnl_pct=pnl_pct,
            valley_url=get_cached_valley_url(db, str(t.id)),
        ))
    return result


@router.post("", response_model=TickerResponse, status_code=201)
def add_ticker(body: TickerCreate, db: Session = Depends(get_db)):
    existing = db.query(Ticker).filter(Ticker.symbol == body.symbol.upper()).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"{body.symbol.upper()} 이미 존재합니다.")

    ticker = Ticker(
        symbol=body.symbol.upper(),
        name=body.name,
        market=body.market,
        status=body.status,
    )
    db.add(ticker)
    db.flush()

    thesis = Thesis(ticker_id=ticker.id, confirmed=ThesisStatusEnum.DRAFT)
    db.add(thesis)
    db.commit()
    db.refresh(ticker)

    logger.info("Ticker added: %s (%s)", ticker.symbol, ticker.market.value)
    return TickerResponse(
        id=str(ticker.id),
        symbol=ticker.symbol,
        name=ticker.name,
        market=ticker.market.value,
        status=ticker.status.value,
        daily_alert=ticker.daily_alert,
        thesis_status=ThesisStatusEnum.DRAFT.value,
        created_at=ticker.created_at.isoformat(),
    )


@router.patch("/{ticker_id}", response_model=TickerResponse)
def patch_ticker(ticker_id: str, body: TickerPatch, db: Session = Depends(get_db)):
    ticker = db.query(Ticker).filter(Ticker.id == ticker_id).first()
    if not ticker:
        raise HTTPException(status_code=404, detail="Ticker not found")
    if body.daily_alert is not None:
        ticker.daily_alert = body.daily_alert
    db.commit()
    db.refresh(ticker)
    return TickerResponse(
        id=str(ticker.id), symbol=ticker.symbol, name=ticker.name,
        market=ticker.market.value, status=ticker.status.value,
        daily_alert=ticker.daily_alert,
        thesis_status=ticker.thesis.confirmed.value if ticker.thesis else None,
        created_at=ticker.created_at.isoformat(),
    )


@router.post("/{ticker_id}/break-monitor", status_code=202)
def trigger_break_monitor(ticker_id: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """수동 Break Monitor 트리거."""
    ticker = db.query(Ticker).filter(Ticker.id == ticker_id).first()
    if not ticker:
        raise HTTPException(status_code=404, detail="Ticker not found")
    thesis = db.query(Thesis).filter(Thesis.ticker_id == ticker.id).first()
    if not thesis or thesis.confirmed != ThesisStatusEnum.CONFIRMED:
        raise HTTPException(status_code=400, detail="confirmed 상태의 thesis가 없습니다.")
    background_tasks.add_task(
        _run_break_monitor_task,
        str(ticker.id), ticker.symbol, ticker.name,
        thesis.thesis or "", thesis.key_assumptions or "",
    )
    return {"message": f"{ticker.symbol} Break Monitor 시작됨"}


def _run_break_monitor_task(ticker_id: str, symbol: str, name: str, thesis: str, key_assumptions: str):
    from models.db import SessionLocal
    from services.scheduler import _get_cache, _fmt_news_full, _fmt_metrics
    db = SessionLocal()
    try:
        news_data = _get_cache(db, ticker_id, "news")
        metrics_data = _get_cache(db, ticker_id, "metrics")
        result = run_break_monitor(
            symbol=symbol, name=name, ticker_id=ticker_id,
            thesis=thesis, key_assumptions=key_assumptions,
            news_context=_fmt_news_full(news_data, limit=7),
            metrics_context=_fmt_metrics(metrics_data),
        )
        notify_break_monitor(symbol, name, result["signal"], result.get("assessment", ""), ticker_id=ticker_id)
        logger.info("Break Monitor %s → %s", symbol, result["signal"])
    except Exception:
        logger.exception("Break Monitor 실패: %s", symbol)
    finally:
        db.close()


@router.post("/{ticker_id}/analyze")
def analyze_ticker(ticker_id: str, body: AnalyzeBody, db: Session = Depends(get_db)):
    """SSE 스트림으로 Thesis AI 초안 생성. 완료 시 DB 저장."""
    from services.financial_data import fetch_all

    ticker = db.query(Ticker).filter(Ticker.id == ticker_id).first()
    if not ticker:
        raise HTTPException(status_code=404, detail="Ticker not found")

    # 재무 데이터 pre-fetch (캐시 우선, 없으면 빈 context로 fallback)
    try:
        fin = fetch_all(ticker.symbol, ticker_id=str(ticker.id), db=db, market=ticker.market.value, company_name=ticker.name)
        financial_context = _format_financial_context(fin) if fin.get("has_data") else ""
    except Exception:
        logger.warning("Financial data fetch failed for %s — proceeding without", ticker.symbol)
        financial_context = ""

    # 공시 요약 추가 (SEC 10-K/10-Q 또는 DART 사업보고서)
    try:
        from services.sec_pipeline import get_sec_context
        sec_context = get_sec_context(str(ticker.id), db, limit=2)
        if sec_context:
            label = "DART 공시 요약 (사업보고서/반기보고서)" if ticker.market.value == "KR_Stock" else "SEC 공시 요약 (10-K/10-Q)"
            financial_context += f"\n\n### {label}\n{sec_context}"
    except Exception:
        logger.warning("SEC/DART context load failed for %s", ticker.symbol)

    def event_stream():
        sections = {}
        try:
            for sse_str in generate_thesis_stream(
                symbol=ticker.symbol,
                name=ticker.name,
                market=ticker.market.value,
                ticker_id=str(ticker.id),
                financial_context=financial_context,
                stock_type=body.stock_type,
                seed_memo=body.seed_memo,
            ):
                # Extract sections from complete event
                if sse_str.startswith("data:"):
                    try:
                        payload = json.loads(sse_str[5:].strip())
                        if payload.get("type") == "complete":
                            sections = payload.get("sections", {})
                    except Exception:
                        pass
                yield sse_str
        except Exception as e:
            logger.exception("Thesis generation failed for %s", ticker.symbol)
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
            return

        # Save sections to DB after stream completes
        if sections:
            fresh_db = db
            thesis = fresh_db.query(Thesis).filter(Thesis.ticker_id == ticker.id).first()
            if thesis:
                thesis.thesis = sections.get("thesis")
                thesis.risk = sections.get("risk")
                thesis.key_assumptions = sections.get("key_assumptions")
                thesis.valuation = sections.get("valuation")
                thesis.stock_type = body.stock_type
                thesis.seed_memo = body.seed_memo
                was_confirmed = thesis.confirmed == ThesisStatusEnum.CONFIRMED
                thesis.confirmed = (
                    ThesisStatusEnum.NEEDS_REVIEW if was_confirmed else ThesisStatusEnum.DRAFT
                )
                thesis.last_analyzed_at = datetime.utcnow()
                fresh_db.commit()
                logger.info("Thesis saved for %s", ticker.symbol)
                if was_confirmed:
                    notify_thesis_needs_review(ticker.symbol, ticker.name, ticker.market.value, ticker_id=str(ticker.id))

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{ticker_id}/refine")
def refine_ticker(ticker_id: str, body: RefineBody, db: Session = Depends(get_db)):
    """SSE 스트림으로 피드백 기반 Thesis 재생성. 완료 시 DB 저장."""
    ticker = db.query(Ticker).filter(Ticker.id == ticker_id).first()
    if not ticker:
        raise HTTPException(status_code=404, detail="Ticker not found")
    thesis = db.query(Thesis).filter(Thesis.ticker_id == ticker.id).first()
    if not thesis or not thesis.thesis:
        raise HTTPException(status_code=400, detail="먼저 AI 분석을 실행하세요.")
    if not body.feedback.strip():
        raise HTTPException(status_code=400, detail="피드백 내용을 입력하세요.")

    current_sections = {
        "thesis": thesis.thesis or "",
        "risk": thesis.risk or "",
        "key_assumptions": thesis.key_assumptions or "",
        "valuation": thesis.valuation or "",
    }

    def event_stream():
        sections = {}
        try:
            for sse_str in refine_thesis_stream(
                symbol=ticker.symbol,
                name=ticker.name,
                market=ticker.market.value,
                ticker_id=str(ticker.id),
                current_sections=current_sections,
                feedback=body.feedback,
            ):
                if sse_str.startswith("data:"):
                    try:
                        payload = json.loads(sse_str[5:].strip())
                        if payload.get("type") == "complete":
                            sections = payload.get("sections", {})
                    except Exception:
                        pass
                yield sse_str
        except Exception as e:
            logger.exception("Thesis refine failed for %s", ticker.symbol)
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
            return

        if sections:
            t = db.query(Thesis).filter(Thesis.ticker_id == ticker.id).first()
            if t:
                t.thesis = sections.get("thesis")
                t.risk = sections.get("risk")
                t.key_assumptions = sections.get("key_assumptions")
                t.valuation = sections.get("valuation")
                was_confirmed = t.confirmed == ThesisStatusEnum.CONFIRMED
                t.confirmed = (
                    ThesisStatusEnum.NEEDS_REVIEW if was_confirmed else ThesisStatusEnum.DRAFT
                )
                t.last_analyzed_at = datetime.utcnow()
                db.commit()
                logger.info("Thesis refined for %s", ticker.symbol)
                if was_confirmed:
                    notify_thesis_needs_review(ticker.symbol, ticker.name, ticker.market.value, ticker_id=str(ticker.id))

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{ticker_id}/financial-data")
def get_financial_data(ticker_id: str, db: Session = Depends(get_db)):
    """캐시된 재무 데이터 전체 반환. 데이터 없으면 404."""
    from models.db import FinancialCache, SecFilingSummary
    from services.financial_data import fetch_all

    ticker = db.query(Ticker).filter(Ticker.id == ticker_id).first()
    if not ticker:
        raise HTTPException(status_code=404, detail="Ticker not found")

    has_cache = db.query(FinancialCache).filter(FinancialCache.ticker_id == ticker_id).first() is not None
    if not has_cache:
        raise HTTPException(status_code=404, detail="재무 데이터가 없습니다.")

    fin = fetch_all(ticker.symbol, ticker_id=ticker_id, db=db, market=ticker.market.value)

    cache_rows = db.query(FinancialCache).filter(FinancialCache.ticker_id == ticker_id).all()
    cache_info = {
        row.data_type: {"fetched_at": row.fetched_at.isoformat(), "expires_at": row.expires_at.isoformat()}
        for row in cache_rows
    }

    sec_rows = (
        db.query(SecFilingSummary)
        .filter(SecFilingSummary.ticker_id == ticker_id)
        .order_by(SecFilingSummary.report_period.desc())
        .all()
    )

    return {
        "company_info": fin.get("company_info", ""),
        "income_table": fin.get("income_table", ""),
        "cf_table": fin.get("cf_table", ""),
        "bs_table": fin.get("bs_table", ""),
        "key_metrics_text": fin.get("key_metrics", ""),
        "news_text": fin.get("news", ""),
        "insider_text": fin.get("insider_trades", ""),
        "metrics": fin.get("_metrics", {}),
        "income": fin.get("_income", []),
        "cache_info": cache_info,
        "sec_summaries": [
            {
                "filing_type": s.filing_type,
                "report_period": s.report_period,
                "filing_url": s.filing_url,
                "business_summary": s.business_summary,
                "risk_summary": s.risk_summary,
                "mda_summary": s.mda_summary,
                "summarized_at": s.summarized_at.isoformat(),
            }
            for s in sec_rows
        ],
    }


@router.get("/{ticker_id}/data-status")
def get_data_status(ticker_id: str, db: Session = Depends(get_db)):
    """재무 데이터 캐시 상태 조회."""
    from models.db import FinancialCache, SecFilingSummary
    cache_row = (
        db.query(FinancialCache)
        .filter(FinancialCache.ticker_id == ticker_id)
        .order_by(FinancialCache.fetched_at.desc())
        .first()
    )
    sec_count = db.query(SecFilingSummary).filter(SecFilingSummary.ticker_id == ticker_id).count()
    return {
        "has_data": cache_row is not None,
        "fetched_at": cache_row.fetched_at.isoformat() if cache_row else None,
        "expires_at": cache_row.expires_at.isoformat() if cache_row else None,
        "sec_summaries": sec_count,
    }


@router.get("/{ticker_id}/reports")
def get_ticker_reports(ticker_id: str, db: Session = Depends(get_db)):
    """특정 종목의 보고서 목록 (최신순)."""
    from models.db import Report
    ticker = db.query(Ticker).filter(Ticker.id == ticker_id).first()
    if not ticker:
        raise HTTPException(status_code=404, detail="Ticker not found")
    reports = (
        db.query(Report)
        .filter(Report.ticker_id == ticker_id)
        .order_by(Report.created_at.desc())
        .all()
    )
    return [
        {
            "id": str(r.id),
            "type": r.type.value,
            "content": r.content,
            "created_at": r.created_at.isoformat(),
        }
        for r in reports
    ]


@router.post("/{ticker_id}/refresh-data", status_code=202)
def refresh_data(ticker_id: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """재무 데이터 강제 새로고침 (캐시 무효화 + 재수집 + SEC/DART 파이프라인)."""
    ticker = db.query(Ticker).filter(Ticker.id == ticker_id).first()
    if not ticker:
        raise HTTPException(status_code=404, detail="Ticker not found")
    background_tasks.add_task(_run_refresh_data, str(ticker.id), ticker.symbol, ticker.market.value, ticker.name)
    return {"message": f"{ticker.symbol} 데이터 새로고침 시작됨"}


@router.get("/bulk-status")
def get_bulk_status():
    """현재 진행 중인 bulk 작업 상태 반환. 없으면 active=False."""
    with _job_lock:
        if _current_job is None:
            return {"active": False, "action": None, "items": [], "started_at": None, "finished_at": None}
        return {"active": True, **copy.deepcopy(_current_job)}


@router.post("/bulk-refresh", status_code=202)
def bulk_refresh(body: BulkRefreshBody, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """선택 종목 데이터 수집을 백그라운드에서 순차 실행. 종목 간 2초 딜레이로 rate limit 보호."""
    tickers = db.query(Ticker).filter(Ticker.id.in_(body.ticker_ids)).all()
    ticker_map = {str(t.id): t for t in tickers}
    jobs = [(str(t.id), t.symbol, t.market.value, t.name)
            for tid in body.ticker_ids if (t := ticker_map.get(tid)) is not None]
    if not jobs:
        return {"message": "종목을 찾을 수 없습니다.", "count": 0}
    items = [{"ticker_id": tid, "symbol": sym, "name": name, "status": "waiting", "msg": None}
             for tid, sym, _, name in jobs]
    started, existing, same_request = _job_try_init("refresh", items)
    if not started:
        if same_request:
            return {"message": "이미 같은 데이터 수집 작업이 진행 중입니다.", "count": len(existing["items"])}
        raise HTTPException(status_code=409, detail="다른 일괄 작업이 진행 중입니다. 완료 후 다시 실행하세요.")
    background_tasks.add_task(_run_bulk_refresh, jobs)
    return {"message": f"{len(jobs)}개 종목 데이터 수집 시작됨", "count": len(jobs)}


def _run_bulk_refresh(jobs: list[tuple]):
    for i, (ticker_id, symbol, market, name) in enumerate(jobs):
        if i > 0:
            time.sleep(2)
        _job_update(ticker_id, "running")
        logger.info("Bulk refresh: %s (%d/%d)", symbol, i + 1, len(jobs))
        ok = _run_refresh_data(ticker_id, symbol, market, name)
        _job_update(ticker_id, "done" if ok else "error")
    _job_finish()


@router.post("/{ticker_id}/report", status_code=202)
def create_report(ticker_id: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """개별 종목 심층 보고서 생성 (백그라운드). 데이터 캐시가 있어야 함."""
    from models.db import FinancialCache
    ticker = db.query(Ticker).filter(Ticker.id == ticker_id).first()
    if not ticker:
        raise HTTPException(status_code=404, detail="Ticker not found")

    has_cache = db.query(FinancialCache).filter(FinancialCache.ticker_id == ticker_id).first() is not None
    if not has_cache:
        raise HTTPException(status_code=400, detail="재무 데이터가 없습니다. 먼저 '데이터 새로고침'을 실행하세요.")

    thesis = db.query(Thesis).filter(Thesis.ticker_id == ticker.id).first()
    background_tasks.add_task(
        _run_report,
        str(ticker.id), ticker.symbol, ticker.name, ticker.market.value,
        thesis.thesis or "" if thesis else "",
        thesis.risk or "" if thesis else "",
        thesis.key_assumptions or "" if thesis else "",
        thesis.valuation or "" if thesis else "",
    )
    return {"message": f"{ticker.symbol} 심층 보고서 생성 시작됨 (완료 시 Telegram 알림)"}


@router.post("/bulk-report", status_code=202)
def bulk_report(body: BulkRefreshBody, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """선택 종목 보고서 생성을 백그라운드에서 순차 실행. 종목 간 30초 딜레이로 rate limit 보호."""
    from models.db import FinancialCache

    tickers = db.query(Ticker).filter(Ticker.id.in_(body.ticker_ids)).all()
    ticker_map = {str(t.id): t for t in tickers}
    jobs = []
    for tid in body.ticker_ids:
        t = ticker_map.get(tid)
        if not t:
            continue
        thesis = db.query(Thesis).filter(Thesis.ticker_id == t.id).first()
        has_cache = db.query(FinancialCache).filter(FinancialCache.ticker_id == t.id).first() is not None
        jobs.append((
            str(t.id), t.symbol, t.name, t.market.value,
            thesis.thesis or "" if thesis else "",
            thesis.risk or "" if thesis else "",
            thesis.key_assumptions or "" if thesis else "",
            thesis.valuation or "" if thesis else "",
            has_cache,
        ))
    if not jobs:
        return {"message": "종목을 찾을 수 없습니다.", "count": 0}
    items = [{"ticker_id": j[0], "symbol": j[1], "name": j[2], "status": "waiting", "msg": None}
             for j in jobs]
    started, existing, same_request = _job_try_init("report", items)
    if not started:
        if same_request:
            return {"message": "이미 같은 보고서 생성 작업이 진행 중입니다.", "count": len(existing["items"])}
        raise HTTPException(status_code=409, detail="다른 일괄 작업이 진행 중입니다. 완료 후 다시 실행하세요.")
    background_tasks.add_task(_run_bulk_report, jobs)
    return {"message": f"{len(jobs)}개 종목 보고서 생성 시작됨 (완료 시 Telegram 알림)", "count": len(jobs)}


def _run_bulk_report(jobs: list[tuple]):
    for i, (ticker_id, symbol, name, market, thesis, risk, key_assumptions, valuation, has_cache) in enumerate(jobs):
        if i > 0:
            time.sleep(30)  # report max_tokens=16000, 종목간 30초 쿨다운
        _job_update(ticker_id, "running")
        logger.info("Bulk report: %s (%d/%d)", symbol, i + 1, len(jobs))
        if not has_cache:
            _job_update(ticker_id, "error", "재무 데이터가 없습니다. 먼저 데이터 수집을 실행하세요.")
            continue
        try:
            ok = _run_report(ticker_id, symbol, name, market, thesis, risk, key_assumptions, valuation)
            _job_update(ticker_id, "done" if ok else "error")
        except Exception:
            _job_update(ticker_id, "error")
            logger.exception("Bulk report failed: %s", symbol)
    _job_finish()


@router.post("/bulk-analyze", status_code=202)
def bulk_analyze(body: BulkAnalyzeBody, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """선택 종목 (또는 thesis 없는 전체) 일괄 AI 분석 (백그라운드 순차 실행)."""
    if body.ticker_ids:
        tickers = db.query(Ticker).filter(Ticker.id.in_(body.ticker_ids)).all()
        ticker_map = {str(t.id): t for t in tickers}
        targets = [ticker_map[tid] for tid in body.ticker_ids if tid in ticker_map]
    else:
        tickers = db.query(Ticker).all()
        targets = [t for t in tickers if not (t.thesis and t.thesis.thesis)]
    if not targets:
        return {"message": "분석 대상 종목이 없습니다.", "count": 0}
    jobs = [(str(t.id), t.symbol, t.name, t.market.value) for t in targets]
    items = [{"ticker_id": j[0], "symbol": j[1], "name": j[2], "status": "waiting", "msg": None}
             for j in jobs]
    started, existing, same_request = _job_try_init("analyze", items)
    if not started:
        if same_request:
            return {"message": "이미 같은 Thesis 생성 작업이 진행 중입니다.", "count": len(existing["items"])}
        raise HTTPException(status_code=409, detail="다른 일괄 작업이 진행 중입니다. 완료 후 다시 실행하세요.")
    background_tasks.add_task(_run_bulk_analyze, jobs)
    return {"message": f"{len(jobs)}개 종목 분석 시작됨", "count": len(jobs)}


@router.post("/bulk-resolve-valley", status_code=202)
def bulk_resolve_valley(body: BulkRefreshBody, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """선택 종목의 Valley 링크를 백그라운드에서 조회/캐시."""
    tickers = db.query(Ticker).filter(Ticker.id.in_(body.ticker_ids)).all()
    ticker_map = {str(t.id): t for t in tickers}
    jobs = [(str(t.id), t.symbol, t.name, t.market.value)
            for tid in body.ticker_ids if (t := ticker_map.get(tid)) is not None]
    if not jobs:
        return {"message": "종목을 찾을 수 없습니다.", "count": 0}
    items = [{"ticker_id": j[0], "symbol": j[1], "name": j[2], "status": "waiting", "msg": None}
             for j in jobs]
    started, existing, same_request = _job_try_init("valley", items)
    if not started:
        if same_request:
            return {"message": "이미 같은 Valley 링크 조회 작업이 진행 중입니다.", "count": len(existing["items"])}
        raise HTTPException(status_code=409, detail="다른 일괄 작업이 진행 중입니다. 완료 후 다시 실행하세요.")
    background_tasks.add_task(_run_bulk_resolve_valley, jobs)
    return {"message": f"{len(jobs)}개 종목 Valley 링크 조회 시작됨", "count": len(jobs)}


def _run_bulk_analyze(jobs: list[tuple]):
    from models.db import SessionLocal
    from services.agent import generate_thesis
    from services.financial_data import fetch_all
    for i, (ticker_id, symbol, name, market) in enumerate(jobs):
        if i > 0:
            time.sleep(20)  # thesis max_tokens=4096, 종목간 20초 쿨다운
        _job_update(ticker_id, "running")
        db = SessionLocal()
        try:
            logger.info("Bulk analyze: %s (%d/%d)", symbol, i + 1, len(jobs))
            try:
                fin = fetch_all(symbol, ticker_id=ticker_id, db=db, market=market, company_name=name)
                financial_context = _format_financial_context(fin) if fin.get("has_data") else ""
            except Exception:
                financial_context = ""
            thesis = db.query(Thesis).filter(Thesis.ticker_id == ticker_id).first()
            existing_stock_type = thesis.stock_type if thesis and thesis.stock_type else "compounding"
            existing_seed_memo = thesis.seed_memo or ""
            sections = generate_thesis(symbol=symbol, name=name, market=market,
                                       ticker_id=ticker_id, financial_context=financial_context,
                                       stock_type=existing_stock_type, seed_memo=existing_seed_memo)
            if not thesis:
                thesis = Thesis(ticker_id=ticker_id, confirmed=ThesisStatusEnum.DRAFT)
                db.add(thesis)
            thesis.thesis = sections.get("thesis")
            thesis.risk = sections.get("risk")
            thesis.key_assumptions = sections.get("key_assumptions")
            thesis.valuation = sections.get("valuation")
            thesis.last_analyzed_at = datetime.utcnow()
            db.commit()
            _job_update(ticker_id, "done")
            logger.info("Bulk analyze done: %s", symbol)
        except Exception:
            _job_update(ticker_id, "error")
            logger.exception("Bulk analyze failed: %s", symbol)
        finally:
            db.close()
    _job_finish()


def _run_bulk_resolve_valley(jobs: list[tuple]):
    from models.db import SessionLocal

    for i, (ticker_id, symbol, name, market) in enumerate(jobs):
        if i > 0:
            time.sleep(2)
        _job_update(ticker_id, "running")
        db = SessionLocal()
        try:
            url, reason = resolve_valley_url_with_reason(db, ticker_id, symbol, name, market)
            if url:
                _job_update(ticker_id, "done")
            else:
                _job_update(ticker_id, "error", reason or "Valley 종목 조회 실패")
        except Exception as e:
            _job_update(ticker_id, "error", str(e)[:120])
            logger.exception("Bulk valley resolve failed: %s", symbol)
        finally:
            db.close()
    _job_finish()


def _run_refresh_data(ticker_id: str, symbol: str, market: str = "US_Stock", name: str = "") -> bool:
    """재무 데이터 수집 + SEC/DART 파이프라인. 성공 시 True, 실패 시 False 반환."""
    from models.db import SessionLocal, FinancialCache
    from services.financial_data import fetch_all
    from services.sec_pipeline import run_sec_pipeline

    db = SessionLocal()
    try:
        deleted = db.query(FinancialCache).filter(FinancialCache.ticker_id == ticker_id).delete()
        db.commit()
        logger.info("Cleared %d cache rows for %s", deleted, symbol)

        fin = fetch_all(symbol, ticker_id=ticker_id, db=db, market=market, company_name=name)
        logger.info("Financial data refreshed for %s (has_data=%s)", symbol, fin["has_data"])

        if fin.get("filing_refs") and market == "US_Stock":
            saved = run_sec_pipeline(fin["filing_refs"], ticker_id, db)
            if saved:
                logger.info("SEC pipeline saved %d new summaries for %s", saved, symbol)
            # 8-K 파이프라인 (ETF 제외 — filing_refs 있으면 non-ETF)
            from services.sec_pipeline import run_8k_pipeline
            saved_8k = run_8k_pipeline(symbol, ticker_id, db)
            if saved_8k:
                logger.info("8-K pipeline saved %d new summaries for %s", saved_8k, symbol)
        elif fin.get("filing_refs") and market == "KR_Stock":
            from services.dart_pipeline import run_dart_pipeline
            saved = run_dart_pipeline(fin["filing_refs"], ticker_id, db)
            logger.info("DART pipeline: %d new summaries for %s", saved, symbol)
        else:
            logger.info("No filing_refs for %s (market=%s)", symbol, market)
        return True
    except Exception:
        logger.exception("Data refresh failed for %s", symbol)
        return False
    finally:
        db.close()


def _run_report(
    ticker_id: str, symbol: str, name: str, market: str,
    thesis: str, risk: str, key_assumptions: str, valuation: str,
) -> bool:
    from models.db import SessionLocal

    db = SessionLocal()
    try:
        # DB 캐시 + SEC 요약 그대로 읽어서 보고서 생성 (데이터 수집 없음)
        sections = generate_ticker_report(
            symbol=symbol, name=name, market=market, ticker_id=ticker_id,
            thesis=thesis, risk=risk, key_assumptions=key_assumptions, valuation=valuation,
            db=db,
        )
        report = Report(
            ticker_id=ticker_id,
            type=ReportTypeEnum.ANALYSIS,
            content=sections["full_text"],
        )
        db.add(report)
        db.commit()
        logger.info("Deep report saved for %s", symbol)
        summary = sections.get("investment_conclusion", sections.get("business_overview", ""))[:300]
        notify_report_generated(symbol, name, summary, report_id=str(report.id))
        return True
    except Exception:
        logger.exception("Report generation failed for %s", symbol)
        return False
    finally:
        db.close()
