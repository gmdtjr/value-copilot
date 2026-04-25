import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from models.db import Base, engine
from routes.tickers import router as tickers_router
from routes.thesis import router as thesis_router
from routes.reports import router as reports_router
from routes.portfolio import router as portfolio_router
from routes.market import router as market_router
from routes.settings import router as settings_router
from routes.tradelog import router as tradelog_router
from routes.ideas import router as ideas_router

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s — %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Value Copilot API",
    description="가치투자 AI 코파일럿 — Human-in-the-loop 구조",
    version="0.1.0",
)

import os as _os
_CORS_ORIGINS = [
    "http://localhost:5173", "http://127.0.0.1:5173",
    "http://3.26.145.173",
]
if _extra := _os.environ.get("CORS_ORIGIN"):
    _CORS_ORIGINS.append(_extra)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(tickers_router, prefix="/api/tickers", tags=["tickers"])
app.include_router(thesis_router, prefix="/api/thesis", tags=["thesis"])
app.include_router(reports_router, prefix="/api/reports", tags=["reports"])
app.include_router(portfolio_router, prefix="/api/portfolio", tags=["portfolio"])
app.include_router(market_router, prefix="/api/market", tags=["market"])
app.include_router(settings_router, prefix="/api/settings", tags=["settings"])
app.include_router(tradelog_router, prefix="/api/tradelog", tags=["tradelog"])
app.include_router(ideas_router, prefix="/api/ideas", tags=["ideas"])


@app.on_event("startup")
async def startup():
    from sqlalchemy import text as _text
    # create_all 먼저 실행 → enum 타입 생성
    Base.metadata.create_all(bind=engine)
    # 이후 신규 enum 값 추가 (기존 DB 마이그레이션용, 신규 DB는 no-op)
    with engine.connect() as conn:
        for _old, _new in (
            ("ANALYSIS", "analysis"),
            ("DAILY_BRIEF", "daily_brief"),
            ("MACRO", "macro"),
        ):
            conn.execute(_text(
                f"DO $$ BEGIN "
                f"IF EXISTS (SELECT 1 FROM pg_enum WHERE enumlabel='{_old}' "
                f"AND enumtypid=(SELECT oid FROM pg_type WHERE typname='reporttypeenum')) "
                f"THEN ALTER TYPE reporttypeenum RENAME VALUE '{_old}' TO '{_new}'; END IF; END $$;"
            ))
        for _val in ("discovery", "portfolio_review"):
            conn.execute(_text(
                f"DO $$ BEGIN "
                f"IF NOT EXISTS (SELECT 1 FROM pg_enum WHERE enumlabel='{_val}' "
                f"AND enumtypid=(SELECT oid FROM pg_type WHERE typname='reporttypeenum')) "
                f"THEN ALTER TYPE reporttypeenum ADD VALUE '{_val}'; END IF; END $$;"
            ))
        # is_read 컬럼 (Report 테이블)
        conn.execute(_text(
            "ALTER TABLE reports ADD COLUMN IF NOT EXISTS is_read BOOLEAN NOT NULL DEFAULT FALSE;"
        ))
        # report_comments 테이블 (create_all로 생성되지만 기존 DB에도 안전)
        conn.execute(_text("""
            CREATE TABLE IF NOT EXISTS report_comments (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                report_id UUID NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT now()
            );
        """))
        # trade_logs 테이블
        conn.execute(_text("""
            DO $$ BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname='tradeactionenum') THEN
                    CREATE TYPE tradeactionenum AS ENUM ('buy', 'sell', 'add', 'reduce');
                END IF;
            END $$;
        """))
        conn.execute(_text("""
            CREATE TABLE IF NOT EXISTS trade_logs (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                ticker_id UUID REFERENCES tickers(id) ON DELETE SET NULL,
                symbol VARCHAR(20) NOT NULL,
                name VARCHAR(200) NOT NULL,
                action tradeactionenum NOT NULL,
                quantity_before FLOAT NOT NULL DEFAULT 0,
                quantity_after FLOAT NOT NULL DEFAULT 0,
                avg_price_before FLOAT NOT NULL DEFAULT 0,
                avg_price_after FLOAT NOT NULL DEFAULT 0,
                note TEXT,
                detected_at TIMESTAMP DEFAULT now(),
                noted_at TIMESTAMP
            );
        """))
        # idea_memos 테이블
        conn.execute(_text("""
            CREATE TABLE IF NOT EXISTS idea_memos (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                content TEXT NOT NULL,
                ticker_symbol VARCHAR(20),
                created_at TIMESTAMP DEFAULT now(),
                updated_at TIMESTAMP DEFAULT now()
            );
        """))
        # stock_type / seed_memo 컬럼 (Thesis)
        conn.execute(_text(
            "ALTER TABLE theses ADD COLUMN IF NOT EXISTS stock_type VARCHAR(50);"
        ))
        conn.execute(_text(
            "ALTER TABLE theses ADD COLUMN IF NOT EXISTS seed_memo TEXT;"
        ))
        conn.commit()
    logger.info("DB tables ready")
    from services.telegram_bot import start_bot
    await start_bot()
    from services.scheduler import start_scheduler
    start_scheduler()


@app.on_event("shutdown")
async def shutdown():
    from services.telegram_bot import stop_bot
    await stop_bot()
    from services.scheduler import stop_scheduler
    stop_scheduler()


@app.get("/health")
async def health():
    return {"status": "ok"}
