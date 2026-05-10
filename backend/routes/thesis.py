import logging
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from models.db import get_db, Thesis, Ticker, ThesisStatusEnum
from services.telegram import notify_thesis_confirmed

logger = logging.getLogger(__name__)
router = APIRouter()


def _active_thesis(db: Session, ticker_id) -> Optional[Thesis]:
    """Returns the latest non-retired thesis. Falls back to simple query for pre-Phase2 DBs."""
    try:
        return (
            db.query(Thesis)
            .filter(Thesis.ticker_id == ticker_id, Thesis.confirmed != ThesisStatusEnum.RETIRED)
            .order_by(Thesis.version_number.desc().nullslast())
            .first()
        )
    except Exception:
        db.rollback()  # PG 트랜잭션 abort 상태 리셋
        return db.query(Thesis).filter(Thesis.ticker_id == ticker_id).first()


class ThesisResponse(BaseModel):
    id: str
    ticker_id: str
    confirmed: str
    confirmed_at: Optional[str]
    thesis: Optional[str]
    risk: Optional[str]
    key_assumptions: Optional[str]
    valuation: Optional[str]
    last_analyzed_at: Optional[str]
    stock_type: Optional[str]
    seed_memo: Optional[str]
    # Phase 2
    version_number: int = 1
    parent_version_id: Optional[str] = None
    key_logic: Optional[str] = None
    monitoring_contract: Optional[str] = None
    exploration_note: Optional[str] = None
    retired_at: Optional[str] = None
    retirement_reason: Optional[str] = None


class ThesisPatch(BaseModel):
    thesis: Optional[str] = None
    risk: Optional[str] = None
    key_assumptions: Optional[str] = None
    valuation: Optional[str] = None
    key_logic: Optional[str] = None
    monitoring_contract: Optional[str] = None
    exploration_note: Optional[str] = None


class ConfirmBody(BaseModel):
    key_logic: Optional[str] = None  # legacy fallback. 새 workflow에서는 monitoring_contract 사용.
    monitoring_contract: Optional[str] = None


@router.get("/{ticker_id}", response_model=ThesisResponse)
def get_thesis(ticker_id: str, db: Session = Depends(get_db)):
    thesis = _active_thesis(db, ticker_id)
    if not thesis:
        raise HTTPException(status_code=404, detail="Thesis not found")
    return _to_response(thesis)


@router.get("/{ticker_id}/versions", response_model=list[ThesisResponse])
def get_thesis_versions(ticker_id: str, db: Session = Depends(get_db)):
    """모든 버전 반환 (retired 포함, version_number 내림차순)."""
    versions = (
        db.query(Thesis)
        .filter(Thesis.ticker_id == ticker_id)
        .order_by(Thesis.version_number.desc().nullslast())
        .all()
    )
    return [_to_response(v) for v in versions]


@router.patch("/{ticker_id}", response_model=ThesisResponse)
def patch_thesis(ticker_id: str, body: ThesisPatch, db: Session = Depends(get_db)):
    """사람이 thesis 내용을 직접 편집. draft/needs_review 상태에서만 허용."""
    thesis = _active_thesis(db, ticker_id)
    if not thesis:
        raise HTTPException(status_code=404, detail="Thesis not found")
    if thesis.confirmed == ThesisStatusEnum.CONFIRMED:
        raise HTTPException(status_code=400, detail="Confirmed thesis는 직접 수정할 수 없습니다. 새 버전을 만든 뒤 수정하세요.")

    for field, value in body.model_dump(exclude_none=True).items():
        setattr(thesis, field, value)
    db.commit()
    db.refresh(thesis)
    return _to_response(thesis)


@router.post("/{ticker_id}/confirm", response_model=ThesisResponse)
def confirm_thesis(ticker_id: str, body: ConfirmBody = ConfirmBody(), db: Session = Depends(get_db)):
    """사람이 confirmed 버튼을 눌러 상태 전환. AI가 임의로 호출 불가."""
    thesis = _active_thesis(db, ticker_id)
    if not thesis:
        raise HTTPException(status_code=404, detail="Thesis not found")
    if not thesis.thesis:
        raise HTTPException(status_code=400, detail="Thesis 내용이 없습니다. 'Thesis 작성' 버튼으로 내용을 입력하세요.")

    # Monitoring Contract가 새 framework의 confirm 기준이다.
    # key_logic은 기존 confirmed thesis 호환용 fallback으로만 유지한다.
    if body.key_logic and body.key_logic.strip():
        thesis.key_logic = body.key_logic.strip()
    if body.monitoring_contract and body.monitoring_contract.strip():
        thesis.monitoring_contract = body.monitoring_contract.strip()

    # monitoring_contract가 있으면 Break Monitor의 1차 기준, 없으면 key_logic으로 호환
    current_contract = getattr(thesis, 'monitoring_contract', None)
    if current_contract and not current_contract.strip():
        current_contract = None
    current_key_logic = getattr(thesis, 'key_logic', None)
    if current_key_logic and not current_key_logic.strip():
        current_key_logic = None
    if not current_contract and not current_key_logic:
        raise HTTPException(
            status_code=400,
            detail="Monitoring Contract가 필요합니다. Break Monitor가 감시할 Core Logic, Break Conditions, Strengthening Signals, Watch Metrics를 입력하세요."
        )

    # 이전의 confirmed/needs_review 버전 retire (Phase 2 DB에서만 동작)
    version_number = getattr(thesis, 'version_number', 1) or 1
    if version_number > 1:
        try:
            older_versions = (
                db.query(Thesis)
                .filter(
                    Thesis.ticker_id == thesis.ticker_id,
                    Thesis.id != thesis.id,
                    Thesis.confirmed != ThesisStatusEnum.RETIRED,
                )
                .all()
            )
            for old in older_versions:
                old.confirmed = ThesisStatusEnum.RETIRED
                old.retired_at = datetime.utcnow()
                old.retirement_reason = "superseded"
        except Exception:
            db.rollback()  # PG abort 상태 리셋 후 계속 진행

    thesis.confirmed = ThesisStatusEnum.CONFIRMED
    thesis.confirmed_at = datetime.utcnow()
    db.commit()
    db.refresh(thesis)
    logger.info("Thesis confirmed for ticker_id=%s (v%s)", ticker_id, thesis.version_number)

    ticker = db.query(Ticker).filter(Ticker.id == thesis.ticker_id).first()
    if ticker:
        notify_thesis_confirmed(ticker.symbol, ticker.name, ticker.market.value)

    return _to_response(thesis)


@router.post("/{ticker_id}/new-version", response_model=ThesisResponse)
def create_new_version(ticker_id: str, db: Session = Depends(get_db)):
    """현재 confirmed thesis를 기반으로 새 draft 버전 생성. 사람이 직접 편집을 원할 때 사용."""
    current = _active_thesis(db, ticker_id)
    if not current:
        raise HTTPException(status_code=404, detail="Active thesis not found")
    if current.confirmed != ThesisStatusEnum.CONFIRMED:
        raise HTTPException(status_code=400, detail="새 버전 생성은 confirmed 상태에서만 가능합니다.")

    new_v = current.version_number + 1
    new_thesis = Thesis(
        ticker_id=current.ticker_id,
        version_number=new_v,
        parent_version_id=current.id,
        confirmed=ThesisStatusEnum.DRAFT,
        thesis=current.thesis,
        risk=current.risk,
        key_assumptions=current.key_assumptions,
        valuation=current.valuation,
        stock_type=current.stock_type,
        seed_memo=current.seed_memo,
        exploration_note=current.exploration_note,
        key_logic=current.key_logic,
        monitoring_contract=getattr(current, 'monitoring_contract', None),
    )
    db.add(new_thesis)
    db.commit()
    db.refresh(new_thesis)
    logger.info("New thesis version v%s created for ticker_id=%s", new_v, ticker_id)
    return _to_response(new_thesis)


@router.delete("/versions/{thesis_id}", status_code=204)
def delete_thesis_version(thesis_id: str, db: Session = Depends(get_db)):
    """특정 thesis 버전 삭제. draft/needs_review/retired 모두 가능.
    confirmed 버전은 해당 ticker의 유일한 active thesis인 경우 삭제 불가."""
    thesis = db.query(Thesis).filter(Thesis.id == thesis_id).first()
    if not thesis:
        raise HTTPException(status_code=404, detail="Thesis not found")

    # confirmed 상태이고 다른 non-retired 버전이 없으면 삭제 불가
    if thesis.confirmed == ThesisStatusEnum.CONFIRMED:
        other_active = (
            db.query(Thesis)
            .filter(
                Thesis.ticker_id == thesis.ticker_id,
                Thesis.id != thesis.id,
                Thesis.confirmed != ThesisStatusEnum.RETIRED,
            )
            .first()
        )
        if not other_active:
            raise HTTPException(
                status_code=400,
                detail="현재 유일한 confirmed thesis는 삭제할 수 없습니다. 새 버전을 만들어 Confirm한 후 삭제하거나, 종목 삭제를 사용하세요."
            )

    # FK 제약이 DB 레벨에 미적용됐을 가능성 — 명시적 선행 처리
    try:
        from models.db import BreakSignal, InvestmentCycle
        db.query(BreakSignal).filter(BreakSignal.thesis_id == thesis.id).delete(synchronize_session=False)
        db.query(InvestmentCycle).filter(InvestmentCycle.thesis_id == thesis.id).update(
            {"thesis_id": None}, synchronize_session=False
        )
        db.delete(thesis)
        db.commit()
        logger.info("Thesis version deleted: thesis_id=%s", thesis_id)
    except Exception as e:
        db.rollback()
        logger.exception("Thesis version delete failed: %s", thesis_id)
        raise HTTPException(status_code=500, detail=f"삭제 실패: {str(e)}")


def _to_response(thesis: Thesis) -> ThesisResponse:
    return ThesisResponse(
        id=str(thesis.id),
        ticker_id=str(thesis.ticker_id),
        confirmed=thesis.confirmed.value,
        confirmed_at=thesis.confirmed_at.isoformat() if thesis.confirmed_at else None,
        thesis=thesis.thesis,
        risk=thesis.risk,
        key_assumptions=thesis.key_assumptions,
        valuation=thesis.valuation,
        last_analyzed_at=thesis.last_analyzed_at.isoformat() if thesis.last_analyzed_at else None,
        stock_type=thesis.stock_type.value if thesis.stock_type else None,
        seed_memo=thesis.seed_memo,
        version_number=thesis.version_number or 1,
        parent_version_id=str(thesis.parent_version_id) if thesis.parent_version_id else None,
        key_logic=thesis.key_logic,
        monitoring_contract=getattr(thesis, 'monitoring_contract', None),
        exploration_note=thesis.exploration_note,
        retired_at=thesis.retired_at.isoformat() if thesis.retired_at else None,
        retirement_reason=thesis.retirement_reason,
    )
