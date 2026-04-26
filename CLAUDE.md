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
7. **뉴스는 투자 thesis 렌즈로 필터링** — 주가/목표가/애널리스트 의견은 노이즈. thesis key_assumptions에 직접 영향을 주는 사건만 신호
8. **Thesis는 관점 기반 생성** — "AI 분석" 클릭 시 stock_type + seed_memo 입력 필수. AI는 사람의 관점을 정리하는 역할. AI가 관점을 만들지 않음
9. **종목 상세 보고서는 중립** — report-generator는 특정 투자 철학에 편향되지 않은 다관점 분석. 결론을 내리지 않고 사용자가 관점을 수립할 재료를 제공

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
│   │   ├── ideas.py                # 아이디어 메모 CRUD (GET/POST/PATCH/DELETE)
│   │   ├── market.py               # 시장 지표 API
│   │   └── settings.py             # 설정 조회/수정 + system-info
│   ├── services/
│   │   ├── agent.py                # Agent Core — 모든 Claude 호출
│   │   ├── financial_data.py       # US 종목 재무 데이터 (yfinance 기본 / financialdatasets 선택) + DB 캐시
│   │   ├── kr_financial_data.py    # OpenDART + yfinance (KR 종목)
│   │   ├── sec_pipeline.py         # EDGAR 10-K/10-Q/8-K → Claude Haiku 요약 → DB
│   │   │                           # 8-K: 실적(2.02)/임원변경(5.02)/주요계약(1.01)/가이던스(7.01) 필터링
│   │   │                           # CIK 캐시(_cik_cache) 프로세스 메모리 내 유지
│   │   ├── dart_pipeline.py        # DART 정기공시 TOC → viewer.do → Claude Haiku 요약 → DB
│   │   ├── scheduler.py            # 06:00 light_refresh / 07:00 briefing / 08:00 break_monitor
│   │   ├── market_data.py          # VIX / S&P500 / KOSPI / Fear&Greed
│   │   ├── portfolio_sync.py       # KIS API 동기화 + 거래 감지 → TradeLog 저장
│   │   │                           # current_price/daily_pct는 Yahoo Finance quote로 덮어씀
│   │   ├── valley.py               # Valley.town AI 종목 페이지 URL 조회 + FinancialCache 캐시 (30일)
│   │   ├── telegram.py             # notify_* 9개 함수 (APP_URL 딥링크 포함)
│   │   └── telegram_bot.py         # /analyze /report /sync /macro 커맨드
│   └── .claude/
│       └── skills/
│           ├── thesis-generator/
│           │   ├── SKILL.md        # 관점 기반 초안 생성 (stock_type + seed_memo 입력)
│           │   └── refs/           # stock_type별 투자 프레임워크 (동적 로드)
│           │       ├── compounding.md
│           │       ├── growth.md
│           │       ├── asset_play.md
│           │       ├── turnaround.md
│           │       ├── cyclical.md
│           │       └── special_situation.md
│           ├── report-generator/SKILL.md   # 중립 8섹션 심층 보고서 (버핏 편향 제거)
│           ├── daily-briefing/SKILL.md
│           ├── break-monitor/SKILL.md      # stock_type별 신호 분기
│           ├── macro-report/SKILL.md
│           ├── stock-discovery/SKILL.md    # 탐색 렌즈(lens) 파라미터 지원
│           └── portfolio-review/SKILL.md
│
└── frontend/                       # React + Vite
    ├── Dockerfile.prod             # 프로덕션 빌드 (node → nginx 멀티스테이지)
    ├── nginx.conf                  # SPA 라우팅 + /api/ 프록시 + SSE 지원
    │                               # proxy_buffering off, proxy_read_timeout 300s
    ├── tailwind.config.js          # darkMode: 'class' (라이트/다크 토글)
    └── src/
        ├── contexts/
        │   └── ThemeContext.tsx    # 테마(dark/light) + 글자크기(sm/md/lg) 상태 — localStorage 영속화
        ├── components/
        │   ├── Markdown.tsx        # 커스텀 마크다운 렌더러
        │   │                       # 지원: h1~h3, bold/italic/code, 표, 목록, blockquote, 코드블록, hr
        │   │                       # <section> XML 태그 자동 strip. dark: 클래스 완전 지원
        │   └── ThemeControls.tsx   # 헤더 공용 — A/A/A 글자크기 버튼 + ☀/🌙 테마 토글
        ├── pages/
        │   ├── Dashboard.tsx       # 포트폴리오/관심 섹션 + bulk 작업 + 설정 모달
        │   │                       # 종목 카드: 종목명 크게, 심볼·시장 작게 표시
        │   │                       # bulk 버튼: 데이터 수집 / 리포트 생성 / Valley 링크 찾기
        │   │                       # (bulk Thesis 생성 제거됨 — 관점 입력 필요로 개별 생성)
        │   ├── Thesis.tsx          # Thesis탭 + 재무데이터탭 + 보고서탭
        │   │                       # AI 분석 버튼 → 모달(stock_type 선택 + seed_memo 입력)
        │   │                       # 종목명 헤더 크게, 심볼·시장 작게 표시
        │   │                       # main 영역에 fs-${fontSize} 적용 (글자크기 조절 반영)
        │   ├── Reports.tsx         # 보고서 히스토리 + 읽음관리 + 코멘트 + 종류 필터 + 복수삭제
        │   │                       # 종목 탐색: 렌즈 선택 드롭다운 + 아이디어 입력
        │   │                       # 보고서 목록: 종목명 크게, 심볼 회색 작게
        │   │                       # 사이드바 접기/펼치기 (PanelLeft 토글, lg+ only)
        │   │                       # 컨테이너 max-w-[1400px]. 보고서 본문에 fs-${fontSize} 적용
        │   └── Journal.tsx         # 거래일지 탭 (KIS 동기화 거래 + 메모) + 아이디어 탭 (자유 메모)
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
  stock_type: enum | null  # compounding | growth | asset_play | turnaround | cyclical | special_situation
  seed_memo: text | null   # 사용자의 초기 투자 관점 (AI 분석 시 입력 필수)

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
                       # 공통: valley_url (30일, Valley.town 종목 페이지 URL)
  data: JSON
  fetched_at: datetime
  expires_at: datetime
  UNIQUE(ticker_id, data_type)

# SecFilingSummary — SEC/DART 공시 요약 (누적)
SecFilingSummary:
  id: uuid
  ticker_id: uuid (FK, CASCADE)
  filing_type: str     # 10-K | 10-Q | 8-K | 사업보고서 | 반기보고서
  report_period: str   # 2024 | 2024-Q3 | 2025-04 | 2025-01-15 (8-K는 날짜)
  filing_url: text
  business_summary: text  # 10-K/10-Q: Item1 요약 | 8-K: 이벤트 유형 레이블
  risk_summary: text      # 10-K/10-Q only
  mda_summary: text       # 10-K/10-Q: MD&A 요약 | 8-K: 이벤트 전체 요약
  summarized_at: datetime

# Settings — 사용자 설정 key-value
Settings:
  key: str (PK)        # us_data_source
  value: str           # yfinance | financialdatasets
  updated_at: datetime

# IdeaMemo — 자유 형식 투자 아이디어 메모
IdeaMemo:
  id: uuid
  content: text                  # 메모 본문
  ticker_symbol: str | null      # 선택적 종목 태그 (DB 종목과 무관한 자유 입력, 대문자 저장)
  created_at: datetime
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
  valley_url                  : 30일  (bulk-resolve-valley 수동 실행)

갱신 방식:
  수동 "데이터 갱신" (단일 종목)  → 전체 캐시 삭제 + 재수집 + SEC/DART + 8-K 파이프라인
  bulk-refresh (복수 선택)        → BackgroundTask 순차 처리(2초 sleep), 프론트 15초 polling
  bulk-resolve-valley (복수 선택) → BackgroundTask 순차 처리(2초 sleep), 프론트 15초 polling
  06:00 light_refresh             → news / metrics / insider_trades 갱신 + US_Stock 8-K 신규 체크

Rate limit 보호:
  yfinance      : 수집 전 1초 sleep, bulk 시 종목 간 2초 sleep
  DART viewer   : 섹션 fetch 간 1초 sleep
  Anthropic API : Haiku 호출 간 1.5초 sleep, 공시 건당 1.5초 cooldown
  Valley.town   : bulk 시 종목 간 2초 sleep
  EDGAR (8-K)   : 주 문서 fetch 간 1초 sleep, EX-99.1 fetch 0.5초 sleep
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
      EDGAR submissions API → 10-K/10-Q primary HTML → Claude Haiku → SecFilingSummary
      EDGAR submissions API → 8-K (실적/임원/계약/가이던스) → 주문서+EX-99.1 → Claude Haiku → SecFilingSummary
  KR: OpenDART → FinancialCache (income/news/insider_trades/facts)
      yfinance (.KS/.KQ 자동 판별) → FinancialCache (metrics)
      네이버 뉴스 API → FinancialCache (naver_news)
      DART 정기공시 TOC → viewer.do → Claude Haiku → SecFilingSummary
    ↓
[보고서 생성] (수동, 선택)  ← 관점 수립 재료
  FinancialCache + SecFilingSummary (8-K 포함) + Thesis
  → Claude Sonnet (max_tokens=8192) → 8섹션 중립 심층 보고서
    business_overview / competitive_position / financial_analysis / management_track_record /
    valuation / risk_matrix / recent_developments / bull_bear_synthesis
  → Telegram notify_report_generated + 딥링크
    ↓
[AI 분석] ("AI 분석" 버튼 → 모달)
  사람: 보고서를 읽고 관점 수립
      → stock_type 선택 (compounding|growth|asset_play|turnaround|cyclical|special_situation)
      → seed_memo 작성 (나의 초기 관점, 필수)
  → 해당 stock_type 프레임워크 파일 동적 로드
  → Claude Sonnet → Thesis 4섹션 초안 (seed_memo 기반)
    ↓
[피드백 루프] (선택, 반복 가능)
  사람 피드백 → Claude Sonnet → 수정된 Thesis
    ↓
[Confirm] (사람만)
  draft / needs_review → confirmed
  Break Monitor 활성화 (daily_alert=True 종목)
  → Telegram notify_thesis_confirmed

[보고서 탭]
  종목 탐색      : 렌즈 선택(compounding/growth/asset-play/turnaround/cyclical/special-situation/다양하게)
                  + 아이디어 입력 → US+KR 유망 종목 SSE → DB 저장 → Telegram
  포트폴리오 점검 : KIS + Thesis + Metrics → 5섹션 SSE → DB 저장 → Telegram
  보고서 관리    : 읽음/미읽음 토글, 코멘트 작성, 복수 선택 삭제, 종류별 필터

[KIS 동기화] (수동 버튼)
  동기화 전 Portfolio 스냅샷
    ↓ KIS API 전 계좌 집계
  각 종목별 Yahoo Finance quote → current_price / daily_pct 덮어씀
    (KIS evlu_pfls_rt는 평가손익률이므로 일일 등락률로 사용 불가)
  신규/청산/수량변화 감지 → TradeLog 저장
  청산 종목: quantity=0, status=watchlist
  → Telegram notify_trades_detected + /journal 딥링크

[Valley 링크 찾기] (Dashboard bulk 버튼)
  선택 종목 → bulk-resolve-valley → BackgroundTask
  Valley.town 로그인(VALLEY_EMAIL/VALLEY_PASSWORD) → 종목 검색 → URL 후보 검증
  US: stockId suffix 기반 거래소 매핑 → NASD/NYSE/AMEX 순으로 시도
  KR: 6자리 zero-pad → KRX/kospi/kosdaq 순으로 시도 (ETF는 kospi 우선)
  성공 시 FinancialCache(valley_url, 30일) 저장
  Dashboard 카드에 파란색 Valley 외부링크 표시 (실패 시 amber 비활성)

[투자 일지] (/journal)
  거래일지 탭: TradeLog 목록 (날짜별 그룹, 미작성 강조)
    → 인라인 메모 작성 (note + noted_at 저장)
  아이디어 탭: IdeaMemo 자유 메모 (상단 작성 폼 + 날짜별 그룹)
    → 종목 태그 선택 가능 (DB 미등록 종목도 허용)
    → 카드 호버 시 수정/삭제 버튼 노출

[매일 자동]
  06:00  light_refresh  : news/metrics/insider_trades 갱신
                          + US_Stock 종목별 8-K 신규 공시 체크 (이미 요약된 건 즉시 스킵)
  07:00  daily_briefing : 뉴스 + 포트폴리오 + 매크로 → 3섹션 브리핑 (max_tokens=8192)
                        → Telegram + /reports 딥링크
  08:00  break_monitor  : confirmed 종목 → stock_type별 신호 기준으로 intact/weakening/broken 판정
                        → Telegram + /tickers/{id}/thesis 딥링크
```

---

## 상태 머신 규칙

```
(빈값/신규)
    ↓ "AI 분석" → 모달(stock_type + seed_memo 입력) → 생성
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
- **bulk Thesis 생성 없음** — 각 종목마다 stock_type + seed_memo 개별 입력 필수

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
Frontend   React 18 + TypeScript + Vite + Tailwind CSS (darkMode: 'class')
           SSE (fetch + ReadableStream) — POST 지원 위해 EventSource 대신 사용
           react-router-dom: /, /tickers/:id/thesis, /reports, /journal
           ThemeContext: 라이트/다크 + 글자크기(sm/md/lg) — localStorage 영속화
           ThemeControls: 모든 페이지 헤더 공용 컴포넌트

Backend    Python 3.11 + FastAPI + SSE
           APScheduler (06:00 / 07:00 / 08:00 KST 3개 job)
           8개 라우터: tickers / thesis / reports / portfolio / tradelog / ideas / market / settings

Agent      Anthropic API
           - claude-sonnet-4-6: thesis/report/break_monitor/briefing/discovery/portfolio-review/macro
             max_tokens: thesis 4096, refine 4096, report 16000, briefing 8192,
                         macro 4096, discovery 16000, portfolio-review 16000, break-monitor 1024
           - claude-haiku-4-5-20251001: SEC/DART 공시 요약 (max_tokens 600, 비용 절감)
           SKILL.md 기반 스킬 시스템 (7개 스킬)
           .scratchpad/*.jsonl 로깅 (SCRATCHPAD_DIR=/app/.scratchpad)

DB         PostgreSQL 15 (프로덕션: EC2 3.26.145.173)
           10개 테이블: tickers / theses / reports / report_comments /
                        portfolios / trade_logs / idea_memos / financial_cache /
                        sec_filing_summaries / settings
           (alembic 없음, startup 마이그레이션)
           startup 시 자동 마이그레이션 순서:
             1. create_all() — 신규 테이블/enum 생성
             2. ReportTypeEnum 값 이름 변경 (ANALYSIS→analysis, DAILY_BRIEF→daily_brief, MACRO→macro)
             3. ReportTypeEnum 신규 값 추가 (discovery, portfolio_review)
             4. is_read BOOLEAN 컬럼 추가 (reports)
             5. report_comments 테이블 생성
             6. TradeActionEnum 생성 + trade_logs 테이블 생성
             7. idea_memos 테이블 생성
             8. stock_type VARCHAR(50) 컬럼 추가 (theses)
             9. seed_memo TEXT 컬럼 추가 (theses)

External   yfinance: US 기본 소스 (재무제표+지표+뉴스 통합, 24h TTL)
                    ETF 감지(quoteType=ETF) 시 ETF 전용 metrics 수집 (totalAssets/NAV/yield/beta 등)
                    ETF는 재무제표 없음 → income/cf/bs 빈값 정상. EDGAR 파이프라인 미실행.
                    KR 시장 지표 (KOSPI=.KS / KOSDAQ=.KQ 자동 판별)
                    KIS 동기화 후 종목별 현재가/일일등락률 quote 소스로도 사용
           financialdatasets.ai: US 선택 소스 (Settings 전환, 한도 초과 시 yfinance fallback)
           SEC EDGAR: 10-K/10-Q/8-K HTML (submissions API → primary doc + EX-99.1)
           OpenDART: KR 재무제표 / 공시 / 임원거래 / 정기공시 TOC
           네이버 뉴스 API: KR 뉴스 (없으면 skip)
           KIS API: 5개 계좌 포트폴리오 동기화 (evlu_pfls_rt=평가손익률, daily_pct로 사용하지 않음)
           Valley.town: AI 투자 분석 플랫폼. 종목 페이지 URL 조회 및 캐시 (VALLEY_EMAIL/VALLEY_PASSWORD)

Messaging  python-telegram-bot (알림 전용, 봇 커맨드는 보조용)
           APP_URL 환경변수로 딥링크 생성

Deploy     EC2 (ap-southeast-2, 3.26.145.173) + Docker Compose + nginx
           nginx: 포트 80, React 정적 서빙 + /api/ 프록시
                  proxy_buffering off, proxy_read_timeout 300s, proxy_send_timeout 300s
           SSE 응답: Cache-Control: no-cache, X-Accel-Buffering: no 헤더 명시 필수
           uvicorn workers=1 고정 (bulk 작업 상태가 프로세스 메모리에 있어 다중 worker 불가)
           배포: ./deploy.sh (rsync + docker compose up --build, 약 2분)
```

---

## Agent Skills 상세

### thesis-generator/SKILL.md
- **관점 기반 생성**: seed_memo(사용자 초기 관점)를 기반으로 thesis 초안 작성. AI가 관점을 만들지 않음
- stock_type에 맞는 프레임워크 파일을 refs/에서 동적 로드 (asset_play → refs/asset_play.md)
- key_assumptions는 stock_type 프레임워크 기준으로 측정 가능한 수치로 작성 (Break Monitor 기준)
- 재무 데이터 있으면 실제 수치 기반, 없으면 graceful fallback

### thesis-generator/refs/ (stock_type별 프레임워크)
| 파일 | 유형 | 핵심 지표 | 주요 밸류에이션 |
|------|------|----------|--------------|
| compounding.md | 지속 복리 성장 | ROIC > 15%, FCF전환율, 재투자 기회 | DCF / P/FCF |
| growth.md | 고성장 초기 기업 | 매출CAGR, TAM침투율, Rule of 40 | EV/Revenue, Reverse DCF |
| asset_play.md | 저평가 자산 | P/B, NAV, 촉매 이벤트 | NAV, 청산가치 |
| turnaround.md | 회복 촉매 | 촉매 일정, Cash runway, 구조조정 효과 | 정상화 EV/EBITDA |
| cyclical.md | 사이클 저점 | Mid-cycle 이익, 부채 수준, 선행지표 | Mid-cycle EV/EBITDA |
| special_situation.md | 이벤트 드리븐 | 이벤트 완료 가치, 스프레드, 타임라인 | 이벤트 기대가치 |

### report-generator/SKILL.md
- **중립 다관점 분석**: 특정 투자 철학(버핏 등) 편향 없음. 결론 없이 Bull/Bear 논거 병기
- Buffett refs(01~08) 로드하지 않음 — 프레임워크로 재활용 가능하나 현재 미사용
- 8섹션: business_overview / **competitive_position** / financial_analysis / **management_track_record** /
  valuation / risk_matrix / recent_developments / **bull_bear_synthesis**
- 입력: 5년 재무제표 + Metrics TTM + 뉴스 + 인사이더 + SEC 요약(8-K 포함) + thesis(참고용)
- max_tokens=16000

### break-monitor/SKILL.md
- confirmed + daily_alert=True 종목만
- **stock_type별 신호 분기**: thesis의 stock_type에 따라 판단 기준 적용
  - compounding: ROIC 하락, FCF 훼손, 경쟁 구조 변화
  - growth: 매출 성장 둔화, Cash runway, Unit economics 악화
  - asset_play: 자산 가치 훼손, 촉매 이벤트 지연
  - turnaround: 핵심 촉매 지연/실패, Cash runway 위험
  - cyclical: 사이클 선행지표 악화, 부채 임계치 접근
  - special_situation: 이벤트 무산 리스크, 타임라인 연장
- stock_type 없는 기존 confirmed 종목: 공통 신호 기준으로 판단
- 출력: intact / weakening / broken

### daily-briefing/SKILL.md
- 입력: 뉴스(종목별 3건) + 포트폴리오 현재가 + 매크로 지표
- 3섹션: macro / portfolio_summary / watchlist
- max_tokens=8192 (포트폴리오 종목 수에 비례)

### macro-report/SKILL.md
- 3섹션: market_overview / macro_factors / portfolio_implication
- max_tokens=4096

### stock-discovery/SKILL.md
- **렌즈(lens) 파라미터**: compounding/growth/asset-play/turnaround/cyclical/special-situation/다양하게
- 렌즈별 스크리닝 기준 적용. "다양하게"는 6개 렌즈 혼합
- 5섹션: theme_analysis / us_picks / kr_picks / screening_criteria / next_steps
- max_tokens=16000

### portfolio-review/SKILL.md
- 5섹션: portfolio_overview / holdings_assessment / concentration_risk / thesis_health_check / action_items
- max_tokens=16000

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

VALLEY_EMAIL=                      # Valley.town 로그인 이메일 (없으면 Valley 링크 기능 비활성)
VALLEY_PASSWORD=                   # Valley.town 로그인 비밀번호
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

### 데이터 수집
- **데이터 수집 선행 필수**: AI 분석 / 보고서 생성 전 "데이터 갱신" 버튼 클릭
- **US 종목 데이터**: yfinance 기본. `yfinance_data` 단일 키에 재무제표+지표+뉴스 통합
- **US 데이터 소스 전환**: Settings(us_data_source) 값으로 제어. financialdatasets 한도 초과 시 yfinance 자동 전환
- **KR 종목 데이터**: OpenDART(재무제표/공시) + yfinance(시장지표) + 네이버뉴스(선택)
- **KR balance/cashflow**: DART `fnlttSinglAcntAll` 단일 호출로 IS/BS/CF 동시 추출
- **8-K 파이프라인**: 실적(2.02)/임원(5.02)/계약(1.01)/가이던스(7.01)/주요이벤트(8.01) 필터. EX-99.1(press release) 자동 추출. 06:00 light_refresh에서 신규 8-K 자동 체크. 이미 요약된 건(ticker_id+period+filing_type 중복) 즉시 스킵
- **CIK 캐시**: `_cik_cache` dict로 company_tickers.json 중복 호출 방지. workers=1이라 프로세스 메모리 캐시 안전

### Thesis 생성
- **stock_type 필수**: "AI 분석" 버튼 클릭 시 모달에서 stock_type 선택 + seed_memo 작성 필수
- **bulk Thesis 생성 없음**: Dashboard의 일괄 Thesis 생성 버튼 제거됨. 각 종목 페이지에서 개별 생성
- **bulk-analyze 엔드포인트**: 백엔드 `POST /api/tickers/bulk-analyze` 엔드포인트는 여전히 존재(Telegram bot 등 내부용). 기존 thesis의 stock_type 사용, 없으면 "compounding" default

### 보고서
- **보고서 삭제**: 웹앱 UI에서 단건/복수 삭제 가능. 코멘트도 CASCADE 삭제
- **report-generator 섹션명**: competitive_position, management_track_record, bull_bear_synthesis (구버전: moat_analysis, management_quality, investment_conclusion)
- **sec_context 순서**: 8-K 먼저(시의성), 그 뒤 10-K/10-Q (report 프롬프트에서 최신 이벤트 우선 반영)
- **discovery max_tokens**: 6000 (5섹션이 4096을 초과하므로 증가)
- **SSE 저장 확인**: discovery/portfolio-review 완료 후 finally 블록에서 무조건 목록 갱신. 이전에 없던 신규 보고서 감지해 자동 선택

### 표시
- **종목명 우선 표시**: Dashboard 카드, Thesis 헤더, Reports 목록 모두 종목명 크게, 심볼 작게
  - Dashboard: `종목명 (크게) / 심볼 · US|KR (작게)`
  - Reports: `종목명 심볼(회색)` 형식
- **KR 종목**: 심볼이 6자리 숫자라 종목명 우선 표시 특히 중요
- **라이트/다크 모드**: Tailwind `dark:` 클래스 전체 적용. `<html class="dark">` 토글로 전환
  - 기본값: 다크 모드 (localStorage 'theme' 키로 영속화)
  - 컬러 버튼(bg-blue-700 등): 라이트 모드에서도 white text 유지 — 배경이 충분히 어두움
  - 배지(bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-200): 라이트/다크 각각 별도 정의
- **글자 크기 조절**: `fs-sm / fs-md / fs-lg` CSS 클래스로 보고서·thesis 본문 폰트 크기 제어
  - `index.css`에 `p, li, td, th` 선택자로 정의 (0.8 / 0.875 / 1.0 rem)
  - localStorage 'fontSize' 키로 영속화. Reports.tsx와 Thesis.tsx main에 적용
- **Reports 사이드바**: 데스크탑(lg+)에서 `sidebarCollapsed` 상태로 접기/펼치기
  - 접힌 상태: `lg:w-0 overflow-hidden` + 보고서 본문이 전체 너비 사용
  - 컨테이너: `max-w-[1400px]` (이전 `max-w-5xl` 1024px에서 확장)

### 인프라
- **SSE 헤더**: `Cache-Control: no-cache`, `X-Accel-Buffering: no` 모든 SSE 응답에 명시. reports.py의 discovery/portfolio-review 포함
- **SSE 이벤트 타입**: start | chunk | complete | error | saved | done. discovery/portfolio-review는 complete 이후 saved(report_id 포함) → done 순으로 emit
- **SSE 저장 감지**: frontend finally 블록에서 스트리밍 전 report ID 목록 기억 → 이후 신규 discovery 보고서 감지로 discoverySaved 처리
- **uvicorn workers=1**: bulk 작업 상태(_job_store)가 프로세스 메모리에 있어 다중 worker로 실행하면 상태 불일치 발생. 단일 worker 고정
- **청산 종목 처리**: KIS 동기화 시 KIS에 없는 종목은 qty=0, status=watchlist 자동 전환
- **거래 감지 임계값**: qty 변화 0.01 이하는 부동소수점 오차로 무시
- **마크다운 렌더링**: 모든 LLM 생성 텍스트는 Markdown.tsx로 렌더링. `<section>` 태그 자동 strip. 스트리밍 중은 `<pre>` 유지
- **Telegram 딥링크**: APP_URL 환경변수 필수. 미설정 시 `http://3.26.145.173` fallback
- **ETF 종목 (SHV 등)**: quoteType=ETF 감지 시 재무제표 없음이 정상. totalAssets/NAV/yield/beta 기반 ETF 전용 metrics 표시. EDGAR 파이프라인 미실행. has_data는 current_price 기준으로 판단
- **KIS daily_pct 버그 수정**: 과거 동기화에서 evlu_pfls_rt(평가손익률)를 daily_pct에 저장한 데이터가 남아 있을 수 있음. `list_tickers`에서 daily_pct와 pnl_pct가 0.05% 이내로 같고 둘 다 50% 초과면 daily_pct=None으로 처리
- **KIS 동기화 current_price/daily_pct**: KIS API 값 대신 Yahoo Finance quote로 덮어씀. KIS evlu_pfls_rt는 평가손익률이므로 일일 등락률로 사용 불가
- **Valley 링크**: Dashboard 멀티셀렉트 → "Valley 링크 찾기" 버튼으로 bulk 조회. VALLEY_EMAIL/VALLEY_PASSWORD 환경변수 필수. FinancialCache(valley_url)에 30일 캐시. 조회 성공 시 카드에 파란색 외부링크, 실패 시 amber 비활성 표시
- **아이디어 메모**: `/api/ideas` CRUD. ticker_symbol은 DB 종목 FK 없이 자유 텍스트 (대문자). Journal 페이지의 아이디어 탭에서 관리
- **자동매매 코드 작성 금지**
- **Thesis confirmed 변경은 반드시 사람의 명시적 액션으로만**
