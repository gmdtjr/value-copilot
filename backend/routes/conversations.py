from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from models.db import get_db, ConversationImport, ConversationImportTypeEnum, Ticker

router = APIRouter()


class ConversationImportCreate(BaseModel):
    import_type: str
    summary: str
    raw_excerpt: Optional[str] = None
    ticker_id: Optional[str] = None


class ConversationImportUpdate(BaseModel):
    summary: Optional[str] = None
    raw_excerpt: Optional[str] = None


class ConversationImportResponse(BaseModel):
    id: str
    ticker_id: Optional[str]
    ticker_symbol: Optional[str]
    ticker_name: Optional[str]
    import_type: str
    summary: str
    raw_excerpt: Optional[str]
    created_at: str


def _to_response(c: ConversationImport) -> ConversationImportResponse:
    return ConversationImportResponse(
        id=str(c.id),
        ticker_id=str(c.ticker_id) if c.ticker_id else None,
        ticker_symbol=c.ticker.symbol if c.ticker else None,
        ticker_name=c.ticker.name if c.ticker else None,
        import_type=c.import_type.value if hasattr(c.import_type, 'value') else c.import_type,
        summary=c.summary,
        raw_excerpt=c.raw_excerpt,
        created_at=c.created_at.isoformat(),
    )


@router.get("", response_model=list[ConversationImportResponse])
def list_imports(
    db: Session = Depends(get_db),
    ticker_id: Optional[str] = None,
    limit: int = 100,
):
    q = db.query(ConversationImport)
    if ticker_id:
        q = q.filter(ConversationImport.ticker_id == ticker_id)
    items = q.order_by(ConversationImport.created_at.desc()).limit(limit).all()
    return [_to_response(c) for c in items]


@router.post("", status_code=201, response_model=ConversationImportResponse)
def create_import(body: ConversationImportCreate, db: Session = Depends(get_db)):
    if not body.summary.strip():
        raise HTTPException(status_code=400, detail="summary는 필수입니다")
    try:
        import_type = ConversationImportTypeEnum(body.import_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"알 수 없는 import_type: {body.import_type}")

    ticker_id = None
    if body.ticker_id:
        ticker = db.query(Ticker).filter(Ticker.id == body.ticker_id).first()
        if not ticker:
            raise HTTPException(status_code=404, detail="종목을 찾을 수 없습니다")
        ticker_id = ticker.id

    item = ConversationImport(
        ticker_id=ticker_id,
        import_type=import_type,
        summary=body.summary.strip(),
        raw_excerpt=body.raw_excerpt.strip() if body.raw_excerpt else None,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return _to_response(item)


@router.patch("/{item_id}", response_model=ConversationImportResponse)
def update_import(item_id: str, body: ConversationImportUpdate, db: Session = Depends(get_db)):
    item = db.query(ConversationImport).filter(ConversationImport.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="탐색 결과를 찾을 수 없습니다")
    if body.summary is not None:
        item.summary = body.summary.strip()
    if body.raw_excerpt is not None:
        item.raw_excerpt = body.raw_excerpt.strip() or None
    db.commit()
    db.refresh(item)
    return _to_response(item)


@router.delete("/{item_id}", status_code=204)
def delete_import(item_id: str, db: Session = Depends(get_db)):
    item = db.query(ConversationImport).filter(ConversationImport.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="탐색 결과를 찾을 수 없습니다")
    db.delete(item)
    db.commit()
