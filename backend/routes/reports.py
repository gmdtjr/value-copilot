import logging
from typing import Optional

from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from models.db import get_db, Report, ReportComment, Ticker, ReportTypeEnum, SessionLocal, TickerStatusEnum
from services.agent import generate_macro_report
from services.market_data import get_market_indicators
from services.telegram import notify_macro_saved

logger = logging.getLogger(__name__)
router = APIRouter()


class MarkReadBody(BaseModel):
    is_read: bool


class CommentBody(BaseModel):
    content: str


class ReportResponse(BaseModel):
    id: str
    ticker_id: Optional[str]
    ticker_symbol: Optional[str]
    ticker_name: Optional[str]
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
    ticker_rows = db.query(Ticker).filter(Ticker.id.in_(ticker_ids)).all()
    tickers = {t.id: t.symbol for t in ticker_rows}
    ticker_names = {t.id: t.name for t in ticker_rows}

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
            ticker_name=ticker_names.get(r.ticker_id) if r.ticker_id else None,
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
    ticker_name = report.ticker.name if report.ticker_id and report.ticker else None
    comment_count = db.query(func.count(ReportComment.id)).filter(ReportComment.report_id == report.id).scalar()
    return ReportResponse(
        id=str(report.id),
        ticker_id=str(report.ticker_id) if report.ticker_id else None,
        ticker_symbol=ticker_symbol,
        ticker_name=ticker_name,
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


@router.get("/explore-prompt")
def get_explore_prompt(type: str = "discovery", db: Session = Depends(get_db)):
    """외부 Claude 탐색에 붙여넣을 프롬프트 텍스트 반환."""
    try:
        if type == "discovery":
            return {"prompt": _build_discovery_prompt(db)}
        elif type == "portfolio_review":
            return {"prompt": _build_portfolio_prompt(db)}
        else:
            raise HTTPException(status_code=400, detail=f"알 수 없는 type: {type}")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("explore-prompt 생성 실패: type=%s", type)
        raise HTTPException(status_code=500, detail=f"프롬프트 생성 오류: {str(e)}")


def _build_discovery_prompt(db) -> str:
    """현재 포트폴리오/관심 종목을 컨텍스트로 포함한 종목 탐색 프롬프트."""
    from datetime import datetime

    from sqlalchemy.orm import selectinload
    tickers = db.query(Ticker).options(selectinload(Ticker.theses)).all()
    portfolio = [t for t in tickers if t.status == TickerStatusEnum.PORTFOLIO]
    watchlist = [t for t in tickers if t.status == TickerStatusEnum.WATCHLIST]

    lines = [
        "당신은 가치투자 전문가입니다. 아래 현재 포트폴리오와 관심 종목을 참고하여 새로운 투자 아이디어를 탐색해주세요.",
        "",
        "## 현재 포트폴리오",
    ]
    if portfolio:
        for t in portfolio:
            thesis_line = ""
            if t.thesis:
                st = t.thesis.stock_type or "미분류"
                thesis_line = f" | {st}"
                if t.thesis.key_assumptions:
                    thesis_line += f" | 핵심가정: {t.thesis.key_assumptions[:80].strip()}"
            lines.append(f"- {t.name} ({t.symbol}, {t.market.value}){thesis_line}")
    else:
        lines.append("- (없음)")

    lines.extend(["", "## 현재 관심 목록"])
    if watchlist:
        for t in watchlist:
            st = (t.thesis.stock_type or "") if t.thesis else ""
            lines.append(f"- {t.name} ({t.symbol}, {t.market.value}){' | ' + st if st else ''}")
    else:
        lines.append("- (없음)")

    lines.extend([
        "",
        "## 탐색 요청",
        "위 포트폴리오와 겹치지 않으면서, 가치투자 관점에서 매력적인 새 종목을 탐색해주세요.",
        "",
        "다음 중 하나 이상의 렌즈로 접근해주세요:",
        "- Compounding: ROIC 15%+ 지속, 재투자 기회 존재",
        "- Growth: 매출 CAGR 20%+, TAM 초기 침투",
        "- Asset Play: P/B 할인, 명확한 촉매 이벤트",
        "- Turnaround: 구조조정 진행 중, Cash runway 충분",
        "- Cyclical: 사이클 저점 근처, 부채 낮음",
        "- Special Situation: M&A, 스핀오프, 규제 변화",
        "",
        "각 추천 종목에 대해:",
        "1. 왜 지금 매력적인가 (핵심 논리 2~3문장)",
        "2. 핵심 리스크",
        "3. 무엇이 바뀌면 thesis가 깨지는가",
        "",
        "미국 종목 3~5개, 한국 종목 2~3개를 추천해주세요.",
    ])

    return "\n".join(lines)


def _build_portfolio_prompt(db) -> str:
    """현재 포트폴리오를 컨텍스트로 포함한 포트폴리오 점검 프롬프트."""
    from datetime import datetime

    from sqlalchemy.orm import selectinload
    tickers = (
        db.query(Ticker)
        .options(selectinload(Ticker.theses))
        .filter(Ticker.status == TickerStatusEnum.PORTFOLIO)
        .all()
    )

    lines = [
        "당신은 가치투자 전문가입니다. 아래 포트폴리오를 점검해주세요.",
        "",
        "## 포트폴리오 현황",
    ]

    if not tickers:
        lines.append("- (포트폴리오 없음)")
    else:
        for t in tickers:
            p = t.portfolio
            price_line = ""
            if p:
                if p.current_price and p.avg_price:
                    pnl = (p.current_price - p.avg_price) / p.avg_price * 100 if p.avg_price else 0
                    price_line = f" | 평균단가 {p.avg_price:.2f} / 현재가 {p.current_price:.2f} ({pnl:+.1f}%)"
                if p.daily_pct:
                    price_line += f" | 당일 {p.daily_pct:+.1f}%"

            thesis_section = ""
            if t.thesis:
                st = t.thesis.stock_type or "미분류"
                status = t.thesis.confirmed.value
                thesis_section = f"\n  - 유형: {st} | 상태: {status}"
                if t.thesis.key_logic:
                    thesis_section += f"\n  - 핵심 논리: {t.thesis.key_logic[:200].strip()}"
                elif t.thesis.key_assumptions:
                    thesis_section += f"\n  - 핵심가정: {t.thesis.key_assumptions[:150].strip()}"
                if t.thesis.risk:
                    thesis_section += f"\n  - 리스크: {t.thesis.risk[:100].strip()}"

            lines.append(f"- **{t.name}** ({t.symbol}, {t.market.value}){price_line}{thesis_section}")
            lines.append("")

    lines.extend([
        "## 점검 요청",
        "",
        "1. **포트폴리오 전체 관점**: 집중도, 상관관계, 시장 환경 적합성",
        "2. **종목별 thesis 건전성**: 각 종목의 핵심가정이 여전히 유효한가",
        "3. **행동 필요 항목**: 추가 조사가 필요하거나 비중 재검토가 필요한 종목",
        "4. **전략적 관점**: 현재 시장 환경에서 포트폴리오의 취약점과 기회",
        "",
        "특정 투자 결정을 내리지 말고, 사고의 방향을 제시해주세요.",
    ])

    return "\n".join(lines)


@router.post("/macro/trigger", status_code=202)
def trigger_macro_report(background_tasks: BackgroundTasks):
    background_tasks.add_task(_run_macro_report)
    return {"message": "매크로 보고서 생성 시작됨"}


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
