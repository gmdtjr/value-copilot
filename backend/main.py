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
from routes.conversations import router as conversations_router
from routes.human_responses import router as human_responses_router
from routes.break_signals import router as break_signals_router
from routes.cycles import router as cycles_router
from routes.retrospectives import router as retrospectives_router

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
app.include_router(conversations_router, prefix="/api/conversations", tags=["conversations"])
app.include_router(human_responses_router, prefix="/api/human-responses", tags=["human_responses"])
app.include_router(break_signals_router, prefix="/api/break-signals", tags=["break_signals"])
app.include_router(cycles_router, prefix="/api/cycles", tags=["cycles"])
app.include_router(retrospectives_router, prefix="/api/retrospectives", tags=["retrospectives"])


@app.on_event("startup")
async def startup():
    from sqlalchemy import text as _text
    # create_all 먼저 실행 → enum 타입 생성
    Base.metadata.create_all(bind=engine)

    # ALTER TYPE ... ADD VALUE 는 트랜잭션 블록 안에서 실행 불가 → AUTOCOMMIT 연결로 분리
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as _ac:
        # reporttypeenum 값 이름 변경 (ANALYSIS→analysis 등)
        for _old, _new in (
            ("ANALYSIS", "analysis"),
            ("DAILY_BRIEF", "daily_brief"),
            ("MACRO", "macro"),
        ):
            try:
                _ac.execute(_text(
                    f"DO $$ BEGIN "
                    f"IF EXISTS (SELECT 1 FROM pg_enum WHERE enumlabel='{_old}' "
                    f"AND enumtypid=(SELECT oid FROM pg_type WHERE typname='reporttypeenum')) "
                    f"THEN ALTER TYPE reporttypeenum RENAME VALUE '{_old}' TO '{_new}'; END IF; END $$;"
                ))
            except Exception:
                pass
        # reporttypeenum 신규 값 추가
        for _val in ("discovery", "portfolio_review"):
            try:
                _ac.execute(_text(
                    f"ALTER TYPE reporttypeenum ADD VALUE IF NOT EXISTS '{_val}';"
                ))
            except Exception:
                pass
        # Phase 2: thesisstatusenum 에 retired 추가 (소문자 — _pg_enum values 기준)
        try:
            _ac.execute(_text(
                "ALTER TYPE thesisstatusenum ADD VALUE IF NOT EXISTS 'retired';"
            ))
        except Exception:
            pass
        try:
            _ac.execute(_text(
                "ALTER TYPE verdictenum ADD VALUE IF NOT EXISTS 'strengthening';"
            ))
        except Exception:
            pass

    # 나머지 DDL (컬럼 추가 등) — 일반 트랜잭션으로
    with engine.connect() as conn:
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
        # Phase 2: theses.ticker_id unique 제약 제거 (다중 버전 허용)
        conn.execute(_text(
            "DO $$ BEGIN "
            "IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname='theses_ticker_id_key') "
            "THEN ALTER TABLE theses DROP CONSTRAINT theses_ticker_id_key; END IF; END $$;"
        ))
        # Phase 2: theses 신규 컬럼
        conn.execute(_text("ALTER TABLE theses ADD COLUMN IF NOT EXISTS version_number INTEGER NOT NULL DEFAULT 1;"))
        conn.execute(_text("ALTER TABLE theses ADD COLUMN IF NOT EXISTS parent_version_id UUID;"))
        conn.execute(_text("ALTER TABLE theses ADD COLUMN IF NOT EXISTS exploration_note TEXT;"))
        conn.execute(_text("ALTER TABLE theses ADD COLUMN IF NOT EXISTS key_logic TEXT;"))
        conn.execute(_text("ALTER TABLE theses ADD COLUMN IF NOT EXISTS monitoring_contract TEXT;"))
        conn.execute(_text("ALTER TABLE theses ADD COLUMN IF NOT EXISTS retired_at TIMESTAMP;"))
        conn.execute(_text("ALTER TABLE theses ADD COLUMN IF NOT EXISTS retirement_reason VARCHAR(50);"))
        # Phase 2: 기존 thesis에 version_number=1 백필 (커밋 분리 — 앞 DDL 실패와 무관하게 실행)
        conn.commit()
        conn.execute(_text("UPDATE theses SET version_number = 1 WHERE version_number IS NULL OR version_number = 0;"))
        conn.commit()
        # Phase 4: investment_cycles 테이블
        conn.execute(_text("""
            CREATE TABLE IF NOT EXISTS investment_cycles (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                ticker_id UUID NOT NULL REFERENCES tickers(id) ON DELETE CASCADE,
                thesis_id UUID REFERENCES theses(id) ON DELETE SET NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'open',
                opened_at TIMESTAMP NOT NULL,
                closed_at TIMESTAMP,
                exit_reason VARCHAR(30),
                exit_reason_note TEXT,
                pnl_pct FLOAT
            );
        """))
        # Phase 4: retrospectives 테이블
        conn.execute(_text("""
            CREATE TABLE IF NOT EXISTS retrospectives (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                cycle_id UUID NOT NULL UNIQUE REFERENCES investment_cycles(id) ON DELETE CASCADE,
                is_draft BOOLEAN NOT NULL DEFAULT TRUE,
                original_logic TEXT NOT NULL,
                what_changed TEXT,
                logic_held BOOLEAN,
                weak_link TEXT,
                if_wrong_why TEXT,
                if_right_why TEXT,
                next_time TEXT,
                completed_at TIMESTAMP
            );
        """))
        # Phase 4: trade_logs에 cycle_id 추가
        conn.execute(_text(
            "ALTER TABLE trade_logs ADD COLUMN IF NOT EXISTS cycle_id UUID REFERENCES investment_cycles(id) ON DELETE SET NULL;"
        ))
        # Phase 3: break_signals 테이블
        conn.execute(_text("""
            CREATE TABLE IF NOT EXISTS break_signals (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                thesis_id UUID NOT NULL REFERENCES theses(id) ON DELETE CASCADE,
                checked_at TIMESTAMP DEFAULT now(),
                key_logic_snapshot TEXT,
                observations TEXT NOT NULL,
                positive_signals TEXT,
                negative_signals TEXT,
                watch_items TEXT,
                verdict VARCHAR(20),
                human_note TEXT,
                reviewed_at TIMESTAMP
            );
        """))
        conn.execute(_text("ALTER TABLE break_signals ADD COLUMN IF NOT EXISTS positive_signals TEXT;"))
        conn.execute(_text("ALTER TABLE break_signals ADD COLUMN IF NOT EXISTS negative_signals TEXT;"))
        # conversation_imports 테이블
        conn.execute(_text("""
            CREATE TABLE IF NOT EXISTS conversation_imports (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                ticker_id UUID REFERENCES tickers(id) ON DELETE SET NULL,
                import_type VARCHAR(50) NOT NULL,
                summary TEXT NOT NULL,
                raw_excerpt TEXT,
                created_at TIMESTAMP DEFAULT now()
            );
        """))
        # human_responses 테이블
        conn.execute(_text("""
            CREATE TABLE IF NOT EXISTS human_responses (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                target_type VARCHAR(50) NOT NULL,
                target_id UUID NOT NULL,
                section_key VARCHAR(50),
                response_type VARCHAR(50) NOT NULL,
                content TEXT NOT NULL,
                recorded_at TIMESTAMP DEFAULT now()
            );
        """))
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
