# Value Investing Copilot — AGENTS.md

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
├── AGENTS.md
├── docker-compose.yml          # 로컬 개발용
├── docker-compose.prod.yml     # EC2 프로덕션용 (nginx + no reload)
├── deploy.sh                   # EC2 배포 스크립트
├── scripts/server-setup.sh     # EC2 최초 Docker 설치
├── .env.example
│
├── backend/                        # FastAPI
│   ├── main.py                     # DB create_all → enum 마이그레이션 → 라우터 등록
│   ├── models/
│   │   └── db.py                   # ORM 모델 + UniqueConstraint
│   ├── routes/
│   │   ├── tickers.py              # 종목 CRUD + analyze/refine/refresh-data/report/financial-data
│   │   ├── thesis.py               # Thesis CRUD + confirm
│   │   ├── reports.py              # 보고서 목록 + 트리거 + discovery + portfolio-review
│   │   └── market.py               # 시장 지표 API
│   ├── services/
│   │   ├── agent.py                # Agent Core — 모든 Codex 호출
│   │   ├── financial_data.py       # financialdatasets.ai API + DB 캐시 (US 종목)
│   │   ├── kr_financial_data.py    # OpenDART + yfinance (KR 종목)
│   │   ├── sec_pipeline.py         # EDGAR 공시 → Codex Haiku 요약 → DB
│   │   ├── scheduler.py            # 06:00 light_refresh / 07:00 briefing / 08:00 break_monitor
│   │   ├── market_data.py          # VIX / S&P500 / KOSPI / Fear&Greed
│   │   ├── portfolio_sync.py       # KIS API 동기화
│   │   ├── telegram.py             # notify_* 함수
│   │   └── telegram_bot.py         # /analyze /report /sync /macro 커맨드
│   └── .Codex/
│       └── skills/
│           ├── thesis-generator/
│           │   ├── SKILL.md
│           │   └── refs/           # value-investing / valuation-models / analysis-framework
│           ├── report-generator/
│           │   ├── SKILL.md
│           │   └── refs/           # buffett-skills 8개 파일 (2,141줄)
│           ├── daily-briefing/
│           │   └── SKILL.md
│           ├── break-monitor/
│           │   └── SKILL.md
│           ├── macro-report/
│           │   └── SKILL.md
│           ├── stock-discovery/
│           │   └── SKILL.md        # 투자 아이디어 → US+KR 유망 종목 탐색
│           └── portfolio-review/
│               └── SKILL.md        # 포트폴리오 전체 점검
│
└── frontend/                       # React + Vite
    ├── Dockerfile.prod             # 프로덕션 빌드 (node → nginx 멀티스테이지)
    ├── nginx.conf                  # SPA 라우팅 + /api/ 프록시 + SSE 지원
    └── src/
        ├── pages/
        │   ├── Dashboard.tsx       # 포트폴리오/관심 섹션 분리 + 현재가/등락/수익률 표시
        │   ├── Thesis.tsx          # Thesis탭 + 재무데이터탭 (재무제표/지표/공시 요약)
        │   └── Reports.tsx         # 보고서 히스토리 + Discovery + Portfolio Review
        ├── api.ts                  # fetch 래퍼 + SSE 스트림 헬퍼
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

# Report — 생성된 보고서 (누적, 삭제 없음)
Report:
  id: uuid
  ticker_id: uuid | null   # null = 전체 브리핑 / macro / discovery / portfolio_review
  type: enum               # analysis | daily_brief | macro | discovery | portfolio_review
  content: text            # <section name="..."> XML 태그 포맷
  created_at: datetime

# Portfolio — 보유 현황 (KIS 동기화)
Portfolio:
  id: uuid
  ticker_id: uuid (FK, unique)
  quantity: float
  avg_price: float
  current_price: float
  daily_pct: float
  updated_at: datetime

# FinancialCache — financialdatasets.ai API 응답 캐시
FinancialCache:
  id: uuid
  ticker_id: uuid (FK, CASCADE)
  data_type: str       # income|balance|cashflow|metrics|news|insider_trades|facts
  data: JSON
  fetched_at: datetime
  expires_at: datetime
  UNIQUE(ticker_id, data_type)   # 종목+타입 조합은 항상 1행

# SecFilingSummary — SEC 10-K/10-Q Codex 요약 (누적)
SecFilingSummary:
  id: uuid
  ticker_id: uuid (FK, CASCADE)
  filing_type: str     # 10-K | 10-Q
  report_period: str   # 2024 | 2024-Q3
  filing_url: text
  business_summary: text   # Item 1 요약
  risk_summary: text       # Item 1A 요약
  mda_summary: text        # Item 7 요약
  summarized_at: datetime
```

---

## 캐시 설계

```
FinancialCache TTL:
  income / balance / cashflow : 90일  (분기 공시 — 수동 갱신)
  metrics / news              : 24시간 (매일 06:00 자동 갱신)
  insider_trades              : 3일   (매일 06:00 자동 갱신)
  facts                       : 30일  (수동 갱신)

갱신 방식:
  수동 "데이터 갱신" 버튼 → 해당 종목 전체 캐시 삭제 + 재수집 + SEC 파이프라인
  06:00 light_refresh      → news / metrics / insider_trades만 overwrite (재무제표 건드리지 않음)
```

---

## 데이터 흐름

```
[종목 추가]
    ↓
[데이터 수집] (수동, "데이터 갱신" 버튼)
  US: financialdatasets.ai → FinancialCache (7종 데이터)
      EDGAR HTML → Codex Haiku 요약 → SecFilingSummary
  KR: OpenDART → FinancialCache (income/news/insider_trades/facts)
      yfinance (.KS/.KQ 자동 판별) → FinancialCache (metrics)
    ↓
[AI 분석] ("AI 분석" 버튼)
  FinancialCache 조회 → financial_context 구성
  → Codex Sonnet → Thesis 4섹션 초안 (실제 수치 기반)
    ↓
[피드백 루프] (선택, 반복 가능)
  사람 피드백 → Codex Sonnet → 수정된 Thesis (기존 수치 유지)
    ↓
[Confirm] (사람만)
  draft / needs_review → confirmed
  Break Monitor 활성화 (daily_alert=True 종목)
    ↓
[보고서 생성] (수동, 데이터 수집 후에만 가능)
  FinancialCache + SecFilingSummary + Thesis
  → Codex Sonnet (max_tokens=8192) → 8섹션 심층 보고서

[보고서 탭 추가 기능]
  종목 탐색   : 투자 아이디어 입력 → US+KR 유망 종목 SSE 스트리밍 → DB 저장
  포트폴리오 점검: KIS 동기화 데이터 + Thesis + Metrics → 5섹션 점검 보고서

[매일 자동]
  06:00  light_refresh  : news/metrics/insider_trades 갱신
  07:00  daily_briefing : 뉴스 + 포트폴리오 현황 + 매크로 지표 → 브리핑
  08:00  break_monitor  : confirmed 종목 뉴스 + metrics → thesis 이탈 감지
```

---

## 상태 머신 규칙

```
(빈값/신규)
    ↓ AI 분석 실행 (재무 데이터 있으면 실제 수치 기반)
  draft          ← AI 초안 완성. Break Monitor 비활성.
    ↓ [선택] 피드백 → 수정 반복
    ↓ 사람이 confirm 버튼
  confirmed      ← Break Monitor 활성 (daily_alert=True 시).
    ↓ /analyze 재실행 후 저장
  needs_review   ← AI 업데이트 제안. Break Monitor 비활성.
    ↓ 사람이 confirm 버튼
  confirmed
```

**규칙:**
- `confirmed` 상태가 아니면 Break Monitor 절대 발동하지 않음
- AI가 임의로 `confirmed`로 바꾸지 않음 — 반드시 사람 액션 필요
- `/analyze` 저장 시: `confirmed` → `needs_review`, 그 외 → `draft`

---

## 기술 스택

```
Frontend   React 18 + TypeScript + Vite + Tailwind CSS
           SSE (fetch + ReadableStream) — POST 지원 위해 EventSource 대신 사용
           ref: virattt/ai-hedge-fund (app/frontend)

Backend    Python 3.11 + FastAPI + SSE
           APScheduler (06:00 / 07:00 / 08:00 KST 3개 job)
           ref: ginlix-ai/LangAlpha

Agent      Anthropic API
           - Codex-sonnet-4-6: thesis / report / break_monitor / briefing / discovery / portfolio-review
           - Codex-haiku-4-5-20251001: SEC 공시 섹션 요약 (비용 절감)
           SKILL.md 기반 스킬 시스템
           Scratchpad: .scratchpad/*.jsonl (모든 Codex 호출 로그)
           ref: virattt/dexter

DB         PostgreSQL 15 (프로덕션: EC2 3.26.145.173, 로컬 sync 없음)
           - FinancialCache: TTL 기반 API 캐시 (종목별 overwrite)
           - SecFilingSummary: 공시 요약 누적 (period별 고유)
           - Report: 보고서 누적 (삭제 없음, 최신 배지 UI)
           ref: ginlix-ai/LangAlpha

External   financialdatasets.ai: US 종목 재무 데이터 (free tier: 연간 3년, limit=10)
           SEC EDGAR: 10-K/10-Q HTML 공시 원문
           OpenDART: KR 종목 재무제표 / 공시 / 임원 주식 변동
           yfinance: KR 종목 시장 지표 (KOSPI=.KS / KOSDAQ=.KQ 자동 판별)
           KIS API: 포트폴리오 동기화 (5개 계좌)

Messaging  python-telegram-bot

Deploy     EC2 (ap-southeast-2, 3.26.145.173) + Docker Compose + nginx
           nginx: 포트 80, React 정적 서빙 + /api/ 프록시 (SSE 지원)
           배포: ./deploy.sh (rsync + docker compose up --build)
```

---

## Agent Skills 상세

### thesis-generator/SKILL.md
- 재무 데이터 있으면 실제 수치 기반으로 thesis 생성 (없으면 graceful fallback)
- 버핏 8문항 Quick Filter 포함
- key_assumptions는 측정 가능한 수치로 작성 (Break Monitor 모니터링 기준)
- refs: value-investing.md / valuation-models.md / analysis-framework.md

### report-generator/SKILL.md
- 월가 수준 8섹션: business_overview / moat_analysis / financial_analysis / management_quality / valuation / risk_matrix / recent_developments / investment_conclusion
- 입력: 5년 재무제표 + Key Metrics TTM + 뉴스 + 인사이더 거래 + SEC 공시 요약 + 기존 thesis
- refs: buffett-skills 8개 파일 (2,141줄) — 버핏 투자 철학 전체

### daily-briefing/SKILL.md
- 입력: 뉴스 캐시(종목별 3건) + 포트폴리오 현재가/등락 + 매크로 지표
- 뉴스 필터: 주가/목표가/애널리스트 의견 무시, thesis 관련 사건만 언급
- Mr. Market 관점: 가격 등락이 아니라 thesis 변화 여부 기준으로 서술

### break-monitor/SKILL.md
- confirmed + daily_alert=True 종목만 대상
- 입력: thesis + key_assumptions + 뉴스 7건 + Key Metrics TTM
- 뉴스 필터 (무시): 주가 등락 / 목표가 / 애널리스트 의견 / 단기 beat/miss
- 뉴스 신호 (사용): 경영진 교체 / 사업 구조 변화 / 주요 계약 / 규제 이슈 / 자본배분 결정
- 출력: intact / weakening / broken + 근거

### macro-report/SKILL.md
- VIX / S&P500 / KOSPI / Fear&Greed 기반 매크로 분석
- 포트폴리오 영향 섹션 포함

### stock-discovery/SKILL.md
- 투자 아이디어(자유 텍스트) 입력 → 가치투자 렌즈로 US+KR 유망 종목 탐색
- 5섹션: theme_analysis / us_picks / kr_picks / screening_criteria / next_steps
- 노이즈 필터: 주가/목표가/애널리스트 의견 제외, 모트/FCF/ROE 기준으로 선별

### portfolio-review/SKILL.md
- KIS 동기화 포트폴리오 전체 점검 (보유 현황 + Thesis + Key Metrics)
- 5섹션: portfolio_overview / holdings_assessment / concentration_risk / thesis_health_check / action_items
- 핵심 원칙: 가격 하락 ≠ 매도 이유, thesis 이탈 여부만 판단

---

## 참고 레포 활용 현황

```
virattt/dexter
  → agent.py Plan→Execute→Validate 구조
  → .scratchpad/ JSONL 로깅

liangdabiao/Codex-Stock-Deep-Research-Agent
  → 8단계 분석 프레임워크 → thesis-generator refs/

agi-now/buffett-skills
  → report-generator/refs/ 8개 파일로 복사 (2,141줄)
  → thesis-generator/refs/ value-investing.md

virattt/ai-hedge-fund
  → financialdatasets.ai API 래퍼 패턴 (financial_data.py)
  → React + SSE 스트리밍 UI 패턴

ginlix-ai/LangAlpha
  → Docker Compose + PostgreSQL 구조
  → Background Task Manager 패턴
```

---

## 환경 변수 (.env)

```bash
ANTHROPIC_API_KEY=

DATABASE_URL=postgresql://value_copilot:value_copilot@localhost:5432/value_copilot
REDIS_URL=redis://localhost:6379

TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

KIS_APP_KEY=
KIS_APP_SECRET=
KIS_ACCOUNT_NO=

FINANCIAL_DATASETS_API_KEY=   # US 종목 재무 데이터
OPENDART_API_KEY=             # KR 종목 재무제표 / 공시 (OpenDART)
```

---

## 개발 & 배포

```bash
# 로컬 개발
docker compose up -d          # 전체 스택 (postgres + redis + backend + frontend dev)
docker compose up -d --build  # 의존성 변경 후

# EC2 프로덕션 배포
./deploy.sh                   # 파일 전송 + 빌드 + 재시작 (약 2분 소요)

# 최초 서버 설정 (Docker 미설치 상태)
./scripts/server-setup.sh

# 접속
# 로컬: http://localhost:5173
# 프로덕션: http://3.26.145.173
```

---

## 주의사항

- **데이터 수집 선행 필수**: AI 분석 / 보고서 생성 전 반드시 "데이터 갱신" 버튼 클릭
- **보고서 생성 조건**: FinancialCache에 데이터 있어야만 활성화 (백엔드 400 반환)
- **보고서는 누적 보존**: 삭제 없음. 실적 전후 비교가 가치투자 검증의 핵심
- **KR 종목 데이터**: OpenDART(재무제표/공시) + yfinance(시장지표). KOSPI=`.KS`, KOSDAQ=`.KQ` 자동 판별
- **KR balance/cashflow**: DART `fnlttSinglAcntAll` 단일 호출로 IS/BS/CF 모두 추출 (중복 API 호출 없음)
- **SEC 파이프라인**: 보고서 생성 전 자동 실행. EDGAR 응답 없으면 non-fatal skip
- **free tier 제한**: financialdatasets.ai news limit=10 / 연간 데이터 3년
- **자동매매 코드 작성 금지**
- **Thesis confirmed 변경은 반드시 사람의 명시적 액션으로만**
