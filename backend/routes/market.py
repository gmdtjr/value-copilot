import logging

from fastapi import APIRouter
from services.market_data import get_market_indicators

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/indicators")
def market_indicators():
    return get_market_indicators()
