import logging
from typing import Optional

from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from models.db import get_db, Report, ReportComment, Ticker, Portfolio, Thesis, FinancialCache, ReportTypeEnum, SessionLocal, TickerStatusEnum, ThesisStatusEnum
from services.scheduler import run_daily_briefing
from services.agent import generate_macro_report, generate_discovery_stream, generate_portfolio_review_stream
from services.market_data import get_market_indicators
from services.telegram import notify_discovery_saved, notify_portfolio_review_saved, notify_macro_saved

logger = logging.getLogger(__name__)
router = APIRouter()


class DiscoveryRequest(BaseModel):
    idea: str


class MarkReadBody(BaseModel):
    is_read: bool


class CommentBody(BaseModel):
    content: str


class ReportResponse(BaseModel):
    id: str
    ticker_id: Optional[str]
    ticker_symbol: Optional[str]
    type: str
    content: str
    created_at: str
    is_read: bool
    comment_count: int


class CommentResponse(BaseModel):
    id: str
    report_id: str
    content: str
    created_at: str


@router.get("", response_model=list[ReportResponse])
def list_reports(db: Session = Depends(get_db), limit: int = 50):
    reports = (
        db.query(Report)
        .order_by(Report.created_at.desc())
        .limit(limit)
        .all()
    )
    ticker_ids = [r.ticker_id for r in reports if r.ticker_id]
    tickers = {t.id: t.symbol for t in db.query(Ticker).filter(Ticker.id.in_(ticker_ids)).all()}

    report_ids = [r.id for r in reports]
    comment_counts = dict(
        db.query(ReportComment.report_id, func.count(ReportComment.id))
        .filter(ReportComment.report_id.in_(report_ids))
        .group_by(ReportComment.report_id)
        .all()
    ) if report_ids else {}

    return [
        ReportResponse(
            id=str(r.id),
            ticker_id=str(r.ticker_id) if r.ticker_id else None,
            ticker_symbol=tickers.get(r.ticker_id) if r.ticker_id else None,
            type=r.type.value,
            content=r.content,
            created_at=r.created_at.isoformat(),
            is_read=r.is_read,
            comment_count=comment_counts.get(r.id, 0),
        )
        for r in reports
    ]


@router.delete("/{report_id}", status_code=204)
def delete_report(report_id: str, db: Session = Depends(get_db)):
    report = db.query(Report).filter(Report.id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="보고서를 찾을 수 없습니다")
    db.delete(report)
    db.commit()


@router.patch("/{report_id}/read", response_model=ReportResponse)
def mark_read(report_id: str, body: MarkReadBody, db: Session = Depends(get_db)):
    report = db.query(Report).filter(Report.id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="보고서를 찾을 수 없습니다")
    report.is_read = body.is_read
    db.commit()
    ticker_symbol = report.ticker.symbol if report.ticker_id and report.ticker else None
    comment_count = db.query(func.count(ReportComment.id)).filter(ReportComment.report_id == report.id).scalar()
    return ReportResponse(
        id=str(report.id),
        ticker_id=str(report.ticker_id) if report.ticker_id else None,
        ticker_symbol=ticker_symbol,
        type=report.type.value,
        content=report.content,
        created_at=report.created_at.isoformat(),
        is_read=report.is_read,
        comment_count=comment_count,
    )


@router.get("/{report_id}/comments", response_model=list[CommentResponse])
def get_comments(report_id: str, db: Session = Depends(get_db)):
    comments = (
        db.query(ReportComment)
        .filter(ReportComment.report_id == report_id)
        .order_by(ReportComment.created_at.asc())
        .all()
    )
    return [
        CommentResponse(id=str(c.id), report_id=str(c.report_id), content=c.content, created_at=c.created_at.isoformat())
        for c in comments
    ]


@router.post("/{report_id}/comments", status_code=201, response_model=CommentResponse)
def add_comment(report_id: str, body: CommentBody, db: Session = Depends(get_db)):
    if not body.content.strip():
        raise HTTPException(status_code=400, detail="코멘트 내용을 입력하세요")
    report = db.query(Report).filter(Report.id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="보고서를 찾을 수 없습니다")
    comment = ReportComment(report_id=report.id, content=body.content.strip())
    db.add(comment)
    db.commit()
    return CommentResponse(id=str(comment.id), report_id=str(comment.report_id), content=comment.content, created_at=comment.created_at.isoformat())


@router.delete("/{report_id}/comments/{comment_id}", status_code=204)
def delete_comment(report_id: str, comment_id: str, db: Session = Depends(get_db)):
    comment = db.query(ReportComment).filter(
        ReportComment.id == comment_id,
        ReportComment.report_id == report_id,
    ).first()
    if not comment:
        raise HTTPException(status_code=404, detail="코멘트를 찾을 수 없습니다")
    db.delete(comment)
    db.commit()


@router.post("/daily-briefing/trigger", status_code=202)
def trigger_daily_briefing(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_daily_briefing)
    return {"message": "데일리 브리핑 생성 시작됨"}


@router.post("/macro/trigger", status_code=202)
def trigger_macro_report(background_tasks: BackgroundTasks):
    background_tasks.add_task(_run_macro_report)
    return {"message": "매크로 보고서 생성 시작됨"}


@router.post("/discovery")
def run_discovery(body: DiscoveryRequest):
    """투자 아이디어 → 유망 종목 탐색 보고서 (SSE 스트리밍)."""
    idea = body.idea.strip()
    if not idea:
        raise HTTPException(status_code=400, detail="idea는 필수입니다")

    def event_stream():
        import json as _json
        captured = {"full_text": ""}
        for event in generate_discovery_stream(idea):
            yield event
            if event.startswith("data: "):
                try:
                    data = _json.loads(event[6:])
                    if data.get("type") == "complete":
                        captured["full_text"] = data.get("full_text", "")
                except Exception:
                    pass
        full_text = captured["full_text"]
        if full_text:
            try:
                db = SessionLocal()
                report = Report(ticker_id=None, type=ReportTypeEnum.DISCOVERY, content=full_text)
                db.add(report)
                db.commit()
                report_id = str(report.id)
                db.close()
                yield f"data: {_json.dumps({'type': 'saved', 'report_id': report_id})}\n\n"
                try:
                    notify_discovery_saved(report_id, idea[:80])
                except Exception:
                    pass
            except Exception:
                logger.exception("Discovery report DB 저장 실패")

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/portfolio-review")
def run_portfolio_review():
    """포트폴리오 전체 점검 보고서 (SSE 스트리밍)."""
    db = SessionLocal()
    try:
        portfolio_context = _build_portfolio_context(db)
    finally:
        db.close()

    if not portfolio_context:
        raise HTTPException(status_code=400, detail="포트폴리오 종목이 없습니다. KIS 동기화를 먼저 실행하세요.")

    def event_stream():
        import json as _json
        captured = {"full_text": ""}
        for event in generate_portfolio_review_stream(portfolio_context):
            yield event
            if event.startswith("data: "):
                try:
                    data = _json.loads(event[6:])
                    if data.get("type") == "complete":
                        captured["full_text"] = data.get("full_text", "")
                except Exception:
                    pass
        full_text = captured["full_text"]
        if full_text:
            try:
                _db = SessionLocal()
                report = Report(ticker_id=None, type=ReportTypeEnum.PORTFOLIO_REVIEW, content=full_text)
                _db.add(report)
                _db.commit()
                report_id = str(report.id)
                _db.close()
                yield f"data: {_json.dumps({'type': 'saved', 'report_id': report_id})}\n\n"
                try:
                    notify_portfolio_review_saved(report_id)
                except Exception:
                    pass
            except Exception:
                logger.exception("Portfolio review DB 저장 실패")

    return StreamingResponse(event_stream(), media_type="text/event-stream")


def _build_portfolio_context(db) -> str:
    """DB에서 포트폴리오 데이터를 조립해 프롬프트용 문자열로 반환."""
    from datetime import datetime

    tickers = (
        db.query(Ticker)
        .filter(Ticker.status == TickerStatusEnum.PORTFOLIO)
        .all()
    )
    if not tickers:
        return ""

    # 전체 포트폴리오 가치 계산 (USD 기준)
    total_value = 0.0
    holdings = []

    for t in tickers:
        p = t.portfolio
        if not p:
            continue
        market_value = (p.quantity or 0) * (p.current_price or 0)
        total_value += market_value

        # metrics 캐시
        metrics_row = (
            db.query(FinancialCache)
            .filter(FinancialCache.ticker_id == t.id, FinancialCache.data_type == "metrics")
            .first()
        )
        metrics = {}
        if metrics_row and metrics_row.expires_at > datetime.utcnow():
            raw = metrics_row.data
            metrics = raw[0] if isinstance(raw, list) and raw else (raw if isinstance(raw, dict) else {})

        holdings.append({
            "symbol": t.symbol,
            "name": t.name,
            "market": t.market.value,
            "quantity": p.quantity or 0,
            "avg_price": p.avg_price or 0,
            "current_price": p.current_price or 0,
            "daily_pct": p.daily_pct or 0,
            "market_value": market_value,
            "thesis": t.thesis,
            "metrics": metrics,
        })

    if not holdings:
        return ""

    # 비중 계산
    for h in holdings:
        h["weight"] = (h["market_value"] / total_value * 100) if total_value else 0
        avg = h["avg_price"]
        cur = h["current_price"]
        h["pnl_pct"] = ((cur - avg) / avg * 100) if avg else 0
        h["unrealized_pnl"] = (cur - avg) * h["quantity"]

    # 정렬: 비중 내림차순
    holdings.sort(key=lambda x: x["market_value"], reverse=True)

    def pct(v): return f"{v*100:.1f}%" if v is not None else "N/A"
    def x(v): return f"{v:.1f}x" if v is not None else "N/A"
    def sign(v): return f"+{v:.1f}%" if v >= 0 else f"{v:.1f}%"

    lines = [
        f"## 포트폴리오 현황 (총 {total_value:,.0f} USD 상당, {len(holdings)}종목)\n",
    ]

    for h in holdings:
        th = h["thesis"]
        thesis_status = th.confirmed.value if th else "없음"
        m = h["metrics"]

        lines.append(
            f"### {h['symbol']} — {h['name']} ({h['market']})\n"
            f"- 보유: {h['quantity']:.2f}주 | 평균단가: {h['avg_price']:.2f} | 현재가: {h['current_price']:.2f}\n"
            f"- 평가금액: {h['market_value']:,.0f} | 비중: {h['weight']:.1f}% | 평가손익: {sign(h['pnl_pct'])} ({h['unrealized_pnl']:+,.0f})\n"
            f"- 당일등락: {sign(h['daily_pct'])}\n"
            f"- Thesis 상태: {thesis_status}\n"
        )

        if th and th.thesis:
            lines.append(f"- Thesis 요약: {th.thesis[:300].strip()}{'...' if len(th.thesis) > 300 else ''}\n")
        if th and th.key_assumptions:
            lines.append(f"- Key Assumptions: {th.key_assumptions[:300].strip()}{'...' if len(th.key_assumptions) > 300 else ''}\n")

        if m:
            lines.append(
                f"- Key Metrics (TTM): P/E {x(m.get('price_to_earnings_ratio'))} | "
                f"EV/EBITDA {x(m.get('enterprise_value_to_ebitda_ratio'))} | "
                f"FCF Yield {pct(m.get('free_cash_flow_yield'))} | "
                f"ROE {pct(m.get('return_on_equity'))} | "
                f"ROIC {pct(m.get('return_on_invested_capital'))} | "
                f"Revenue Growth {pct(m.get('revenue_growth'))}\n"
            )
        lines.append("")

    return "\n".join(lines)


def _run_macro_report():
    db = SessionLocal()
    try:
        indicators = get_market_indicators()
        sections = generate_macro_report(indicators)
        report = Report(ticker_id=None, type=ReportTypeEnum.MACRO, content=sections["full_text"])
        db.add(report)
        db.commit()
        logger.info("Macro report saved")
        notify_macro_saved(str(report.id))
    except Exception:
        logger.exception("Macro report 생성 실패")
    finally:
        db.close()
