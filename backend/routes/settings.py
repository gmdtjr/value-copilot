import os
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from models.db import get_db, Settings

router = APIRouter()

_DEFAULTS = {
    "us_data_source": "yfinance",  # "yfinance" | "financialdatasets"
}


@router.get("")
def get_settings(db: Session = Depends(get_db)):
    rows = db.query(Settings).all()
    result = dict(_DEFAULTS)
    for row in rows:
        result[row.key] = row.value
    return result


@router.get("/system-info")
def get_system_info():
    """환경변수 설정 여부 및 파이프라인 구성 반환."""
    return {
        "has_anthropic_key":           bool(os.environ.get("ANTHROPIC_API_KEY")),
        "has_financial_datasets_key":  bool(os.environ.get("FINANCIAL_DATASETS_API_KEY")),
        "has_opendart_key":            bool(os.environ.get("OPENDART_API_KEY")),
        "has_naver_client_id":         bool(os.environ.get("NAVER_CLIENT_ID")),
        "has_kis_key":                 bool(os.environ.get("KIS_APP_KEY")),
    }


class SettingValue(BaseModel):
    value: str


@router.put("/{key}")
def update_setting(key: str, body: SettingValue, db: Session = Depends(get_db)):
    if key not in _DEFAULTS:
        raise HTTPException(status_code=400, detail=f"Unknown setting: {key}")
    row = db.query(Settings).filter(Settings.key == key).first()
    if row:
        row.value = body.value
    else:
        db.add(Settings(key=key, value=body.value))
    db.commit()
    return {"key": key, "value": body.value}
