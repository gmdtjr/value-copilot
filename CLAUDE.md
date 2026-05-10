# Value Investing Copilot — CLAUDE.md

> 가치투자자를 위한 AI 투자 분석 코파일럿.
> 자동매매 없음. Thesis는 사람이 직접 작성·확정. AI는 보고서·Break Monitor·복기에만 사용.

---

## 핵심 철학 (절대 어기지 말 것)

1. **Thesis는 사람이 직접 작성** — 외부 Claude에서 완성한 결과를 "Thesis 작성" 모달로 직접 입력. AI thesis 생성 없음
2. `draft → confirmed → retired` 상태 머신 + **버전 관리** — 수정 = 새 버전 생성, 기존 버전 보존
3. Macro는 보고서/대시보드로만 — 개별 thesis DB에 넣지 않음
4. 보고서 읽기는 **웹앱**, 명령 실행·알림은 **Telegram**
5. 자동매매 코드는 절대 작성하지 않음
6. **데이터 수집은 보고서·Break Monitor용** — 재무 데이터(refresh-data)는 심층 보고서 생성과 Break Monitor 감시에 사용. Thesis 직접 입력에는 불필요
7. **뉴스는 Monitoring Contract 렌즈로 필터링** — 주가/목표가/애널리스트 의견은 노이즈. Break Conditions와 Watch Metrics에 직접 영향을 주는 사건만 신호
8. **Thesis는 외부 완성 후 직접 입력** — 외부 Claude에서 심층 분석 → Thesis 완성 프롬프트(5개 필드 산출) → 앱에 붙여넣기. 5개 필드: thesis / risk / key_assumptions / valuation / monitoring_contract
9. **종목 상세 보고서는 중립** — 결론 없이 Bull/Bear 논거 병기
10. **탐색은 밖에서, 확정은 시스템에서** — 종목 탐색·포트폴리오 점검·집중분석·Monitoring Contract 산출은 외부 Claude로, 결과를 시스템에 기록
11. **LLM은 관찰, 사람은 판단** — Break Monitor는 관찰(observations, positive/negative signals)만 출력, verdict(strengthening/intact/weakening/broken)는 사람이 결정
12. **논리를 기록한다** — 진입 시 Monitoring Contract 명문화, 청산 시 복기 (Phase 4)

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
│   │   ├── tickers.py              # 종목 CRUD + thesis/direct/refresh-data/report/bulk-*
│   │   │                           # + DELETE /{id} (cascade) + POST /{id}/resolve-valley (단건)
│   │   │                           # POST /{id}/thesis/direct — AI 없이 5개 필드 직접 저장 (UI)
│   │   │                           # POST /{id}/analyze — SSE thesis AI (Telegram bot 내부용만)
│   │   ├── thesis.py               # Thesis CRUD + confirm
│   │   ├── reports.py              # 보고서 관리 + macro 트리거 + explore-prompt 생성
│   │   ├── portfolio.py            # KIS 동기화 트리거 + 거래 감지
│   │   ├── tradelog.py             # 투자 일지 CRUD (POST 수동생성/GET/PATCH note/DELETE)
│   │   ├── ideas.py                # 아이디어 메모 CRUD (GET/POST/PATCH/DELETE)
│   │   ├── conversations.py        # ConversationImport CRUD (외부 탐색 결과 기록)
│   │   ├── human_responses.py      # HumanResponse CRUD (보고서 섹션 메모)
│   │   ├── break_signals.py        # BreakSignal CRUD + verdict 입력
│   │   ├── cycles.py               # InvestmentCycle 조회 + exit_reason 입력
│   │   └── retrospectives.py       # Retrospective CRUD + AI 초안 생성
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
│   │   ├── scheduler.py            # 06:00 light_refresh / 08:00 break_monitor / 월 08:00 weekly_briefing
│   │   ├── market_data.py          # VIX / S&P500 / KOSPI / Fear&Greed
│   │   ├── portfolio_sync.py       # KIS API 동기화 + 거래 감지 → TradeLog 저장
│   │   │                           # current_price/daily_pct는 Yahoo Finance quote로 덮어씀
│   │   ├── valley.py               # Valley.town AI 종목 페이지 URL 조회 + FinancialCache 캐시 (30일)
│   │   ├── telegram.py             # notify_* 7개 함수 (APP_URL 딥링크 포함)
│   │   └── telegram_bot.py         # /analyze /report /sync /macro 커맨드
│   └── .claude/
│       └── skills/
│           ├── thesis-generator/
│           │   ├── SKILL.md        # 관점 기반 초안 생성 (stock_type + seed_memo + key_logic 추출)
│           │   └── refs/           # stock_type별 투자 프레임워크 (동적 로드)
│           ├── report-generator/SKILL.md          # 중립 8섹션 심층 보고서
│           ├── break-monitor/SKILL.md             # stock_type별 신호 분기 (현재: 레이블 출력, Phase3에서 관찰 전용으로 개선 예정)
│           ├── macro-report/SKILL.md
│           ├── weekly-briefing/SKILL.md           # 주간 브리핑 (월 08:00)
│           └── exploration-prompt-generator/SKILL.md  # 외부 탐색용 프롬프트 생성
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
        │   │                       # bulk 버튼: 데이터 수집 / 리포트 생성 / Valley 링크 찾기 / 종목 삭제
        │   │                       # 종목 단건 삭제 (카드 Trash 아이콘 → 확인 모달)
        │   │                       # (bulk Thesis 생성 제거됨 — 관점 입력 필요로 개별 생성)
        │   ├── Thesis.tsx          # Thesis탭 + 재무데이터탭 + 보고서탭 + 버전히스토리탭
        │   │                       # "Thesis 작성" 버튼 → 직접 입력 모달
        │   │                       #   stock_type 선택 + 5개 필드(thesis/risk/key_assumptions/valuation/monitoring_contract)
        │   │                       #   전체 붙여넣기: [THESIS][RISK][KEY_ASSUMPTIONS][VALUATION][MONITORING_CONTRACT] 자동 파싱
        │   │                       # 외부 탐색 도구: 심층분석 프롬프트 / Thesis 완성 프롬프트 (2개만)
        │   │                       # 종목별 탐색 기록(ConversationImport) 인라인 표시
        │   │                       # 버전 히스토리: 5개 필드 모두 접고 펼치기 가능 (VersionCard)
        │   ├── Reports.tsx         # 보고서 히스토리 + 읽음관리 + 코멘트 + 종류 필터 + 복수삭제
        │   │                       # 탐색 프롬프트 복사: 종목 탐색 / 포트폴리오 점검 (외부 Claude용)
        │   │                       # 보고서 섹션별 HumanResponse 메모 슬롯
        │   │                       # 사이드바 접기/펼치기 (PanelLeft 토글, lg+ only)
        │   └── Journal.tsx         # 거래일지 탭 + 아이디어 탭 + 탐색결과 탭
        │                           # 탐색결과: ConversationImport 기록 (discovery/deep_analysis/thesis_challenge/portfolio_review)
        │                           # 수동 기록: "수동 기록" 버튼 → ManualTradeComposer 모달 → POST /api/tradelog
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
  daily_alert: bool    # 주시 종목 여부 — True: 신호 유무 무관 항상 Telegram 알림 / False: 신호 감지 시에만 알림
  created_at, updated_at

# Thesis — 투자 노트 (버전 관리)
Thesis:
  id: uuid
  ticker_id: uuid (FK)     # unique 제약 없음 — 종목당 여러 버전 가능
  version_number: int       # 1부터 시작
  parent_version_id: uuid | null  # 이전 버전 추적
  confirmed: enum      # draft | confirmed | needs_review | retired
  confirmed_at: datetime | null
  thesis: text
  risk: text
  key_assumptions: text
  valuation: text
  last_analyzed_at: datetime
  stock_type: enum | null  # compounding | growth | asset_play | turnaround | cyclical | special_situation
  seed_memo: text | null          # 구버전 필드 (신규 입력 없음, 기존 데이터 호환용)
  exploration_note: text | null   # 구버전 필드 (신규 입력 없음, 기존 데이터 호환용)
  key_logic: text | null          # 구버전 필드 — monitoring_contract Core Logic과 중복. DB 유지, 모달 입력 제거
  monitoring_contract: text | null  # Break Monitor가 그대로 사용할 감시 계약서 (핵심)
                                    # 형식: Core Logic / Break Conditions / Strengthening Signals / Watch Metrics / Review Timing
  retired_at: datetime | null
  retirement_reason: str | null  # superseded | broken | sold | manual

  # 비즈니스 규칙
  # - Ticker.thesis @property: confirmed > needs_review > draft (version_number 내림차순, NULLS LAST)
  # - "Thesis 작성" 시 confirmed 버전 있으면 새 draft 버전 생성 (기존 유지)
  # - "Thesis 작성" 시 draft/needs_review 버전 있으면 in-place 수정
  # - Confirm 시 이전 non-retired 버전들 → retired (retirement_reason='superseded')
  # - monitoring_contract 필수 (또는 key_logic fallback) — Break Monitor 감시 기준
  # - Break Monitor: monitoring_contract 우선, 없으면 key_logic, 없으면 key_assumptions 폴백
  # - version_number ORDER BY: .nullslast() 필수 — NULL이 NULLS FIRST로 정렬되는 PG 기본값 방지

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
  content: text
  ticker_symbol: str | null      # 선택적 종목 태그 (DB 종목과 무관한 자유 입력, 대문자 저장)
  created_at: datetime
  updated_at: datetime

# ConversationImport — 외부 탐색 결과 기록 (Phase 2)
ConversationImport:
  id: uuid
  ticker_id: uuid | null (FK → tickers, SET NULL)
  import_type: str   # discovery | deep_analysis | thesis_challenge | portfolio_review
  summary: text      # 핵심 요약 (사람이 직접)
  raw_excerpt: text | null  # 중요 발췌 (선택)
  created_at: datetime

# HumanResponse — LLM 출력에 대한 사람 메모 (Phase 2)
HumanResponse:
  id: uuid
  target_type: str   # report | thesis | break_signal | retrospective
  target_id: uuid
  section_key: str | null  # 보고서 섹션 구분
  response_type: str  # agree | disagree | partial | override | note
  content: text
  recorded_at: datetime

# BreakSignal — Break Monitor 관찰 결과 (Phase 3)
BreakSignal:
  id: uuid
  thesis_id: uuid (FK → theses, CASCADE)
  checked_at: datetime
  key_logic_snapshot: text | null   # 체크 시점 key_logic/monitoring_contract 사본
  observations: text                # LLM 관찰: "무엇이 바뀌었는가" — 레이블 없음
  positive_signals: text | null     # thesis 강화 신호
  negative_signals: text | null     # thesis 약화 신호
  watch_items: text | null
  verdict: enum | null              # strengthening | intact | weakening | broken — 사람이 판정
  human_note: text | null
  reviewed_at: datetime | null

# InvestmentCycle — 매수~매도 완결 단위 (Phase 4)
InvestmentCycle:
  id: uuid
  ticker_id: uuid (FK, CASCADE)
  thesis_id: uuid | null (FK → theses, SET NULL)  # 진입 당시 확정 thesis
  status: enum                # open | closed
  opened_at: datetime         # KIS 매수 감지 자동 생성
  closed_at: datetime | null
  exit_reason: enum | null    # logic_broken | target_reached | better_opportunity | mistake | other
  exit_reason_note: text | null
  pnl_pct: float | null       # 청산 시점 수익률 자동 계산

# Retrospective — 청산 후 논리 복기 (Phase 4)
Retrospective:
  id: uuid
  cycle_id: uuid (FK unique, CASCADE)
  is_draft: bool
  original_logic: text          # key_logic 자동 복사 (불변)
  what_changed: text | null     # 실제로 무엇이 달랐는가
  logic_held: bool | null       # 핵심 논리가 결국 맞았는가 — 사람 판단
  weak_link: text | null        # 논리의 어느 연결고리가 약했는가
  if_wrong_why: text | null     # 틀렸다면 어디서 잘못 생각했는가
  if_right_why: text | null     # 맞았다면 이 구조는 반복 가능한가
  next_time: text | null        # 다음에 비슷한 상황에서 어떻게 생각할 것인가
  completed_at: datetime | null

  # Phase 4 자동화
  # KIS 매수 감지 → InvestmentCycle 자동 열기 (confirmed thesis 연결)
  # KIS 전량매도 감지 → 사이클 자동 종료 + Retrospective 초안 행 생성
  #   + Telegram "복기를 시작하세요" 알림
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
  valley_url                  : 30일  (bulk-resolve-valley 또는 단건 resolve-valley 수동 실행)

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
[Thesis 직접 입력] ("Thesis 작성" 버튼 → 모달)
  외부 플로우:
    1. Thesis 페이지 "심층 분석 프롬프트" 복사 → 외부 Claude에서 대화 시작
    2. 논의 완료 후 "Thesis 완성 프롬프트" 복사 → 외부 Claude에서 5개 필드 산출
       출력 형식: [THESIS] / [RISK] / [KEY_ASSUMPTIONS] / [VALUATION] / [MONITORING_CONTRACT]
    3. 결과 전체를 앱 "Thesis 작성" 모달 → 전체 붙여넣기 textarea → "채우기" 클릭 → 자동 파싱
    4. stock_type 선택 후 저장 → draft 생성
  API: POST /api/tickers/{id}/thesis/direct (AI 호출 없음, 즉시 저장)
    ↓
[Confirm] (사람만)
  draft / needs_review → confirmed
  monitoring_contract 필수 (key_logic fallback 가능)
  Break Monitor 활성화 (confirmed 전체 대상, daily_alert=True면 항상 알림)
  → Telegram notify_thesis_confirmed

[보고서 탭]
  탐색 프롬프트  : 종목 탐색 / 포트폴리오 점검 프롬프트 복사 → 외부 Claude에서 실행
                  결과 → Journal "탐색결과" 탭에 ConversationImport로 기록
  보고서 관리    : 읽음/미읽음 토글, 코멘트 작성, 복수 선택 삭제, 종류별 필터
                  보고서 섹션별 HumanResponse (agree/disagree/partial/override/note)

[KIS 동기화] (수동 버튼)
  동기화 전 Portfolio 스냅샷
    ↓ KIS API 전 계좌 집계
  각 종목별 Yahoo Finance quote → current_price / daily_pct 덮어씀
    (KIS evlu_pfls_rt는 평가손익률이므로 일일 등락률로 사용 불가)
  신규/청산/수량변화 감지 → TradeLog 저장
  청산 종목: quantity=0, status=watchlist
  → Telegram notify_trades_detected + /journal 딥링크
  [Phase 4 — InvestmentCycle]
    BUY/ADD 감지 → InvestmentCycle 자동 열기 (confirmed thesis 연결, opened_at=detected_at)
    SELL 전량 감지 → 사이클 자동 종료 (closed_at, pnl_pct 계산) + Retrospective 초안 행 생성
                   → Telegram notify_cycle_closed "복기를 시작하세요" + /journal 딥링크

[Valley 링크 찾기]
  bulk (Dashboard 멀티셀렉트) → bulk-resolve-valley → BackgroundTask 순차 처리
  단건 (Thesis 페이지 헤더 "Valley 링크" 버튼) → POST /{id}/resolve-valley → BackgroundTask
  Valley.town 로그인(VALLEY_EMAIL/VALLEY_PASSWORD) → 종목 검색 → URL 후보 검증
  US: stockId suffix 기반 거래소 매핑 → NASD/NYSE/AMEX 순으로 시도
  KR: 6자리 zero-pad → KRX/kospi/kosdaq 순으로 시도 (ETF는 kospi 우선)
  성공 시 FinancialCache(valley_url, 30일) 저장
  Dashboard 카드: 파란색 Valley 외부링크 표시 (실패 시 amber 비활성)
  Thesis 헤더: valley_url 있으면 파란색 외부링크, 없으면 조회 버튼 (3초 polling, 최대 60초)

[종목 삭제]
  단건 (Dashboard 카드 Trash 아이콘 / Thesis 헤더 삭제 버튼) → 확인 모달 → DELETE /api/tickers/{id}
  bulk (Dashboard 멀티셀렉트 "삭제" 버튼) → 확인 모달 → 순차 DELETE
  CASCADE: thesis, reports, report_comments, portfolio, financial_cache, sec_filing_summaries 전부 삭제

[투자 일지] (/journal)
  거래일지 탭: TradeLog 목록 (날짜별 그룹, 미작성 강조)
    → 인라인 메모 작성 (note + noted_at 저장)
    → "수동 기록" 버튼 → ManualTradeComposer 모달 → POST /api/tradelog
      포트폴리오 종목 선택 시 현재 수량/단가 자동 입력. 거래유형(buy/add/reduce/sell) 선택
  아이디어 탭: IdeaMemo 자유 메모 (상단 작성 폼 + 날짜별 그룹)
  탐색결과 탭: ConversationImport 기록 (외부 Claude 탐색 결과, 종목 연결 가능)
  복기 탭: InvestmentCycle 목록
    → 모니터링 중 (open): 확정 thesis 연결, 진입 N일째, 수익률
    → 종료됨 (closed): Retrospective 편집
      - original_logic (자동 복사, 불변)
      - what_changed / logic_held / weak_link / if_wrong_why / if_right_why / next_time
      - AI 초안 생성 (POST /api/retrospectives/{id}/generate) → 사람이 수정 후 완료

[매일 자동]
  06:00  light_refresh  : news/metrics/insider_trades 갱신
                          + US_Stock 종목별 8-K 신규 공시 체크 (이미 요약된 건 즉시 스킵)
  08:00  break_monitor  : confirmed 전체 종목 실행 (daily_alert 무관)
                          Monitoring Contract 기준 관찰 (→ key_logic → key_assumptions 폴백)
                          → BreakSignal DB 저장 (observations/positive_signals/negative_signals/watch_items)
                          → has_signal 판정: positive/negative signals에 실제 내용 있으면 True
                          → Telegram: daily_alert=True(항상) OR has_signal=True(신호 감지 시)
                          → /tickers/{id}/thesis 딥링크
  월 08:00 weekly_briefing : 주간 모니터링 브리핑 (4섹션 — monitor_summary 포함)
                           → 전체 N개 / 이상없음 N개 / 신호감지 N개 요약
                           → Telegram + /reports 딥링크
```

---

## 상태 머신 규칙 (Phase 2 버전)

```
(빈값/신규)
    ↓ "Thesis 작성" → 외부 Claude 완성 결과 붙여넣기 → 저장
  draft v1       ← 직접 입력 초안. Break Monitor 비활성.
    ↓ 사람이 monitoring_contract 확인 후 confirm
  confirmed v1   ← Break Monitor 활성 (confirmed 전체 대상).
    ↓ "Thesis 작성" 재실행 (새 draft v2 생성, v1 그대로 유지)
  confirmed v1 + draft v2
    ↓ 사람이 v2 confirm
  confirmed v2 + retired v1 (retirement_reason='superseded')
```

**규칙:**
- `confirmed` 상태가 아니면 Break Monitor 절대 발동하지 않음
- confirmed thesis에서 "Thesis 작성" → 새 draft 버전 생성 (기존 confirmed 유지)
- draft/needs_review thesis에서 "Thesis 작성" → 동일 버전 in-place 수정
- **Confirm 전 monitoring_contract 필수** (key_logic fallback 가능) — Break Monitor 감시 기준
- **bulk Thesis 생성 없음** — 각 종목마다 외부 Claude 탐색 후 개별 직접 입력

---

## Telegram 알림 (8종)

모두 `APP_URL` 환경변수 기반 딥링크 포함.

| 함수 | 트리거 | 링크 |
|---|---|---|
| `notify_thesis_confirmed` | 사람이 Confirm 클릭 | `/tickers/{id}/thesis` |
| `notify_thesis_needs_review` | confirmed thesis에서 "Thesis 작성"으로 새 draft 버전 생성 시 | `/tickers/{id}/thesis` |
| `notify_break_monitor` | 08:00 Break Monitor 실행 — observations 요약 + Verdict 입력하기 링크 | `/tickers/{id}/thesis` |
| `notify_report_generated` | 종목 심층 분석 보고서 저장 | `/reports?id={id}` |
| `notify_weekly_briefing` | 월 08:00 주간 브리핑 저장 | `/reports?id={id}` |
| `notify_macro_saved` | 매크로 보고서 저장 | `/reports?id={id}` |
| `notify_trades_detected` | KIS 동기화 후 거래 감지 | `/journal` |
| `notify_cycle_closed` | KIS 전량매도 감지 → 사이클 자동 종료 | `/journal` |

---

## 기술 스택

```
Frontend   React 18 + TypeScript + Vite + Tailwind CSS (darkMode: 'class')
           SSE (fetch + ReadableStream) — POST 지원 위해 EventSource 대신 사용
           react-router-dom: /, /tickers/:id/thesis, /reports, /journal
           ThemeContext: 라이트/다크 + 글자크기(sm/md/lg) — localStorage 영속화
           ThemeControls: 모든 페이지 헤더 공용 컴포넌트

Backend    Python 3.11 + FastAPI + SSE
           APScheduler (06:00 / 08:00 KST + 월 08:00 3개 job)
           12개 라우터: tickers / thesis / reports / portfolio / tradelog / ideas /
                        conversations / human_responses / break_signals /
                        cycles / retrospectives / market / settings

Agent      Anthropic API
           - claude-sonnet-4-6: report/break_monitor/weekly_briefing/macro (thesis AI 생성 없음 — UI에서 직접 입력)
             max_tokens: report 16000, weekly_briefing 4096, macro 4096, break-monitor 1024
           - claude-haiku-4-5-20251001: SEC/DART 공시 요약 (max_tokens 600, 비용 절감)
           SKILL.md 기반 스킬 시스템 (5개 스킬: report-generator, break-monitor, macro-report,
                                      weekly-briefing, exploration-prompt-generator)
           thesis-generator: Telegram bot bulk-analyze 내부용으로만 유지 (UI에서 미사용)
           .scratchpad/*.jsonl 로깅 (SCRATCHPAD_DIR=/app/.scratchpad)

DB         PostgreSQL 15 (프로덕션: EC2 3.26.145.173)
           16개 테이블: tickers / theses / reports / report_comments /
                        portfolios / trade_logs / idea_memos / financial_cache /
                        sec_filing_summaries / settings / conversation_imports / human_responses /
                        break_signals / investment_cycles / retrospectives
                        (trade_logs.cycle_id FK 추가)
           (alembic 없음, startup 마이그레이션)
           startup 시 자동 마이그레이션 순서:
             0. ALTER TYPE enum ADD VALUE — AUTOCOMMIT 연결로 분리 (트랜잭션 블록 불가)
                reporttypeenum: discovery, portfolio_review 추가
                thesisstatusenum: retired 추가 (소문자 — _pg_enum values 기준)
                thesisstatusenum 소문자 정규화: DRAFT/CONFIRMED/NEEDS_REVIEW → draft/confirmed/needs_review
                  (기존 대문자 값이 있는 경우 rename, _pg_enum 전환으로 소문자 values 사용)
             1. create_all() — 신규 테이블/enum 생성
             2. ReportTypeEnum 값 이름 변경 (ANALYSIS→analysis 등)
             3. is_read BOOLEAN 컬럼 추가 (reports)
             4. report_comments 테이블 생성
             5. TradeActionEnum 생성 + trade_logs 테이블 생성
             6. idea_memos 테이블 생성
             7. stock_type / seed_memo 컬럼 추가 (theses)
             8. Phase 2: theses unique 제약 제거 + version_number/key_logic 등 컬럼 추가
                version_number 백필 (NULL→1) — 앞 DDL과 독립 커밋으로 분리
             9. conversation_imports / human_responses 테이블 생성

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
- **⚠️ UI에서 미사용** — Telegram bot의 `/api/tickers/bulk-analyze` 내부용으로만 유지
- UI thesis 입력은 `POST /api/tickers/{id}/thesis/direct` (직접 입력, AI 없음)
- stock_type에 맞는 프레임워크 파일을 refs/에서 동적 로드 (asset_play → refs/asset_play.md)
- 6섹션 출력: thesis / risk / key_assumptions / valuation / key_logic / monitoring_contract
- bulk-analyze: 기존 thesis의 stock_type 사용, 없으면 "compounding" default

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
- **중립 다관점 분석**: 특정 투자 철학 편향 없음. 결론 없이 Bull/Bear 논거 병기
- 8섹션: business_overview / competitive_position / financial_analysis / management_track_record /
  valuation / risk_matrix / recent_developments / **bull_bear_synthesis**
- **수치 재인용 최소화**: Valley 등 데이터 플랫폼에서 수치 자체는 확인 가능하므로, 보고서는 방향성·추세·해석 위주로 작성. 꼭 필요한 대표값 1~2개만 인용.
- **Reverse DCF 중심 밸류에이션**: 3-시나리오 DCF 테이블 대신, "현재 멀티플이 내포하는 성장 기대치"와 그 현실성 판단 중심
- 입력: 5년 재무제표(분석 참고용) + Metrics TTM + 뉴스 8건 + 인사이더 10건 + SEC/DART 요약 + thesis(참고용)
- max_tokens=16000. 섹션당 길이 최소화 제약 없음 — 인사이트 밀도 우선

### break-monitor/SKILL.md
- **대상**: confirmed 전체 (daily_alert 무관하게 실행)
- **알림 전략**:
  - `daily_alert=True` (주시 종목): 신호 유무 무관하게 항상 Telegram 알림
  - `daily_alert=False`: `has_signal=True`일 때만 Telegram 알림
- **Monitoring Contract 우선 기준**: monitoring_contract → key_logic → key_assumptions 순 폴백
- **4섹션 출력** (레이블 없음 — 판정은 사람이):
  - `observations`: "무엇이 바뀌었는가" 중립 관찰
  - `positive_signals`: Core Logic 강화 사실만 (Strengthening Signals 기준)
  - `negative_signals`: Break Conditions에 가까워지는 사실만
  - `watch_items`: 다음 체크 때 확인할 항목
- **필터링 원칙** (has_signal 신뢰성의 핵심):
  - positive/negative signals는 Monitoring Contract 기준에 직접 연결된 사실만
  - 무조건 무시: 주가 등락 / 애널리스트 목표가 / 컨센서스 beat/miss / 계약서에 없는 매크로
  - Key Metrics TTM: Monitoring Contract에서 언급된 지표의 방향성 변화만
- **`has_signal` 판정**: positive 또는 negative signals에 "특이사항 없음" 이상의 내용 → True
- **stock_type별 폴백 기준** (monitoring_contract 없을 때):
  - compounding: ROIC 추이, FCF 전환율, 경쟁 구조 변화
  - growth: 매출 성장률, Gross Margin, Cash runway
  - asset_play: 자산 가치 변화, 촉매 이벤트 진행
  - turnaround: 촉매 일정 진행, Cash runway 변화
  - cyclical: 사이클 선행지표 방향, 부채 수준
  - special_situation: 이벤트 타임라인, 리스크 변화
- **사람 판정 (verdict)**: strengthening | intact | weakening | broken — AI가 결정하지 않음
- BreakSignal DB에 저장 → Thesis 페이지에서 verdict 입력 가능

### weekly-briefing/SKILL.md
- **daily-briefing 대체** (월 08:00)
- **4섹션**: monitor_summary / macro_changes / break_summary / upcoming_events
  - `monitor_summary`: "전체 N개 — 이상 없음 N개 / 신호 감지 N개" + 신호 종목 요약
  - `break_summary`: 신호 감지 종목만 (이상 없는 종목 생략)
- max_tokens=4096
- 입력: 지난주 Break Signal 종목별 최신 1건 + 신호 통계(monitor_stats) + 매크로 지표

### exploration-prompt-generator/SKILL.md
- 외부 Claude 탐색용 프롬프트 생성 (LLM 호출 없음, DB 데이터 조립)
- 유형:
  - `discovery` (Reports 페이지): 종목 탐색
  - `portfolio_review` (Reports 페이지): 포트폴리오 점검
  - `deep_analysis` (Thesis 페이지): 종목 심층 분석 — 외부 대화 시작용. 보고서 데이터 주입
  - `monitoring_contract` (Thesis 페이지): Thesis 완성 프롬프트 — 외부 대화 마무리용
      5개 필드 산출: [THESIS][RISK][KEY_ASSUMPTIONS][VALUATION][MONITORING_CONTRACT]
      기존 thesis 컨텍스트 미포함 — 외부 대화 내용 그대로 구조화
  - `thesis_revision` (Thesis 페이지): Break Monitor 신호 기반 Thesis 재검토 프롬프트
  - thesis_challenge (반대 논거 탐색): 제거됨 — 외부 대화 중 자연스럽게 질문으로 대체
- API: GET /api/reports/explore-prompt?type=... (전체 포트폴리오 기준)
       GET /api/tickers/{id}/explore-prompt?type=... (종목별 보고서/thesis 포함)

### macro-report/SKILL.md
- 3섹션: market_overview / macro_factors / portfolio_implication
- max_tokens=4096

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

### Thesis 입력
- **직접 입력 플로우**: 외부 Claude → 심층 분석 → Thesis 완성 프롬프트 → 5개 필드 산출 → 앱 "Thesis 작성" 모달 붙여넣기
- **전체 붙여넣기 파싱**: [THESIS][RISK][KEY_ASSUMPTIONS][VALUATION][MONITORING_CONTRACT] 헤더 자동 인식
- **stock_type**: 결과 태깅용 레이블 (외부 대화에서 결정된 유형 선택)
- **bulk Thesis 생성 없음**: Dashboard 일괄 생성 없음. 각 종목 외부 탐색 후 개별 직접 입력
- **bulk-analyze 엔드포인트**: `POST /api/tickers/bulk-analyze` — Telegram bot 내부용만. 기존 thesis의 stock_type 사용

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
- **Yahoo quote change_pct 계산**: `regularMarketChangePercent` 우선 사용. 없으면 `(price - prev_close) / prev_close * 100` 계산. prev_close는 `regularMarketPreviousClose` → `chartPreviousClose` 순 fallback
- **portfolio_sync db.flush()**: upsert 완료 후 flush() 호출 — 거래 감지 쿼리가 동일 트랜잭션 내 최신 Portfolio 상태를 볼 수 있도록 보장
- **Valley 링크**: bulk(Dashboard 멀티셀렉트) 또는 단건(Thesis 헤더) 조회 가능. VALLEY_EMAIL/VALLEY_PASSWORD 환경변수 필수. FinancialCache(valley_url)에 30일 캐시. 단건 조회 시 프론트에서 3초 간격 polling (최대 60초)
- **수동 거래 기록**: `POST /api/tradelog` — KIS 동기화 없이 거래를 직접 입력. ticker_id, action, qty_before/after, avg_price_before/after, detected_at(optional), note(optional). Journal 수동 기록 모달에서 사용
- **종목 삭제**: `DELETE /api/tickers/{id}` — ORM cascade로 thesis/reports/portfolio/financial_cache/sec_filing_summaries 전부 삭제. Thesis 페이지 삭제 후 `/`로 navigate
- **아이디어 메모**: `/api/ideas` CRUD. ticker_symbol은 DB 종목 FK 없이 자유 텍스트 (대문자). Journal 페이지의 아이디어 탭에서 관리
- **자동매매 코드 작성 금지**
- **Thesis confirmed 변경은 반드시 사람의 명시적 액션으로만**
- **version_number 정렬**: 모든 쿼리에서 `.order_by(Thesis.version_number.desc().nullslast())` 필수 — PG 기본 NULLS FIRST 방지
- **Thesis.confirmed enum**: `_pg_enum` (values_callable) 사용 — 소문자 values(draft/confirmed/...) 저장. 순수 SAEnum은 name(대문자) 사용으로 불일치 발생
- **BreakSignal/InvestmentCycle 삭제**: thesis 버전 삭제 시 DB 레벨 CASCADE/SET NULL이 미적용 가능. 명시적 선행 처리 필수
- **thesis/direct 저장 후 getThesis**: thesis/direct 성공 후 프론트에서 getThesis 재호출 — version_number nullslast가 올바른 최신 draft 반환하는지 확인 필수
