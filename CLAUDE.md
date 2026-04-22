# Value Investing Copilot — CLAUDE.md

> 가치투자자를 위한 AI 투자 분석 코파일럿.
> 자동매매 없음. AI가 초안 생성, 사람이 확정하는 Human-in-the-loop 구조.

---

## 핵심 철학 (절대 어기지 말 것)

1. AI는 초안만 생성 → **사람이 confirmed 눌러야** Break Monitor 등 모든 감시 활성화
2. `draft → confirmed → needs_review` 상태 머신이 모든 것의 중심
3. Macro는 보고서/대시보드로만 — 개별 thesis DB에 넣지 않음
4. 보고서 읽기는 **웹앱**, 명령 실행·알림은 **Telegram**
5. 자동매매 코드는 절대 작성하지 않음
6. **데이터 수집과 분석은 분리** — 재무 데이터를 먼저 수집(refresh-data)한 뒤 AI 분석 실행
7. **뉴스는 가치투자 렌즈로 필터링** — 주가/목표가/애널리스트 의견은 노이즈. thesis key_assumptions에 직접 영향을 주는 사건만 신호

---

## 프로젝트 구조

```
value-copilot/
├── CLAUDE.md
├── docker-compose.yml          # 로컬 개발용
├── docker-compose.prod.yml     # EC2 프로덕션용 (nginx + no reload)
├── deploy.sh                   # EC2 배포 스크립트
├── scripts/server-setup.sh     # EC2 최초 Docker 설치
├── .env                        # 실제 환경변수 (배포 시 rsync 제외)
│
├── backend/                        # FastAPI
│   ├── main.py                     # DB create_all → enum/컬럼 마이그레이션 → 라우터 등록
│   ├── models/
│   │   └── db.py                   # ORM 모델 + Enum 정의
│   ├── routes/
│   │   ├── tickers.py              # 종목 CRUD + analyze/refine/refresh-data/report/bulk-*
│   │   ├── thesis.py               # Thesis CRUD + confirm
│   │   ├── reports.py              # 보고서 관리 + 트리거 + discovery + portfolio-review
│   │   ├── portfolio.py            # KIS 동기화 트리거 + 거래 감지
│   │   ├── tradelog.py             # 투자 일지 CRUD (GET/PATCH note/DELETE)
│   │   ├── market.py               # 시장 지표 API
│   │   └── settings.py             # 설정 조회/수정 + system-info
│   ├── services/
│   │   ├── agent.py                # Agent Core — 모든 Claude 호출
│   │   ├── financial_data.py       # US 종목 재무 데이터 (yfinance 기본 / financialdatasets 선택) + DB 캐시
│   │   ├── kr_financial_data.py    # OpenDART + yfinance (KR 종목)
│   │   ├── sec_pipeline.py         # EDGAR 공시 → Claude Haiku 요약 → DB
│   │   ├── dart_pipeline.py        # DART 정기공시 TOC → viewer.do → Claude Haiku 요약 → DB
│   │   ├── scheduler.py            # 06:00 light_refresh / 07:00 briefing / 08:00 break_monitor
│   │   ├── market_data.py          # VIX / S&P500 / KOSPI / Fear&Greed
│   │   ├── portfolio_sync.py       # KIS API 동기화 + 거래 감지 → TradeLog 저장
│   │   ├── telegram.py             # notify_* 9개 함수 (APP_URL 딥링크 포함)
│   │   └── telegram_bot.py         # /analyze /report /sync /macro 커맨드
│   └── .claude/
│       └── skills/
│           ├── thesis-generator/SKILL.md
│           ├── report-generator/SKILL.md
│           ├── daily-briefing/SKILL.md
│           ├── break-monitor/SKILL.md
│           ├── macro-report/SKILL.md
│           ├── stock-discovery/SKILL.md
│           └── portfolio-review/SKILL.md
│
└── frontend/                       # React + Vite
    ├── Dockerfile.prod             # 프로덕션 빌드 (node → nginx 멀티스테이지)
    ├── nginx.conf                  # SPA 라우팅 + /api/ 프록시 + SSE 지원
    └── src/
        ├── components/
        │   └── Markdown.tsx        # 커스텀 마크다운 렌더러
        │                           # 지원: h1~h3, bold/italic/code, 표, 목록, blockquote, 코드블록, hr
        │                           # <section> XML 태그 자동 strip
        ├── pages/
        │   ├── Dashboard.tsx       # 포트폴리오/관심 섹션 + bulk 작업 + 설정 모달
        │   ├── Thesis.tsx          # Thesis탭 + 재무데이터탭 (재무제표/지표/공시 요약)
        │   ├── Reports.tsx         # 보고서 히스토리 + 읽음관리 + 코멘트 + 종류 필터 + 복수삭제
        │   └── Journal.tsx         # 투자 일지 (KIS 동기화 거래 자동감지 + 메모 작성)
        ├── api.ts
        └── types.ts
```

---

## 데이터 모델

```python
# Ticker — 종목 마스터
Ticker:
  id: uuid
  symbol: str          # NVDA, 005930
  name: str
  market: enum         # US_Stock | KR_Stock
  status: enum         # portfolio | watchlist
  daily_alert: bool    # Break Monitor 대상 여부
  created_at, updated_at

# Thesis — 투자 노트 (핵심)
Thesis:
  id: uuid
  ticker_id: uuid (FK, unique)
  confirmed: enum      # draft | confirmed | needs_review
  confirmed_at: datetime | null
  thesis: text
  risk: text
  key_assumptions: text   # Break Monitor가 이 수치로 모니터링
  valuation: text
  last_analyzed_at: datetime

# Report — 생성된 보고서
Report:
  id: uuid
  ticker_id: uuid | null   # null = 브리핑 / macro / discovery / portfolio_review
  type: enum               # analysis | daily_brief | macro | discovery | portfolio_review
  content: text            # <section name="..."> XML 태그 포맷
  is_read: bool            # 읽음 여부 (기본 false)
  created_at: datetime

# ReportComment — 보고서 메모
ReportComment:
  id: uuid
  report_id: uuid (FK → reports, CASCADE DELETE)
  content: text
  created_at: datetime

# Portfolio — 보유 현황 (KIS 동기화)
Portfolio:
  id: uuid
  ticker_id: uuid (FK, unique)
  quantity: float          # 0이면 청산 (KIS에서 사라진 종목)
  avg_price: float
  current_price: float
  daily_pct: float
  updated_at: datetime

# TradeLog — KIS 동기화 거래 감지 기록
TradeLog:
  id: uuid
  ticker_id: uuid (FK → tickers, SET NULL on delete)
  symbol: str
  name: str
  action: enum             # buy | sell | add | reduce
  quantity_before: float
  quantity_after: float
  avg_price_before: float
  avg_price_after: float
  note: text | null        # 사용자 작성 거래 이유
  detected_at: datetime
  noted_at: datetime | null

# FinancialCache — API 응답 캐시 (TTL 기반)
FinancialCache:
  id: uuid
  ticker_id: uuid (FK, CASCADE)
  data_type: str       # US: yfinance_data | income|balance|cashflow|metrics|news|insider_trades|facts
                       # KR: income|metrics|news|naver_news|insider_trades|facts
  data: JSON
  fetched_at: datetime
  expires_at: datetime
  UNIQUE(ticker_id, data_type)

# SecFilingSummary — SEC/DART 공시 요약 (누적)
SecFilingSummary:
  id: uuid
  ticker_id: uuid (FK, CASCADE)
  filing_type: str     # 10-K | 10-Q | 사업보고서 | 반기보고서
  report_period: str   # 2024 | 2024-Q3 | 2025-04
  filing_url: text
  business_summary, risk_summary, mda_summary: text
  summarized_at: datetime

# Settings — 사용자 설정 key-value
Settings:
  key: str (PK)        # us_data_source
  value: str           # yfinance | financialdatasets
  updated_at: datetime
```

---

## 캐시 설계

```
FinancialCache TTL:
  yfinance_data               : 24시간 (US 종목 yfinance 통합 캐시 — 재무제표+지표+뉴스 일체)
  income / balance / cashflow : 90일  (분기 공시 — 수동 갱신)
  metrics / news / naver_news : 24시간 (매일 06:00 자동 갱신)
  insider_trades              : 3일   (매일 06:00 자동 갱신)
  facts                       : 30일  (수동 갱신)

갱신 방식:
  수동 "데이터 갱신" (단일 종목)  → 전체 캐시 삭제 + 재수집 + SEC/DART 파이프라인
  bulk-refresh (복수 선택)        → BackgroundTask 순차 처리(2초 sleep), 프론트 15초 polling
  06:00 light_refresh             → news / metrics / insider_trades만 overwrite

Rate limit 보호:
  yfinance      : 수집 전 1초 sleep, bulk 시 종목 간 2초 sleep
  DART viewer   : 섹션 fetch 간 1초 sleep
  Anthropic API : Haiku 호출 간 1.5초 sleep, 공시 건당 1.5초 cooldown
```

---

## 데이터 흐름

```
[종목 추가]
    ↓
[데이터 수집] (수동 단일 / Dashboard 멀티셀렉트 bulk)
  US: yfinance → FinancialCache(yfinance_data, 24h)  ← 기본
      financialdatasets.ai → FinancialCache(income/balance/cashflow/metrics/news/insider_trades)
        ↑ Settings(us_data_source=financialdatasets) 시 사용, 한도 초과 시 yfinance 자동 전환
      EDGAR submissions API → primary HTML → Claude Haiku → SecFilingSummary
  KR: OpenDART → FinancialCache (income/news/insider_trades/facts)
      yfinance (.KS/.KQ 자동 판별) → FinancialCache (metrics)
      네이버 뉴스 API → FinancialCache (naver_news)
      DART 정기공시 TOC → viewer.do → Claude Haiku → SecFilingSummary
    ↓
[AI 분석] ("AI 분석" 버튼)
  FinancialCache → financial_context 구성
  → Claude Sonnet → Thesis 4섹션 초안
    ↓
[피드백 루프] (선택, 반복 가능)
  사람 피드백 → Claude Sonnet → 수정된 Thesis
    ↓
[Confirm] (사람만)
  draft / needs_review → confirmed
  Break Monitor 활성화 (daily_alert=True 종목)
  → Telegram notify_thesis_confirmed
    ↓
[보고서 생성] (수동)
  FinancialCache + SecFilingSummary + Thesis
  → Claude Sonnet (max_tokens=8192) → 8섹션 심층 보고서
  → Telegram notify_report_generated + 딥링크

[보고서 탭]
  종목 탐색      : 아이디어 → US+KR 유망 종목 SSE → DB 저장 → Telegram
  포트폴리오 점검 : KIS + Thesis + Metrics → 5섹션 SSE → DB 저장 → Telegram
  보고서 관리    : 읽음/미읽음 토글, 코멘트 작성, 복수 선택 삭제, 종류별 필터

[KIS 동기화] (수동 버튼)
  동기화 전 Portfolio 스냅샷
    ↓ KIS API 전 계좌 집계
  신규/청산/수량변화 감지 → TradeLog 저장
  청산 종목: quantity=0, status=watchlist
  → Telegram notify_trades_detected + /journal 딥링크

[투자 일지] (/journal)
  TradeLog 목록 (날짜별 그룹, 미작성 강조)
  → 인라인 메모 작성 (note + noted_at 저장)

[매일 자동]
  06:00  light_refresh  : news/metrics/insider_trades 갱신
  07:00  daily_briefing : 뉴스 + 포트폴리오 + 매크로 → 3섹션 브리핑 (max_tokens=8192)
                        → Telegram + /reports 딥링크
  08:00  break_monitor  : confirmed 종목 → intact/weakening/broken
                        → Telegram + /tickers/{id}/thesis 딥링크
```

---

## 상태 머신 규칙

```
(빈값/신규)
    ↓ AI 분석 실행
  draft          ← AI 초안. Break Monitor 비활성.
    ↓ [선택] 피드백 반복
    ↓ 사람이 confirm
  confirmed      ← Break Monitor 활성 (daily_alert=True 시).
    ↓ /analyze or /refine 재실행 후 저장
  needs_review   ← Telegram needs_review 알림. Break Monitor 비활성.
    ↓ 사람이 confirm
  confirmed
```

**규칙:**
- `confirmed` 상태가 아니면 Break Monitor 절대 발동하지 않음
- AI가 임의로 `confirmed`로 바꾸지 않음 — 반드시 사람 액션 필요
- confirmed → analyze/refine 저장 시: `needs_review` + Telegram 알림 발송
- `/analyze` 저장 시: `confirmed` → `needs_review`, 그 외 → `draft`

---

## Telegram 알림 (9종)

모두 `APP_URL` 환경변수 기반 딥링크 포함.

| 함수 | 트리거 | 링크 |
|---|---|---|
| `notify_thesis_confirmed` | 사람이 Confirm 클릭 | `/tickers/{id}/thesis` |
| `notify_thesis_needs_review` | confirmed 상태에서 AI 재분석 완료 | `/tickers/{id}/thesis` |
| `notify_break_monitor` | 08:00 Break Monitor 실행 | `/tickers/{id}/thesis` |
| `notify_report_generated` | 종목 심층 분석 보고서 저장 | `/reports?id={id}` |
| `notify_daily_briefing` | 07:00 데일리 브리핑 저장 | `/reports?id={id}` |
| `notify_macro_saved` | 매크로 보고서 저장 | `/reports?id={id}` |
| `notify_discovery_saved` | 종목 탐색 보고서 저장 | `/reports?id={id}` |
| `notify_portfolio_review_saved` | 포트폴리오 점검 보고서 저장 | `/reports?id={id}` |
| `notify_trades_detected` | KIS 동기화 후 거래 감지 | `/journal` |

---

## 기술 스택

```
Frontend   React 18 + TypeScript + Vite + Tailwind CSS
           SSE (fetch + ReadableStream) — POST 지원 위해 EventSource 대신 사용
           react-router-dom: /, /tickers/:id/thesis, /reports, /journal

Backend    Python 3.11 + FastAPI + SSE
           APScheduler (06:00 / 07:00 / 08:00 KST 3개 job)
           7개 라우터: tickers / thesis / reports / portfolio / tradelog / market / settings

Agent      Anthropic API
           - claude-sonnet-4-6: thesis/report/break_monitor/briefing/discovery/portfolio-review/macro
             max_tokens: thesis 4096, report 8192, briefing 8192, macro 4096, discovery/portfolio-review 6000
           - claude-haiku-4-5-20251001: SEC/DART 공시 요약 (max_tokens 600, 비용 절감)
           SKILL.md 기반 스킬 시스템 (7개 스킬)
           .scratchpad/*.jsonl 로깅

DB         PostgreSQL 15 (프로덕션: EC2 3.26.145.173)
           10개 테이블: tickers / theses / reports / report_comments /
                        portfolios / trade_logs / financial_cache /
                        sec_filing_summaries / settings / (내부: alembic 없음, startup 마이그레이션)
           startup 시 자동 마이그레이션: is_read 컬럼, report_comments, trade_logs 테이블

External   yfinance: US 기본 소스 (재무제표+지표+뉴스 통합, 24h TTL)
                    KR 시장 지표 (KOSPI=.KS / KOSDAQ=.KQ 자동 판별)
           financialdatasets.ai: US 선택 소스 (Settings 전환, 한도 초과 시 yfinance fallback)
           SEC EDGAR: 10-K/10-Q HTML (submissions API → primary doc)
           OpenDART: KR 재무제표 / 공시 / 임원거래 / 정기공시 TOC
           네이버 뉴스 API: KR 뉴스 (없으면 skip)
           KIS API: 5개 계좌 포트폴리오 동기화

Messaging  python-telegram-bot (알림 전용, 봇 커맨드는 보조용)
           APP_URL 환경변수로 딥링크 생성

Deploy     EC2 (ap-southeast-2, 3.26.145.173) + Docker Compose + nginx
           nginx: 포트 80, React 정적 서빙 + /api/ 프록시 (SSE buffering 비활성화)
           배포: ./deploy.sh (rsync + docker compose up --build, 약 2분)
```

---

## Agent Skills 상세

### thesis-generator/SKILL.md
- 재무 데이터 있으면 실제 수치 기반 (없으면 graceful fallback)
- 버핏 8문항 Quick Filter 포함
- key_assumptions는 측정 가능한 수치로 (Break Monitor 기준)
- refs: value-investing.md / valuation-models.md / analysis-framework.md

### report-generator/SKILL.md
- 8섹션: business_overview / moat_analysis / financial_analysis / management_quality / valuation / risk_matrix / recent_developments / investment_conclusion
- 입력: 5년 재무제표 + Metrics TTM + 뉴스 + 인사이더 + SEC 요약 + thesis
- refs: buffett-skills 8개 파일 (2,141줄)

### daily-briefing/SKILL.md
- 입력: 뉴스(종목별 3건) + 포트폴리오 현재가 + 매크로 지표
- 3섹션: macro / portfolio_summary / watchlist
- max_tokens=8192 (포트폴리오 종목 수에 비례)

### break-monitor/SKILL.md
- confirmed + daily_alert=True 종목만
- 뉴스 신호: 경영진 교체 / 사업구조 / 주요계약 / 규제 / 자본배분
- 출력: intact / weakening / broken

### macro-report/SKILL.md
- 3섹션: market_overview / macro_factors / portfolio_implication
- max_tokens=4096

### stock-discovery/SKILL.md
- 5섹션: theme_analysis / us_picks / kr_picks / screening_criteria / next_steps

### portfolio-review/SKILL.md
- 5섹션: portfolio_overview / holdings_assessment / concentration_risk / thesis_health_check / action_items

---

## 환경 변수 (.env)

```bash
ANTHROPIC_API_KEY=

DATABASE_URL=postgresql://value_copilot:value_copilot@localhost:5432/value_copilot
REDIS_URL=redis://localhost:6379

TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
APP_URL=http://3.26.145.173        # Telegram 딥링크 기본 URL

KIS_APP_KEY=
KIS_APP_SECRET=
KIS_ACCOUNT_NO=

FINANCIAL_DATASETS_API_KEY=        # US 선택 소스 (없으면 yfinance만 사용)
OPENDART_API_KEY=                  # KR 재무/공시 (없으면 KR 데이터 수집 불가)
NAVER_CLIENT_ID=                   # KR 뉴스 (없으면 skip)
NAVER_CLIENT_SECRET=
```

---

## 개발 & 배포

```bash
# 로컬 개발
docker compose up -d          # 전체 스택
docker compose up -d --build  # 의존성 변경 후

# EC2 배포
./deploy.sh                   # rsync + docker compose up --build (약 2분)

# 접속
# 로컬: http://localhost:5173
# 프로덕션: http://3.26.145.173
```

---

## 주의사항

- **데이터 수집 선행 필수**: AI 분석 / 보고서 생성 전 "데이터 갱신" 버튼 클릭
- **보고서 삭제**: 웹앱 UI에서 단건/복수 삭제 가능. 코멘트도 CASCADE 삭제
- **US 종목 데이터**: yfinance 기본. `yfinance_data` 단일 키에 재무제표+지표+뉴스 통합
- **US 데이터 소스 전환**: Settings(us_data_source) 값으로 제어. financialdatasets 한도 초과 시 yfinance 자동 전환
- **KR 종목 데이터**: OpenDART(재무제표/공시) + yfinance(시장지표) + 네이버뉴스(선택)
- **KR balance/cashflow**: DART `fnlttSinglAcntAll` 단일 호출로 IS/BS/CF 동시 추출
- **청산 종목 처리**: KIS 동기화 시 KIS에 없는 종목은 qty=0, status=watchlist 자동 전환
- **거래 감지 임계값**: qty 변화 0.01 이하는 부동소수점 오차로 무시
- **마크다운 렌더링**: 모든 LLM 생성 텍스트는 Markdown.tsx로 렌더링. `<section>` 태그 자동 strip. 스트리밍 중은 `<pre>` 유지
- **보고서 섹션 뷰**: 5개 타입 모두 전용 아코디언 뷰 (daily_brief/macro/analysis/discovery/portfolio_review)
- **Telegram 딥링크**: APP_URL 환경변수 필수. 미설정 시 `http://3.26.145.173` fallback
- **자동매매 코드 작성 금지**
- **Thesis confirmed 변경은 반드시 사람의 명시적 액션으로만**
