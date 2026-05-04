from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from models.db import get_db, HumanResponse, HumanResponseTypeEnum, HumanResponseTargetEnum

router = APIRouter()


class HumanResponseCreate(BaseModel):
    target_type: str
    target_id: str
    section_key: Optional[str] = None
    response_type: str
    content: str


class HumanResponseUpdate(BaseModel):
    response_type: Optional[str] = None
    content: Optional[str] = None


class HumanResponseOut(BaseModel):
    id: str
    target_type: str
    target_id: str
    section_key: Optional[str]
    response_type: str
    content: str
    recorded_at: str


def _to_out(r: HumanResponse) -> HumanResponseOut:
    return HumanResponseOut(
        id=str(r.id),
        target_type=r.target_type.value if hasattr(r.target_type, 'value') else r.target_type,
        target_id=str(r.target_id),
        section_key=r.section_key,
        response_type=r.response_type.value if hasattr(r.response_type, 'value') else r.response_type,
        content=r.content,
        recorded_at=r.recorded_at.isoformat(),
    )


@router.get("", response_model=list[HumanResponseOut])
def list_responses(
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    db: Session = Depends(get_db),
):
    q = db.query(HumanResponse)
    if target_type:
        q = q.filter(HumanResponse.target_type == target_type)
    if target_id:
        q = q.filter(HumanResponse.target_id == target_id)
    items = q.order_by(HumanResponse.recorded_at.desc()).all()
    return [_to_out(r) for r in items]


@router.post("", status_code=201, response_model=HumanResponseOut)
def create_response(body: HumanResponseCreate, db: Session = Depends(get_db)):
    if not body.content.strip():
        raise HTTPException(status_code=400, detail="content는 필수입니다")
    try:
        target_type = HumanResponseTargetEnum(body.target_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"알 수 없는 target_type: {body.target_type}")
    try:
        response_type = HumanResponseTypeEnum(body.response_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"알 수 없는 response_type: {body.response_type}")

    item = HumanResponse(
        target_type=target_type,
        target_id=body.target_id,
        section_key=body.section_key,
        response_type=response_type,
        content=body.content.strip(),
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return _to_out(item)


@router.patch("/{response_id}", response_model=HumanResponseOut)
def update_response(response_id: str, body: HumanResponseUpdate, db: Session = Depends(get_db)):
    item = db.query(HumanResponse).filter(HumanResponse.id == response_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="메모를 찾을 수 없습니다")
    if body.response_type is not None:
        try:
            item.response_type = HumanResponseTypeEnum(body.response_type)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"알 수 없는 response_type: {body.response_type}")
    if body.content is not None:
        if not body.content.strip():
            raise HTTPException(status_code=400, detail="content는 비울 수 없습니다")
        item.content = body.content.strip()
    db.commit()
    db.refresh(item)
    return _to_out(item)


@router.delete("/{response_id}", status_code=204)
def delete_response(response_id: str, db: Session = Depends(get_db)):
    item = db.query(HumanResponse).filter(HumanResponse.id == response_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="메모를 찾을 수 없습니다")
    db.delete(item)
    db.commit()
