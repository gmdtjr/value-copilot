import uuid
import enum
import os
from datetime import datetime

from sqlalchemy import (
    create_engine, Column, String, Boolean, DateTime,
    Text, Enum as SAEnum, ForeignKey, Float, JSON, UniqueConstraint, Integer,
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


def _enum_values(enum_cls: type[enum.Enum]) -> list[str]:
    return [member.value for member in enum_cls]


def _pg_enum(enum_cls: type[enum.Enum], *, name: str | None = None) -> SAEnum:
    return SAEnum(
        enum_cls,
        name=name,
        values_callable=_enum_values,
    )


def _string_enum(enum_cls: type[enum.Enum], *, name: str | None = None) -> SAEnum:
    return SAEnum(
        enum_cls,
        name=name,
        values_callable=_enum_values,
        native_enum=False,
    )


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
    RETIRED = "retired"

class ReportTypeEnum(str, enum.Enum):
    ANALYSIS = "analysis"
    DAILY_BRIEF = "daily_brief"
    MACRO = "macro"
    DISCOVERY = "discovery"
    PORTFOLIO_REVIEW = "portfolio_review"

class StockTypeEnum(str, enum.Enum):
    COMPOUNDING = "compounding"
    GROWTH = "growth"
    ASSET_PLAY = "asset_play"
    TURNAROUND = "turnaround"
    CYCLICAL = "cyclical"
    SPECIAL_SITUATION = "special_situation"

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
    market = Column(SAEnum(MarketEnum, name="marketenum"), nullable=False)
    status = Column(SAEnum(TickerStatusEnum, name="tickerstatusenum"), default=TickerStatusEnum.WATCHLIST)
    daily_alert = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    theses = relationship(
        "Thesis",
        back_populates="ticker",
        cascade="all, delete-orphan",
    )
    reports = relationship("Report", back_populates="ticker", cascade="all, delete-orphan")
    portfolio = relationship("Portfolio", back_populates="ticker", uselist=False, cascade="all, delete-orphan")

    @property
    def thesis(self):
        """Active thesis: confirmed > needs_review > draft (by version_number desc). Excludes retired."""
        active = [t for t in self.theses if t.confirmed and t.confirmed != ThesisStatusEnum.RETIRED]
        if not active:
            return None
        priority = {ThesisStatusEnum.CONFIRMED: 0, ThesisStatusEnum.NEEDS_REVIEW: 1, ThesisStatusEnum.DRAFT: 2}
        active.sort(key=lambda t: (priority.get(t.confirmed, 99), -(t.version_number or 1)))
        return active[0]


class Thesis(Base):
    __tablename__ = "theses"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticker_id = Column(UUID(as_uuid=True), ForeignKey("tickers.id", ondelete="CASCADE"), nullable=False)
    version_number = Column(Integer, default=1, nullable=False)
    parent_version_id = Column(UUID(as_uuid=True), nullable=True)

    confirmed = Column(SAEnum(ThesisStatusEnum, name="thesisstatusenum"), default=ThesisStatusEnum.DRAFT, nullable=False)
    confirmed_at = Column(DateTime, nullable=True)
    thesis = Column(Text, nullable=True)
    risk = Column(Text, nullable=True)
    key_assumptions = Column(Text, nullable=True)
    valuation = Column(Text, nullable=True)
    last_analyzed_at = Column(DateTime, nullable=True)
    stock_type = Column(_string_enum(StockTypeEnum, name="stocktypeenum"), nullable=True)
    seed_memo = Column(Text, nullable=True)

    # Phase 2 신규 필드
    exploration_note = Column(Text, nullable=True)   # 외부 탐색에서 건진 핵심 인사이트
    key_logic = Column(Text, nullable=True)           # "이 논리가 깨지면 thesis가 무너진다" 한 단락
    retired_at = Column(DateTime, nullable=True)
    retirement_reason = Column(String(50), nullable=True)  # broken|sold|superseded|manual

    ticker = relationship("Ticker", back_populates="theses")


class Report(Base):
    __tablename__ = "reports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticker_id = Column(UUID(as_uuid=True), ForeignKey("tickers.id"), nullable=True)
    type = Column(_pg_enum(ReportTypeEnum, name="reporttypeenum"), nullable=False)
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
    action = Column(SAEnum(TradeActionEnum, name="tradeactionenum"), nullable=False)
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


class ConversationImportTypeEnum(str, enum.Enum):
    DISCOVERY = "discovery"
    THESIS_CHALLENGE = "thesis_challenge"
    PORTFOLIO_REVIEW = "portfolio_review"
    DEEP_ANALYSIS = "deep_analysis"


class ConversationImport(Base):
    """외부 탐색(Claude 대화) 결과를 시스템으로 가져오기."""
    __tablename__ = "conversation_imports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticker_id = Column(UUID(as_uuid=True), ForeignKey("tickers.id", ondelete="SET NULL"), nullable=True)
    import_type = Column(_string_enum(ConversationImportTypeEnum, name="convimporttypeenum"), nullable=False)
    summary = Column(Text, nullable=False)
    raw_excerpt = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    ticker = relationship("Ticker")


class HumanResponseTypeEnum(str, enum.Enum):
    AGREE = "agree"
    DISAGREE = "disagree"
    PARTIAL = "partial"
    OVERRIDE = "override"
    NOTE = "note"


class HumanResponseTargetEnum(str, enum.Enum):
    REPORT = "report"
    THESIS = "thesis"
    BREAK_SIGNAL = "break_signal"
    RETROSPECTIVE = "retrospective"


class HumanResponse(Base):
    """LLM 출력(보고서 섹션, thesis, break signal 등)에 대한 사람 메모."""
    __tablename__ = "human_responses"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    target_type = Column(_string_enum(HumanResponseTargetEnum, name="humanresponsetargetenum"), nullable=False)
    target_id = Column(UUID(as_uuid=True), nullable=False)
    section_key = Column(String(50), nullable=True)  # 보고서 섹션 구분 (optional)
    response_type = Column(_string_enum(HumanResponseTypeEnum, name="humanresponsetypeenum"), nullable=False)
    content = Column(Text, nullable=False)
    recorded_at = Column(DateTime, default=datetime.utcnow)
