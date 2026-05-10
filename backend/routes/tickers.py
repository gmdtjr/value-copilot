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
    exploration_note: Optional[str] = None
    monitoring_contract: Optional[str] = None


class RefineBody(BaseModel):
    feedback: str


class DirectThesisBody(BaseModel):
    stock_type: str
    thesis: Optional[str] = None
    risk: Optional[str] = None
    key_assumptions: Optional[str] = None
    valuation: Optional[str] = None
    key_logic: Optional[str] = None
    monitoring_contract: Optional[str] = None


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
    open_cycle_opened_at: Optional[str] = None  # 진행 중인 사이클 시작일

    class Config:
        from_attributes = True


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("", response_model=list[TickerResponse])
def list_tickers(db: Session = Depends(get_db)):
    from sqlalchemy.orm import selectinload
    from models.db import InvestmentCycle, CycleStatusEnum
    tickers = db.query(Ticker).options(selectinload(Ticker.theses)).order_by(Ticker.created_at.desc()).all()

    # 진행 중 사이클 일괄 조회 (N+1 방지)
    open_cycles: dict = {}
    try:
        tid_list = [t.id for t in tickers]
        for c in db.query(InvestmentCycle).filter(
            InvestmentCycle.ticker_id.in_(tid_list),
            InvestmentCycle.status == CycleStatusEnum.OPEN,
        ).all():
            open_cycles[str(c.ticker_id)] = c.opened_at.isoformat()
    except Exception:
        pass  # investment_cycles 테이블 미생성 환경 graceful fallback

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
            open_cycle_opened_at=open_cycles.get(str(t.id)),
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

    thesis = Thesis(ticker_id=ticker.id, confirmed=ThesisStatusEnum.DRAFT, version_number=1)
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
    thesis = (
        db.query(Thesis)
        .filter(Thesis.ticker_id == ticker.id, Thesis.confirmed == ThesisStatusEnum.CONFIRMED)
        .order_by(Thesis.version_number.desc().nullslast())
        .first()
    )
    if not thesis:
        raise HTTPException(status_code=400, detail="confirmed 상태의 thesis가 없습니다.")
    key_logic = getattr(thesis, 'key_logic', None) or ""
    monitoring_contract = getattr(thesis, 'monitoring_contract', None) or ""
    background_tasks.add_task(
        _run_break_monitor_task,
        str(ticker.id), str(thesis.id), ticker.symbol, ticker.name,
        key_logic, monitoring_contract, thesis.key_assumptions or "",
        thesis.stock_type.value if thesis.stock_type else "",
    )
    return {"message": f"{ticker.symbol} Break Monitor 시작됨"}


def _run_break_monitor_task(
    ticker_id: str, thesis_id: str, symbol: str, name: str,
    key_logic: str, monitoring_contract: str, key_assumptions: str, stock_type: str = "",
):
    from models.db import SessionLocal, BreakSignal
    from services.scheduler import _get_cache, _fmt_news_full, _fmt_metrics
    db = SessionLocal()
    try:
        news_data = _get_cache(db, ticker_id, "news")
        metrics_data = _get_cache(db, ticker_id, "metrics")
        result = run_break_monitor(
            symbol=symbol, name=name, ticker_id=ticker_id,
            key_logic=key_logic, monitoring_contract=monitoring_contract, key_assumptions=key_assumptions,
            news_context=_fmt_news_full(news_data, limit=7),
            metrics_context=_fmt_metrics(metrics_data),
            stock_type=stock_type,
        )
        # BreakSignal 저장
        signal = BreakSignal(
            thesis_id=thesis_id,
            key_logic_snapshot=result.get("key_logic_snapshot") or key_logic or None,
            observations=result.get("observations", result.get("full_text", "")),
            positive_signals=result.get("positive_signals"),
            negative_signals=result.get("negative_signals"),
            watch_items=result.get("watch_items"),
        )
        db.add(signal)
        db.commit()
        notify_break_monitor(symbol, name, result.get("observations", ""), ticker_id=ticker_id)
        logger.info("Break Monitor 완료: %s (signal_id=%s)", symbol, signal.id)
    except Exception:
        logger.exception("Break Monitor 실패: %s", symbol)
        try:
            db.rollback()
        except Exception:
            pass
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

    # Determine target thesis: create new version if current is confirmed
    try:
        active = (
            db.query(Thesis)
            .filter(Thesis.ticker_id == ticker.id, Thesis.confirmed != ThesisStatusEnum.RETIRED)
            .order_by(Thesis.version_number.desc().nullslast())
            .first()
        )
    except Exception:
        db.rollback()
        active = db.query(Thesis).filter(Thesis.ticker_id == ticker.id).first()
    is_new_version = False
    if active and active.confirmed == ThesisStatusEnum.CONFIRMED:
        # Create new draft version
        new_v = (active.version_number or 1) + 1
        new_thesis = Thesis(
            ticker_id=ticker.id,
            version_number=new_v,
            parent_version_id=active.id,
            confirmed=ThesisStatusEnum.DRAFT,
            stock_type=body.stock_type,
            seed_memo=body.seed_memo,
            exploration_note=body.exploration_note,
            monitoring_contract=body.monitoring_contract,
        )
        db.add(new_thesis)
        db.flush()
        target_id = str(new_thesis.id)
        is_new_version = True
    elif active:
        # Update draft/needs_review in place
        active.stock_type = body.stock_type
        active.seed_memo = body.seed_memo
        if body.exploration_note:
            active.exploration_note = body.exploration_note
        if body.monitoring_contract:
            active.monitoring_contract = body.monitoring_contract
        db.flush()
        target_id = str(active.id)
    else:
        target_id = None
    db.commit()

    ticker_symbol = ticker.symbol
    ticker_name = ticker.name
    ticker_market = ticker.market.value
    ticker_id_str = str(ticker.id)

    def event_stream():
        sections = {}
        try:
            for sse_str in generate_thesis_stream(
                symbol=ticker_symbol,
                name=ticker_name,
                market=ticker_market,
                ticker_id=ticker_id_str,
                financial_context=financial_context,
                stock_type=body.stock_type,
                seed_memo=body.seed_memo,
                exploration_note=body.exploration_note or "",
                monitoring_contract=body.monitoring_contract or "",
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
            logger.exception("Thesis generation failed for %s", ticker_symbol)
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
            return

        if sections and target_id:
            from models.db import SessionLocal as _SessionLocal
            local_db = _SessionLocal()
            try:
                t = local_db.query(Thesis).filter(Thesis.id == target_id).first()
                if t:
                    t.thesis = sections.get("thesis")
                    t.risk = sections.get("risk")
                    t.key_assumptions = sections.get("key_assumptions")
                    t.valuation = sections.get("valuation")
                    t.monitoring_contract = sections.get("monitoring_contract") or body.monitoring_contract
                    t.last_analyzed_at = datetime.utcnow()
                    local_db.commit()
                    logger.info("Thesis saved for %s (v%s)", ticker_symbol, t.version_number)
                if is_new_version:
                    notify_thesis_needs_review(ticker_symbol, ticker_name, ticker_market, ticker_id=ticker_id_str)
            except Exception:
                logger.exception("Thesis DB save failed for %s", ticker_symbol)
            finally:
                local_db.close()

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
    # 최신 비-retired thesis에서 refine
    try:
        thesis = (
            db.query(Thesis)
            .filter(Thesis.ticker_id == ticker.id, Thesis.confirmed != ThesisStatusEnum.RETIRED)
            .order_by(Thesis.version_number.desc().nullslast())
            .first()
        )
    except Exception:
        db.rollback()
        thesis = db.query(Thesis).filter(Thesis.ticker_id == ticker.id).first()
    if not thesis or not thesis.thesis:
        raise HTTPException(status_code=400, detail="먼저 AI 분석을 실행하세요.")
    if thesis.confirmed == ThesisStatusEnum.CONFIRMED:
        raise HTTPException(status_code=400, detail="Confirmed thesis는 직접 수정할 수 없습니다. 'AI 분석'으로 새 버전을 생성하세요.")
    if not body.feedback.strip():
        raise HTTPException(status_code=400, detail="피드백 내용을 입력하세요.")

    current_sections = {
        "thesis": thesis.thesis or "",
        "risk": thesis.risk or "",
        "key_assumptions": thesis.key_assumptions or "",
        "valuation": thesis.valuation or "",
        "key_logic": getattr(thesis, "key_logic", None) or "",
        "monitoring_contract": getattr(thesis, "monitoring_contract", None) or "",
    }
    target_id = str(thesis.id)
    ticker_symbol = ticker.symbol
    ticker_name = ticker.name
    ticker_market = ticker.market.value
    ticker_id_str = str(ticker.id)

    def event_stream():
        sections = {}
        try:
            for sse_str in refine_thesis_stream(
                symbol=ticker_symbol,
                name=ticker_name,
                market=ticker_market,
                ticker_id=ticker_id_str,
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
            logger.exception("Thesis refine failed for %s", ticker_symbol)
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
            return

        if sections:
            from models.db import SessionLocal as _SessionLocal
            local_db = _SessionLocal()
            try:
                t = local_db.query(Thesis).filter(Thesis.id == target_id).first()
                if t:
                    t.thesis = sections.get("thesis")
                    t.risk = sections.get("risk")
                    t.key_assumptions = sections.get("key_assumptions")
                    t.valuation = sections.get("valuation")
                    t.monitoring_contract = sections.get("monitoring_contract")
                    t.last_analyzed_at = datetime.utcnow()
                    local_db.commit()
                    logger.info("Thesis refined for %s", ticker_symbol)
            except Exception:
                logger.exception("Thesis refine DB save failed")
            finally:
                local_db.close()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{ticker_id}/thesis/direct")
def create_thesis_direct(ticker_id: str, body: DirectThesisBody, db: Session = Depends(get_db)):
    """직접 입력으로 Thesis draft 생성/수정. AI 호출 없음."""
    ticker = db.query(Ticker).filter(Ticker.id == ticker_id).first()
    if not ticker:
        raise HTTPException(status_code=404, detail="Ticker not found")

    try:
        active = (
            db.query(Thesis)
            .filter(Thesis.ticker_id == ticker.id, Thesis.confirmed != ThesisStatusEnum.RETIRED)
            .order_by(Thesis.version_number.desc().nullslast())
            .first()
        )
    except Exception:
        db.rollback()
        active = db.query(Thesis).filter(Thesis.ticker_id == ticker.id).first()

    is_new_version = False
    if active and active.confirmed == ThesisStatusEnum.CONFIRMED:
        new_v = (active.version_number or 1) + 1
        target = Thesis(
            ticker_id=ticker.id,
            version_number=new_v,
            parent_version_id=active.id,
            confirmed=ThesisStatusEnum.DRAFT,
            stock_type=body.stock_type,
            thesis=body.thesis,
            risk=body.risk,
            key_assumptions=body.key_assumptions,
            valuation=body.valuation,
            key_logic=body.key_logic,
            monitoring_contract=body.monitoring_contract,
            last_analyzed_at=datetime.utcnow(),
        )
        db.add(target)
        is_new_version = True
    elif active:
        active.stock_type = body.stock_type
        active.thesis = body.thesis
        active.risk = body.risk
        active.key_assumptions = body.key_assumptions
        active.valuation = body.valuation
        active.key_logic = body.key_logic
        active.monitoring_contract = body.monitoring_contract
        active.last_analyzed_at = datetime.utcnow()
        target = active
    else:
        target = Thesis(
            ticker_id=ticker.id,
            version_number=1,
            confirmed=ThesisStatusEnum.DRAFT,
            stock_type=body.stock_type,
            thesis=body.thesis,
            risk=body.risk,
            key_assumptions=body.key_assumptions,
            valuation=body.valuation,
            key_logic=body.key_logic,
            monitoring_contract=body.monitoring_contract,
            last_analyzed_at=datetime.utcnow(),
        )
        db.add(target)
        is_new_version = True

    db.commit()
    db.refresh(target)

    if is_new_version and active:
        notify_thesis_needs_review(ticker.symbol, ticker.name, ticker.market.value, ticker_id=ticker_id)

    logger.info("Thesis directly entered for %s (v%s)", ticker.symbol, target.version_number)
    return {"ok": True}


@router.get("/{ticker_id}/explore-prompt")
def get_ticker_explore_prompt(
    ticker_id: str,
    type: str = "deep_analysis",
    signal_id: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Step 3 (종목 집중 분석) / Step 4 (반대 논거 탐색) 외부 Claude 프롬프트 생성."""
    ticker = db.query(Ticker).filter(Ticker.id == ticker_id).first()
    if not ticker:
        raise HTTPException(status_code=404, detail="Ticker not found")

    try:
        # thesis는 버전 필터 없이 간단하게 조회 (Phase 2 컬럼 없는 환경도 호환)
        thesis = db.query(Thesis).filter(Thesis.ticker_id == ticker.id).first()

        if type == "deep_analysis":
            prompt = _build_deep_analysis_prompt(db, ticker, thesis)
        elif type == "monitoring_contract":
            prompt = _build_thesis_complete_prompt(db, ticker, thesis)
        elif type == "thesis_revision":
            prompt = _build_thesis_revision_prompt(db, ticker, thesis, signal_id)
        else:
            raise HTTPException(status_code=400, detail=f"알 수 없는 type: {type}")
        return {"prompt": prompt}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("ticker explore-prompt 생성 실패: %s/%s", ticker_id, type)
        raise HTTPException(status_code=500, detail=f"프롬프트 생성 오류: {str(e)}")


def _build_deep_analysis_prompt(db, ticker, thesis) -> str:
    """Step 3: 보고서를 읽은 후 외부 Claude와 종목을 집중 분석하는 프롬프트."""
    from models.db import Report, ReportTypeEnum

    lines = [
        f"# {ticker.name} ({ticker.symbol}) 종목 집중 분석",
        "",
        "당신은 가치투자 전문가입니다. 아래 종목에 대해 집중적으로 분석해주세요.",
        "",
        f"## 종목 기본 정보",
        f"- 이름: {ticker.name}",
        f"- 심볼: {ticker.symbol}",
        f"- 시장: {ticker.market.value}",
        "",
    ]

    # 최신 심층 보고서 (분석 보고서)
    latest_report = (
        db.query(Report)
        .filter(Report.ticker_id == ticker.id, Report.type == ReportTypeEnum.ANALYSIS)
        .order_by(Report.created_at.desc())
        .first()
    )

    if latest_report:
        # XML 섹션에서 핵심 내용 추출
        import re
        def extract(content, name):
            m = re.search(rf'<section name="{name}">(.*?)</section>', content, re.DOTALL)
            return m.group(1).strip()[:600] if m else ""

        biz = extract(latest_report.content, "business_overview")
        competitive = extract(latest_report.content, "competitive_position")
        bull_bear = extract(latest_report.content, "bull_bear_synthesis")

        lines.extend([
            "## 내부 보고서 요약 (참고용)",
            "",
        ])
        if biz:
            lines.extend([f"### 기업 개요\n{biz}", ""])
        if competitive:
            lines.extend([f"### 경쟁 구도\n{competitive}", ""])
        if bull_bear:
            lines.extend([f"### Bull/Bear 종합\n{bull_bear}", ""])
    else:
        lines.extend(["(심층 보고서 없음 — 공개 정보 기반으로 분석해주세요)", ""])

    lines.extend([
        "## 분석 요청",
        "",
        "아래 항목을 중심으로 깊이 있는 분석을 해주세요:",
        "",
        "1. **이 비즈니스의 진짜 경쟁 우위는 무엇인가?**",
        "   - 일시적인 우위와 구조적 우위를 구분해서",
        "",
        "2. **향후 3~5년 시나리오: 낙관/기본/비관**",
        "   - 각 시나리오의 핵심 전제와 트리거는?",
        "",
        "3. **지금 이 주가에 내포된 기대치는 무엇인가?**",
        "   - 시장이 무엇을 pricing 하고 있는가?",
        "",
        "4. **투자 유형과 핵심 논거 방향**",
        "   - compounding/growth/asset_play/turnaround/cyclical/special_situation 중 어떤 프레임이 맞는가?",
        "   - 그 관점에서 핵심 투자 논거 한 단락을 제시해줘",
        "",
        "분석 후 내가 직접 투자 thesis를 작성할 수 있도록 방향을 제시해주세요. 매수/매도 추천은 하지 마세요.",
    ])

    return "\n".join(lines)



def _build_thesis_complete_prompt(db, ticker, thesis) -> str:
    """외부 Claude 대화의 마지막 단계: 5개 필드 완성형 Thesis 산출."""

    lines = [
        f"# {ticker.name} ({ticker.symbol}) 최종 Thesis 완성",
        "",
        "지금까지 이 대화에서 나눈 종목 분석, 반대 논거, 추가 리서치 내용을 아래 5개 섹션으로 정리해주세요.",
        "이 결과는 value-copilot 앱의 'Thesis 작성' 모달에 각 필드에 직접 붙여넣을 것입니다.",
        "",
        "원칙:",
        "- 새로운 추천을 만들지 말고 지금까지 대화에서 형성된 논리를 구조화하세요.",
        "- 주가 등락, 목표가, 애널리스트 의견은 논거로 쓰지 마세요.",
        "- Monitoring Contract는 Break Monitor가 그대로 사용합니다. 측정 가능한 조건으로 쓰세요.",
        "",
        f"## 종목 정보",
        f"- 이름: {ticker.name} ({ticker.symbol}, {ticker.market.value})",
        "",
    ]

    lines.extend([
        "## 출력 형식",
        "",
        "아래 5개 섹션만, 헤더 그대로 출력하세요.",
        "",
        "---",
        "",
        "### [THESIS]",
        "이 종목에 투자하는 핵심 논거. 왜 지금 이 기업이 저평가됐거나 성장할 것인가.",
        "비즈니스 모델, 경쟁 우위, 성장 동력 중심으로. 3~5문단.",
        "",
        "### [RISK]",
        "thesis가 틀릴 수 있는 주요 시나리오.",
        "각 리스크의 발생 가능성과 thesis에 미치는 임팩트를 간략히 포함. 3~6항목.",
        "",
        "### [KEY_ASSUMPTIONS]",
        "thesis가 성립하기 위해 반드시 유지되어야 할 측정 가능한 가정.",
        "수치, 일정, 사건 기반으로. 예: 'FCF margin 15% 이상 유지', '2026년 내 흑자 전환'",
        "5~8항목.",
        "",
        "### [VALUATION]",
        "현재 가격에 내포된 시장의 기대치와 내 추정 Fair Value.",
        "Reverse DCF 관점 — '현재 멀티플이 어떤 성장률을 가정하는가, 그게 현실적인가'.",
        "2~3문단.",
        "",
        "### [MONITORING_CONTRACT]",
        "## Core Logic",
        "이 thesis가 성립하려면 반드시 유지되어야 하는 핵심 전제. 1~2문단.",
        "",
        "## Break Conditions",
        "- 측정 가능한 파기 조건 3~7개 (이 중 하나라도 깨지면 즉시 재검토)",
        "",
        "## Strengthening Signals",
        "- thesis 강화 신호 3~5개 (자동 매수/매도 표현 금지)",
        "",
        "## Watch Metrics",
        "- Break Monitor가 추적할 지표/뉴스/공시 5~10개",
        "",
        "## Review Timing",
        "- 즉시 재검토 조건 vs 1~2분기 관찰 후 재검토 조건 구분",
        "",
        "---",
    ])

    return "\n".join(lines)


def _build_thesis_revision_prompt(db, ticker, thesis, signal_id: Optional[str] = None) -> str:
    """Break Monitor 결과를 외부 Claude 대화에서 재검토하도록 만드는 프롬프트."""
    from models.db import BreakSignal

    signal = None
    if signal_id:
        signal = db.query(BreakSignal).filter(BreakSignal.id == signal_id).first()

    lines = [
        f"# {ticker.name} ({ticker.symbol}) Thesis 재검토",
        "",
        "아래 confirmed thesis와 Break Monitor 관찰 결과를 바탕으로, thesis를 유지/강화/수정/파기해야 할 논리적 이유를 검토해주세요.",
        "목적은 자동 매수/매도가 아니라, value-copilot에 붙여넣을 새 thesis 버전의 seed memo와 monitoring contract를 보완하는 것입니다.",
        "",
        "중요 원칙:",
        "- 주가 등락, 목표가, 애널리스트 의견은 제외하세요.",
        "- Break Monitor의 positive_signals는 thesis 강화 가능성으로, negative_signals는 thesis 약화 가능성으로 검토하세요.",
        "- 결론은 행동 지시가 아니라 '사람이 확인할 논리 변화'로 작성하세요.",
        "- 기존 thesis가 아직 유효하다면 무엇을 더 확인해야 하는지, 수정이 필요하다면 어느 섹션을 어떻게 고칠지 제안하세요.",
        "",
        "## 종목 정보",
        f"- 이름: {ticker.name}",
        f"- 심볼: {ticker.symbol}",
        f"- 시장: {ticker.market.value}",
        "",
    ]

    if thesis:
        if thesis.seed_memo:
            lines.extend(["## 기존 Seed Memo", thesis.seed_memo, ""])
        if thesis.thesis:
            lines.extend(["## 기존 Thesis", thesis.thesis, ""])
        if thesis.risk:
            lines.extend(["## 기존 Risk", thesis.risk, ""])
        if thesis.key_assumptions:
            lines.extend(["## 기존 Key Assumptions", thesis.key_assumptions, ""])
        if getattr(thesis, 'monitoring_contract', None):
            lines.extend(["## 기존 Monitoring Contract", thesis.monitoring_contract, ""])

    if signal:
        lines.extend([
            "## Break Monitor 관찰 결과",
            f"- 체크 시점: {signal.checked_at.isoformat()}",
            "",
            "### Observations",
            signal.observations or "(없음)",
            "",
        ])
        if signal.positive_signals:
            lines.extend(["### Positive Signals", signal.positive_signals, ""])
        if signal.negative_signals:
            lines.extend(["### Negative Signals", signal.negative_signals, ""])
        if signal.watch_items:
            lines.extend(["### Watch Items", signal.watch_items, ""])
        if signal.verdict:
            lines.extend(["### Human Verdict", signal.verdict.value, ""])
        if signal.human_note:
            lines.extend(["### Human Note", signal.human_note, ""])
    else:
        lines.extend([
            "## Break Monitor 관찰 결과",
            "(특정 signal_id가 제공되지 않았습니다. 사용자가 아래에 관찰 결과를 붙여넣을 수 있게 질문하며 진행하세요.)",
            "",
        ])

    lines.extend([
        "## 출력 형식",
        "",
        "아래 형식으로만 출력하세요.",
        "",
        "```markdown",
        "# Revision Assessment",
        "",
        "## What Changed",
        "- 이번 관찰에서 thesis의 어떤 연결고리가 강화/약화되었는가",
        "",
        "## Thesis Update Needed?",
        "- 유지 / 보완 / 재검토 / 파기 중 하나",
        "- 이유",
        "",
        "## Proposed Seed Memo Delta",
        "- 기존 seed memo에 추가/수정할 문장",
        "",
        "## Proposed Risk Delta",
        "- risk 섹션에 추가/수정할 내용",
        "",
        "## Proposed Monitoring Contract Delta",
        "### Core Logic",
        "...",
        "### Break Conditions",
        "- ...",
        "### Strengthening Signals",
        "- ...",
        "### Watch Metrics",
        "- ...",
        "",
        "## Questions Before Confirm",
        "- 사람이 확인해야 할 데이터/공시/가정",
        "```",
    ])

    return "\n".join(lines)


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


@router.delete("/{ticker_id}", status_code=204)
def delete_ticker(ticker_id: str, db: Session = Depends(get_db)):
    """종목 삭제 (thesis, reports, portfolio, cache 포함 cascade 삭제)."""
    ticker = db.query(Ticker).filter(Ticker.id == ticker_id).first()
    if not ticker:
        raise HTTPException(status_code=404, detail="Ticker not found")
    symbol = ticker.symbol
    db.delete(ticker)
    db.commit()
    logger.info("Ticker deleted: %s", symbol)


@router.post("/{ticker_id}/resolve-valley", status_code=202)
def resolve_valley_single(ticker_id: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """개별 종목 Valley.town URL 조회 (백그라운드)."""
    ticker = db.query(Ticker).filter(Ticker.id == ticker_id).first()
    if not ticker:
        raise HTTPException(status_code=404, detail="Ticker not found")
    background_tasks.add_task(
        _run_resolve_valley_single,
        str(ticker.id), ticker.symbol, ticker.name, ticker.market.value,
    )
    return {"message": f"{ticker.symbol} Valley 링크 조회 시작됨"}


def _run_resolve_valley_single(ticker_id: str, symbol: str, name: str, market: str):
    from models.db import SessionLocal
    db = SessionLocal()
    try:
        url, reason = resolve_valley_url_with_reason(db, ticker_id, symbol, name, market)
        if url:
            logger.info("Valley URL resolved for %s: %s", symbol, url)
        else:
            logger.warning("Valley URL not found for %s: %s", symbol, reason)
    except Exception:
        logger.exception("Single valley resolve failed: %s", symbol)
    finally:
        db.close()


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
        if _current_job.get("finished_at") is not None:
            return {"active": False, **copy.deepcopy(_current_job)}
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
            time.sleep(20)  # thesis max_tokens=8192, 종목간 20초 쿨다운
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
            existing_seed_memo = thesis.seed_memo if thesis and thesis.seed_memo else ""
            existing_exploration_note = getattr(thesis, "exploration_note", None) or ""
            existing_monitoring_contract = getattr(thesis, "monitoring_contract", None) or ""
            sections = generate_thesis(symbol=symbol, name=name, market=market,
                                       ticker_id=ticker_id, financial_context=financial_context,
                                       stock_type=existing_stock_type, seed_memo=existing_seed_memo,
                                       exploration_note=existing_exploration_note,
                                       monitoring_contract=existing_monitoring_contract)
            if not thesis:
                thesis = Thesis(ticker_id=ticker_id, confirmed=ThesisStatusEnum.DRAFT)
                db.add(thesis)
            thesis.thesis = sections.get("thesis")
            thesis.risk = sections.get("risk")
            thesis.key_assumptions = sections.get("key_assumptions")
            thesis.valuation = sections.get("valuation")
            thesis.monitoring_contract = sections.get("monitoring_contract")
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
