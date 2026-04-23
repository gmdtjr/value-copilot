import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from models.db import get_db, IdeaMemo

logger = logging.getLogger(__name__)
router = APIRouter()


class IdeaMemoResponse(BaseModel):
    id: str
    content: str
    ticker_symbol: Optional[str]
    created_at: str
    updated_at: str


class CreateBody(BaseModel):
    content: str
    ticker_symbol: Optional[str] = None


class UpdateBody(BaseModel):
    content: str
    ticker_symbol: Optional[str] = None


@router.get("", response_model=list[IdeaMemoResponse])
def list_ideas(db: Session = Depends(get_db), limit: int = 200):
    memos = (
        db.query(IdeaMemo)
        .order_by(IdeaMemo.created_at.desc())
        .limit(limit)
        .all()
    )
    return [_to_response(m) for m in memos]


@router.post("", response_model=IdeaMemoResponse, status_code=201)
def create_idea(body: CreateBody, db: Session = Depends(get_db)):
    memo = IdeaMemo(
        content=body.content.strip(),
        ticker_symbol=body.ticker_symbol.strip().upper() if body.ticker_symbol else None,
    )
    db.add(memo)
    db.commit()
    db.refresh(memo)
    return _to_response(memo)


@router.patch("/{memo_id}", response_model=IdeaMemoResponse)
def update_idea(memo_id: str, body: UpdateBody, db: Session = Depends(get_db)):
    memo = db.query(IdeaMemo).filter(IdeaMemo.id == memo_id).first()
    if not memo:
        raise HTTPException(status_code=404, detail="메모를 찾을 수 없습니다")
    memo.content = body.content.strip()
    memo.ticker_symbol = body.ticker_symbol.strip().upper() if body.ticker_symbol else None
    memo.updated_at = datetime.utcnow()
    db.commit()
    return _to_response(memo)


@router.delete("/{memo_id}", status_code=204)
def delete_idea(memo_id: str, db: Session = Depends(get_db)):
    memo = db.query(IdeaMemo).filter(IdeaMemo.id == memo_id).first()
    if not memo:
        raise HTTPException(status_code=404, detail="메모를 찾을 수 없습니다")
    db.delete(memo)
    db.commit()


def _to_response(m: IdeaMemo) -> IdeaMemoResponse:
    return IdeaMemoResponse(
        id=str(m.id),
        content=m.content,
        ticker_symbol=m.ticker_symbol,
        created_at=m.created_at.isoformat(),
        updated_at=m.updated_at.isoformat(),
    )
