import uuid
import enum
import os
from datetime import datetime

from sqlalchemy import (
    create_engine, Column, String, Boolean, DateTime,
    Text, Enum as SAEnum, ForeignKey, Float, JSON, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://value_copilot:value_copilot@localhost:5432/value_copilot",
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── Enums ────────────────────────────────────────────────────────────────────

class MarketEnum(str, enum.Enum):
    US_STOCK = "US_Stock"
    KR_STOCK = "KR_Stock"

class TickerStatusEnum(str, enum.Enum):
    PORTFOLIO = "portfolio"
    WATCHLIST = "watchlist"

class ThesisStatusEnum(str, enum.Enum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"
    NEEDS_REVIEW = "needs_review"

class ReportTypeEnum(str, enum.Enum):
    ANALYSIS = "analysis"
    DAILY_BRIEF = "daily_brief"
    MACRO = "macro"
    DISCOVERY = "discovery"
    PORTFOLIO_REVIEW = "portfolio_review"

class TradeActionEnum(str, enum.Enum):
    BUY = "buy"        # 신규 매수
    SELL = "sell"      # 전량 매도
    ADD = "add"        # 추가 매수
    REDUCE = "reduce"  # 일부 매도


# ── ORM Models ────────────────────────────────────────────────────────────────

class Ticker(Base):
    __tablename__ = "tickers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    symbol = Column(String(20), unique=True, nullable=False, index=True)
    name = Column(String(200), nullable=False)
    market = Column(SAEnum(MarketEnum), nullable=False)
    status = Column(SAEnum(TickerStatusEnum), default=TickerStatusEnum.WATCHLIST)
    daily_alert = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    thesis = relationship("Thesis", back_populates="ticker", uselist=False, cascade="all, delete-orphan")
    reports = relationship("Report", back_populates="ticker", cascade="all, delete-orphan")
    portfolio = relationship("Portfolio", back_populates="ticker", uselist=False, cascade="all, delete-orphan")


class Thesis(Base):
    __tablename__ = "theses"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticker_id = Column(UUID(as_uuid=True), ForeignKey("tickers.id"), unique=True, nullable=False)
    confirmed = Column(SAEnum(ThesisStatusEnum), default=ThesisStatusEnum.DRAFT, nullable=False)
    confirmed_at = Column(DateTime, nullable=True)
    thesis = Column(Text, nullable=True)
    risk = Column(Text, nullable=True)
    key_assumptions = Column(Text, nullable=True)
    valuation = Column(Text, nullable=True)
    last_analyzed_at = Column(DateTime, nullable=True)

    ticker = relationship("Ticker", back_populates="thesis")


class Report(Base):
    __tablename__ = "reports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticker_id = Column(UUID(as_uuid=True), ForeignKey("tickers.id"), nullable=True)
    type = Column(SAEnum(ReportTypeEnum), nullable=False)
    content = Column(Text, nullable=False)
    is_read = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    ticker = relationship("Ticker", back_populates="reports")
    comments = relationship("ReportComment", back_populates="report", cascade="all, delete-orphan", order_by="ReportComment.created_at")


class ReportComment(Base):
    __tablename__ = "report_comments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    report_id = Column(UUID(as_uuid=True), ForeignKey("reports.id", ondelete="CASCADE"), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    report = relationship("Report", back_populates="comments")


class Portfolio(Base):
    __tablename__ = "portfolios"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticker_id = Column(UUID(as_uuid=True), ForeignKey("tickers.id"), unique=True, nullable=False)
    quantity = Column(Float, default=0)
    avg_price = Column(Float, default=0)
    current_price = Column(Float, default=0)
    daily_pct = Column(Float, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    ticker = relationship("Ticker", back_populates="portfolio")


class FinancialCache(Base):
    """financialdatasets.ai API 응답 캐시. TTL 기반 자동 만료."""
    __tablename__ = "financial_cache"
    __table_args__ = (
        UniqueConstraint("ticker_id", "data_type", name="uq_financial_cache_ticker_type"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticker_id = Column(UUID(as_uuid=True), ForeignKey("tickers.id", ondelete="CASCADE"), nullable=False)
    data_type = Column(String(50), nullable=False)   # income|balance|cashflow|metrics|news|insider_trades|facts
    data = Column(JSON, nullable=False)
    fetched_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)


class SecFilingSummary(Base):
    """SEC 공시 원문을 Claude로 요약한 결과. 보고서 프롬프트에 RAG 방식으로 주입."""
    __tablename__ = "sec_filing_summaries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticker_id = Column(UUID(as_uuid=True), ForeignKey("tickers.id", ondelete="CASCADE"), nullable=False)
    filing_type = Column(String(20), nullable=False)   # 10-K | 10-Q
    report_period = Column(String(20), nullable=False) # 2025 | 2024-Q3
    filing_url = Column(Text, nullable=True)
    business_summary = Column(Text, nullable=True)     # Item 1 요약
    risk_summary = Column(Text, nullable=True)         # Item 1A 요약
    mda_summary = Column(Text, nullable=True)          # Item 7 요약
    summarized_at = Column(DateTime, default=datetime.utcnow)


class Settings(Base):
    """사용자 설정 key-value 스토어."""
    __tablename__ = "settings"

    key = Column(String(100), primary_key=True)
    value = Column(String(500), nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class TradeLog(Base):
    """KIS 동기화 전/후 거래 감지 기록. 사용자가 거래 이유(note)를 작성."""
    __tablename__ = "trade_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticker_id = Column(UUID(as_uuid=True), ForeignKey("tickers.id", ondelete="SET NULL"), nullable=True)
    symbol = Column(String(20), nullable=False)
    name = Column(String(200), nullable=False)
    action = Column(SAEnum(TradeActionEnum), nullable=False)
    quantity_before = Column(Float, nullable=False, default=0)
    quantity_after = Column(Float, nullable=False, default=0)
    avg_price_before = Column(Float, nullable=False, default=0)
    avg_price_after = Column(Float, nullable=False, default=0)
    note = Column(Text, nullable=True)
    detected_at = Column(DateTime, default=datetime.utcnow)
    noted_at = Column(DateTime, nullable=True)


class IdeaMemo(Base):
    """자유 형식 투자 아이디어 메모. 종목 태그는 선택."""
    __tablename__ = "idea_memos"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    content = Column(Text, nullable=False)
    ticker_symbol = Column(String(20), nullable=True)  # DB 종목과 무관한 자유 태그
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
