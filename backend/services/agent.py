"""
Agent Core — Plan → Execute → Validate
SKILL.md 기반 스킬 시스템. Anthropic Streaming API 사용.
Scratchpad: /app/.scratchpad/YYYY-MM-DD.jsonl 에 모든 이벤트 로그.
"""
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Iterator

import anthropic
import yaml

logger = logging.getLogger(__name__)

SKILLS_DIR = Path(__file__).parent.parent / ".claude" / "skills"
SCRATCHPAD_DIR = Path(os.environ.get("SCRATCHPAD_DIR", "/app/.scratchpad"))


# ── Scratchpad ────────────────────────────────────────────────────────────────

def _log(event: dict):
    try:
        SCRATCHPAD_DIR.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        log_file = SCRATCHPAD_DIR / f"{today}.jsonl"
        entry = {**event, "ts": datetime.now().isoformat()}
        with open(log_file, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass  # 로깅 실패가 메인 흐름을 막으면 안 됨


# ── Skill Loader ──────────────────────────────────────────────────────────────

def _load_skill(skill_name: str) -> dict:
    """SKILL.md 파싱 → {name, description, instructions, refs_dir}"""
    skill_path = SKILLS_DIR / skill_name / "SKILL.md"
    if not skill_path.exists():
        raise FileNotFoundError(f"SKILL.md not found: {skill_path}")

    content = skill_path.read_text(encoding="utf-8")
    if content.startswith("---"):
        parts = content.split("---", 2)
        frontmatter = yaml.safe_load(parts[1]) if len(parts) > 1 else {}
        body = parts[2].strip() if len(parts) > 2 else ""
    else:
        frontmatter = {}
        body = content.strip()

    return {
        "name": frontmatter.get("name", skill_name),
        "description": frontmatter.get("description", ""),
        "instructions": body,
        "refs_dir": SKILLS_DIR / skill_name / "refs",
    }


def _load_refs(refs_dir: Path) -> str:
    if not refs_dir.exists():
        return ""
    parts = []
    for f in sorted(refs_dir.glob("*.md")):
        parts.append(f"## [{f.stem}]\n\n{f.read_text(encoding='utf-8')}")
    return "\n\n---\n\n".join(parts)


# ── Thesis Generator ──────────────────────────────────────────────────────────

SECTION_NAMES = ["thesis", "risk", "key_assumptions", "valuation", "monitoring_contract"]
THESIS_MAX_TOKENS = 8192

def _build_thesis_user_message(
    symbol: str, name: str, market: str, financial_context: str = "",
    stock_type: str = "", seed_memo: str = "", exploration_note: str = "",
    monitoring_contract: str = "",
) -> str:
    fin_block = (
        f"\n{financial_context}\n"
        if financial_context
        else "\n*(재무 데이터 미제공 — 공개 정보 기반으로 작성하되 불확실한 수치는 '데이터 수집 필요'로 표시)*\n"
    )
    exploration_block = (
        f"\n**외부 탐색 인사이트 (exploration_note)**\n{exploration_note}\n"
        if exploration_note
        else ""
    )
    monitoring_block = (
        f"\n**외부 대화에서 확정한 Monitoring Contract**\n{monitoring_contract}\n"
        if monitoring_contract
        else ""
    )
    return f"""다음 종목의 투자 thesis를 생성해 주세요.

**종목 정보**
- 심볼: {symbol}
- 회사명: {name}
- 시장: {market}
- 투자 유형 (stock_type): {stock_type}

**나의 초기 관점 (seed_memo)**
{seed_memo}
{exploration_block}{monitoring_block}{fin_block}
위 초기 관점과 투자 유형 프레임워크를 기반으로 아래 5개 섹션을 XML 태그로 감싸서 출력해 주세요.
각 섹션은 마크다운으로 작성하고 충분한 분량(섹션당 최소 200자)으로 작성하세요.
재무 데이터가 제공된 경우 실제 수치를 반드시 인용하고, valuation 섹션의 가정은 제공된 재무 데이터와 선택된 프레임워크를 근거로 작성하세요.
Monitoring Contract가 제공된 경우 새로 발명하지 말고, 외부 대화에서 확정한 논리를 우선 보존하되 재무 데이터와 충돌하는 수치만 보수적으로 정정하세요.

<section name="thesis">투자 논거 (핵심 thesis, 비즈니스 모델, 투자 유형에 맞는 핵심 강점)</section>
<section name="risk">주요 리스크 (사업 리스크, 재무 리스크, 시장 리스크, 외부 요인)</section>
<section name="key_assumptions">핵심 가정 (thesis가 유효하려면 참이어야 할 조건들 — 투자 유형 기준으로, 측정 가능한 수치 기반으로)</section>
<section name="valuation">밸류에이션 (투자 유형에 맞는 방법론, 적정가 추정)</section>
<section name="monitoring_contract">Break Monitor가 그대로 사용할 감시 계약서. Core Logic / Break Conditions / Strengthening Signals / Watch Metrics 형식으로 작성</section>
"""


def generate_thesis_stream(
    symbol: str,
    name: str,
    market: str,
    ticker_id: str,
    financial_context: str = "",
    stock_type: str = "compounding",
    seed_memo: str = "",
    exploration_note: str = "",
    monitoring_contract: str = "",
) -> Iterator[str]:
    """
    Thesis 5섹션 AI 초안을 SSE 이벤트로 스트림.
    financial_context: fetch_all() 결과를 포맷한 문자열 (없으면 종목명만으로 생성).
    stock_type: 투자 유형 (compounding/growth/asset_play/turnaround/cyclical/special_situation)
    seed_memo: 사용자의 초기 관점 (필수)

    이벤트 타입:
      - start   : 생성 시작
      - chunk   : 텍스트 청크 (실시간 스트리밍)
      - complete: 완료 + 파싱된 5섹션
      - error   : 오류
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        yield f"data: {json.dumps({'type': 'error', 'message': 'ANTHROPIC_API_KEY not set'})}\n\n"
        return

    _log({"event": "thesis_start", "ticker_id": ticker_id, "symbol": symbol,
          "has_financial_data": bool(financial_context), "stock_type": stock_type})

    # Load skill
    try:
        skill = _load_skill("thesis-generator")
    except FileNotFoundError as e:
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        return

    system_prompt = skill["instructions"]
    # stock_type별 프레임워크 파일 동적 로드 (asset_play → asset_play.md)
    framework_path = skill["refs_dir"] / f"{stock_type}.md"
    if framework_path.exists():
        framework = framework_path.read_text(encoding="utf-8")
        system_prompt += f"\n\n---\n\n# 투자 프레임워크 ({stock_type})\n\n{framework}"

    user_message = _build_thesis_user_message(
        symbol,
        name,
        market,
        financial_context,
        stock_type=stock_type,
        seed_memo=seed_memo,
        exploration_note=exploration_note,
        monitoring_contract=monitoring_contract,
    )

    yield f"data: {json.dumps({'type': 'start', 'symbol': symbol})}\n\n"

    client = anthropic.Anthropic(api_key=api_key)
    full_text = ""

    try:
        with client.messages.stream(
            model="claude-sonnet-4-6",
            max_tokens=THESIS_MAX_TOKENS,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        ) as stream:
            for text in stream.text_stream:
                full_text += text
                yield f"data: {json.dumps({'type': 'chunk', 'text': text})}\n\n"

    except anthropic.APIError as e:
        _log({"event": "thesis_error", "ticker_id": ticker_id, "error": str(e)})
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        return

    # Parse sections
    sections = {}
    for sec in SECTION_NAMES:
        pattern = rf'<section name="{sec}">(.*?)</section>'
        m = re.search(pattern, full_text, re.DOTALL)
        sections[sec] = m.group(1).strip() if m else ""

    _log({
        "event": "thesis_complete",
        "ticker_id": ticker_id,
        "symbol": symbol,
        "sections_found": [s for s in SECTION_NAMES if sections.get(s)],
    })

    yield f"data: {json.dumps({'type': 'complete', 'sections': sections})}\n\n"


def refine_thesis_stream(
    symbol: str,
    name: str,
    market: str,
    ticker_id: str,
    current_sections: dict,
    feedback: str,
) -> Iterator[str]:
    """
    기존 thesis + 사람 피드백을 기반으로 thesis를 재생성 (SSE 스트림).
    이벤트 형식은 generate_thesis_stream 과 동일.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        yield f"data: {json.dumps({'type': 'error', 'message': 'ANTHROPIC_API_KEY not set'})}\n\n"
        return

    _log({"event": "thesis_refine_start", "ticker_id": ticker_id, "symbol": symbol})

    try:
        skill = _load_skill("thesis-generator")
    except FileNotFoundError as e:
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        return

    refs = _load_refs(skill["refs_dir"])
    system_prompt = skill["instructions"]
    if refs:
        system_prompt += f"\n\n---\n\n# Reference Materials\n\n{refs}"

    def fmt_section(key: str, label: str) -> str:
        content = current_sections.get(key, "").strip()
        return f"<section name=\"{key}\">\n{content}\n</section>" if content else f"<section name=\"{key}\">(없음)</section>"

    user_message = f"""다음 종목의 기존 가치투자 thesis를 사람의 피드백에 맞게 수정해 주세요.

**종목 정보**
- 심볼: {symbol}
- 회사명: {name}
- 시장: {market}

**기존 Thesis (현재 초안)**
{fmt_section("thesis", "투자 논거")}
{fmt_section("risk", "리스크")}
{fmt_section("key_assumptions", "핵심 가정")}
{fmt_section("valuation", "밸류에이션")}
{fmt_section("monitoring_contract", "Monitoring Contract")}

**사람의 피드백 (이 내용을 반드시 반영하여 수정하세요)**
{feedback}

피드백을 충실히 반영하되, 피드백이 언급하지 않은 섹션도 전체적 일관성을 위해 필요 시 보완하세요.
아래 5개 섹션을 각각 XML 태그로 감싸서 출력해 주세요.
각 섹션은 마크다운으로 작성하고 충분한 분량(섹션당 최소 200자)으로 작성하세요.
기존 thesis에 실제 재무 수치가 포함되어 있으면 그 수치를 유지하거나 더 보완하세요.

<section name="thesis">투자 논거 (핵심 thesis, 비즈니스 모델, 경쟁우위, 성장 동인)</section>
<section name="risk">주요 리스크 (사업 리스크, 재무 리스크, 시장 리스크, 외부 요인)</section>
<section name="key_assumptions">핵심 가정 (thesis가 유효하려면 참이어야 할 조건들 — 측정 가능한 수치 기반으로)</section>
<section name="valuation">밸류에이션 (DCF 가정, 적정가 추정, Margin of Safety)</section>
<section name="monitoring_contract">Break Monitor가 그대로 사용할 감시 계약서. Core Logic / Break Conditions / Strengthening Signals / Watch Metrics 형식으로 작성</section>
"""

    yield f"data: {json.dumps({'type': 'start', 'symbol': symbol})}\n\n"

    client = anthropic.Anthropic(api_key=api_key)
    full_text = ""

    try:
        with client.messages.stream(
            model="claude-sonnet-4-6",
            max_tokens=THESIS_MAX_TOKENS,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        ) as stream:
            for text in stream.text_stream:
                full_text += text
                yield f"data: {json.dumps({'type': 'chunk', 'text': text})}\n\n"

    except anthropic.APIError as e:
        _log({"event": "thesis_refine_error", "ticker_id": ticker_id, "error": str(e)})
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        return

    sections = {}
    for sec in SECTION_NAMES:
        pattern = rf'<section name="{sec}">(.*?)</section>'
        m = re.search(pattern, full_text, re.DOTALL)
        sections[sec] = m.group(1).strip() if m else ""

    _log({
        "event": "thesis_refine_complete",
        "ticker_id": ticker_id,
        "symbol": symbol,
        "sections_found": [s for s in SECTION_NAMES if sections.get(s)],
    })

    yield f"data: {json.dumps({'type': 'complete', 'sections': sections})}\n\n"


def generate_thesis(
    symbol: str,
    name: str,
    market: str,
    ticker_id: str,
    financial_context: str = "",
    stock_type: str = "compounding",
    seed_memo: str = "",
    exploration_note: str = "",
    monitoring_contract: str = "",
) -> dict:
    """Non-streaming version for bulk/Telegram. Returns sections dict."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    _log({"event": "thesis_start", "ticker_id": ticker_id, "symbol": symbol, "mode": "sync",
          "has_financial_data": bool(financial_context), "stock_type": stock_type})

    skill = _load_skill("thesis-generator")
    system_prompt = skill["instructions"]
    framework_path = skill["refs_dir"] / f"{stock_type}.md"
    if framework_path.exists():
        framework = framework_path.read_text(encoding="utf-8")
        system_prompt += f"\n\n---\n\n# 투자 프레임워크 ({stock_type})\n\n{framework}"

    user_message = _build_thesis_user_message(
        symbol,
        name,
        market,
        financial_context,
        stock_type=stock_type,
        seed_memo=seed_memo,
        exploration_note=exploration_note,
        monitoring_contract=monitoring_contract,
    )

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=THESIS_MAX_TOKENS,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    full_text = message.content[0].text

    sections = {}
    for sec in SECTION_NAMES:
        pattern = rf'<section name="{sec}">(.*?)</section>'
        m = re.search(pattern, full_text, re.DOTALL)
        sections[sec] = m.group(1).strip() if m else ""

    _log({"event": "thesis_complete", "ticker_id": ticker_id, "symbol": symbol, "mode": "sync"})
    return sections


# ── Daily Briefing ────────────────────────────────────────────────────────────



def generate_weekly_briefing(
    portfolio_summary: list[dict],
    macro_context: str = "",
    signal_summaries: list[str] | None = None,
) -> dict:
    """주간 브리핑 생성 (월요일 08:00). 반환: {break_summary, upcoming_events, macro_changes, full_text}"""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    _log({"event": "weekly_briefing_start", "portfolio_count": len(portfolio_summary),
          "signals_count": len(signal_summaries or [])})

    skill = _load_skill("weekly-briefing")
    system_prompt = skill["instructions"]

    macro_block = f"\n## 매크로 지표\n{macro_context}\n" if macro_context else ""
    portfolio_block = "\n".join(
        f"- {t['name']} ({t['symbol']}, {t.get('status', '')})"
        for t in portfolio_summary
    ) or "없음"
    signals_block = ""
    if signal_summaries:
        signals_block = "\n## 지난주 Break Monitor 관찰 이력\n" + "\n".join(f"- {s}" for s in signal_summaries) + "\n"

    user_message = f"""이번 주 투자 모니터링 브리핑을 생성해 주세요.
{macro_block}{signals_block}
## 모니터링 대상 종목
{portfolio_block}

3개 섹션을 XML 태그로 감싸서 출력해 주세요.
"""

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    full_text = message.content[0].text

    sections: dict = {"full_text": full_text}
    for sec in ["break_summary", "upcoming_events", "macro_changes"]:
        pattern = rf'<section name="{sec}">(.*?)</section>'
        m = re.search(pattern, full_text, re.DOTALL)
        sections[sec] = m.group(1).strip() if m else ""

    _log({"event": "weekly_briefing_complete"})
    return sections


# ── Ticker Report (Deep Research) ─────────────────────────────────────────────

REPORT_SECTIONS = [
    "business_overview",
    "competitive_position",
    "financial_analysis",
    "management_track_record",
    "valuation",
    "risk_matrix",
    "recent_developments",
    "bull_bear_synthesis",
]


def generate_ticker_report(
    symbol: str,
    name: str,
    market: str = "US_Stock",
    ticker_id: str = "",
    thesis: str = "",
    risk: str = "",
    key_assumptions: str = "",
    valuation: str = "",
    db=None,
) -> dict:
    """
    종목 심층 보고서 생성.
    실제 재무 데이터 + SEC 공시 요약 + 기존 thesis 컨텍스트 활용.
    반환: {business_overview, competitive_position, financial_analysis, management_track_record,
           valuation, risk_matrix, recent_developments, bull_bear_synthesis, full_text}
    """
    from services.financial_data import fetch_all
    from services.sec_pipeline import get_sec_context

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    _log({"event": "report_start", "ticker_id": ticker_id, "symbol": symbol})

    # ── 1. 재무 데이터 수집 (DB 캐시 우선) ────────────────────────────────────
    fin = fetch_all(symbol, ticker_id=ticker_id, db=db, market=market)
    _log({
        "event": "report_data_fetched",
        "ticker_id": ticker_id,
        "symbol": symbol,
        "has_data": fin["has_data"],
    })

    # ── 2. 스킬 로드 ─────────────────────────────────────────────────────────
    skill = _load_skill("report-generator")
    system_prompt = skill["instructions"]

    # ── 3. SEC 공시 요약 (DB에서 조회) ──────────────────────────────────────
    sec_context = ""
    if db and ticker_id:
        sec_context = get_sec_context(ticker_id, db, limit=2)
        if sec_context:
            _log({"event": "sec_context_loaded", "ticker_id": ticker_id})

    # ── 4. 기존 thesis 컨텍스트 (있으면 참고용으로만) ─────────────────────────
    thesis_context = ""
    if any([thesis, risk, key_assumptions, valuation]):
        thesis_context = f"""
### 기존 투자 Thesis (참고용 — 데이터와 대조하여 검증할 것)
**Thesis**: {thesis or '(없음)'}
**Risk**: {risk or '(없음)'}
**Key Assumptions**: {key_assumptions or '(없음)'}
**Valuation**: {valuation or '(없음)'}
"""

    user_message = f"""다음 종목에 대해 심층 분석 보고서를 작성해 주세요.

## 종목 정보
- 심볼: {symbol}
- 회사명: {name}
- 시장: {market}
{fin['company_info']}

## 재무 데이터 (분석 참고용 — 수치 재인용 최소화)

### Income Statement (연간, 최근 5년)
{fin['income_table']}

### Cash Flow Statement (연간, 최근 5년)
{fin['cf_table']}

### Balance Sheet (연간, 최근 5년)
{fin['bs_table']}

### Key Metrics (TTM)
{fin['key_metrics']}

### Insider Trades (최근 10건) — 경영진 매수/매도 신호
{fin['insider_trades']}

### 최근 뉴스 (최근 8건)
{fin['news']}
{("### " + ("DART 공시 요약 (사업보고서/반기보고서)" if market == "KR_Stock" else "SEC 공시 원문 요약 (10-K/10-Q)") + chr(10) + sec_context) if sec_context else ""}
{thesis_context}
---

위 데이터를 분석하여 8개 섹션을 XML 태그로 감싸서 출력해 주세요.

**작성 지침**:
- 재무 수치를 그대로 나열하지 말 것. 수치가 말하는 방향성·추세·의미를 서술할 것.
- 꼭 필요한 경우에만 대표 수치 1~2개 인용 — 나머지는 "개선", "둔화", "안정적" 등 방향 표현 사용.
- Insider Trades는 management_track_record에서 주목할 패턴 위주로 해석.
- SEC/DART 공시가 있으면 recent_developments와 risk_matrix에서 핵심 내용 반영.
- 데이터가 없는 항목은 "데이터 미확인" 표기 후 정성적 분석으로 대체.
- bull_bear_synthesis는 반드시 포함할 것.
"""

    # ── 5. Claude 호출 ────────────────────────────────────────────────────────
    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=16000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    full_text = message.content[0].text

    sections: dict = {"full_text": full_text}
    for sec in REPORT_SECTIONS:
        pattern = rf'<section name="{sec}">(.*?)</section>'
        m = re.search(pattern, full_text, re.DOTALL)
        sections[sec] = m.group(1).strip() if m else ""

    _log({"event": "report_complete", "ticker_id": ticker_id, "symbol": symbol})
    return sections


# ── Break Monitor ─────────────────────────────────────────────────────────────

def run_break_monitor(
    symbol: str,
    name: str,
    ticker_id: str,
    key_logic: str = "",
    monitoring_contract: str = "",
    key_assumptions: str = "",
    news_context: str = "",
    metrics_context: str = "",
    stock_type: str = "",
) -> dict:
    """
    Break Monitor 실행. LLM은 관찰만 출력, 판정(verdict)은 사람이 내림.
    monitoring_contract: 사람이 confirmed한 감시 계약서 (최우선)
    key_logic: legacy 논리 스냅샷 (contract 없으면 기존 데이터 호환용으로 사용)
    반환: {observations, positive_signals, negative_signals, watch_items, key_logic_snapshot, full_text}
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    _log({"event": "break_monitor_start", "ticker_id": ticker_id, "symbol": symbol,
          "has_contract": bool(monitoring_contract), "has_key_logic": bool(key_logic), "has_news": bool(news_context)})

    skill = _load_skill("break-monitor")
    system_prompt = skill["instructions"]

    monitoring_criterion = monitoring_contract or key_logic or key_assumptions
    criterion_label = (
        "Monitoring Contract"
        if monitoring_contract
        else ("legacy 논리 스냅샷" if key_logic else "핵심 가정 (key_assumptions)")
    )

    news_block = f"\n## 최근 뉴스 (오늘 기준)\n{news_context}\n" if news_context else "\n*(뉴스 데이터 없음)*\n"
    metrics_block = f"\n## 현재 Key Metrics (TTM)\n{metrics_context}\n" if metrics_context else ""
    stock_type_block = f"\n**투자 유형**: {stock_type}\n" if stock_type else ""

    user_message = f"""다음 종목에 대해 오늘의 변화를 관찰해 주세요.

**종목**: {symbol} — {name}
{stock_type_block}
**{criterion_label}**
{monitoring_criterion or '(없음 — 공개 정보 기반으로 주요 변화 서술)'}
{news_block}{metrics_block}
4개 섹션(observations, positive_signals, negative_signals, watch_items)을 출력해 주세요.
verdict(판정)는 출력하지 마세요.
"""

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=800,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    full_text = message.content[0].text

    result: dict = {"full_text": full_text, "key_logic_snapshot": monitoring_contract or key_logic}
    for sec in ["observations", "positive_signals", "negative_signals", "watch_items"]:
        m = re.search(rf'<section name="{sec}">(.*?)</section>', full_text, re.DOTALL)
        result[sec] = m.group(1).strip() if m else ""

    _log({"event": "break_monitor_complete", "ticker_id": ticker_id, "symbol": symbol})
    return result


def generate_retrospective(
    original_logic: str,
    pnl_pct: float | None = None,
    exit_reason: str = "",
    signal_summaries: list[str] | None = None,
) -> dict:
    """복기 초안 생성. 반환: {what_changed, weak_link, next_time}"""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    _log({"event": "retrospective_start"})

    skill = _load_skill("thesis-postmortem")
    system_prompt = skill["instructions"]

    pnl_block = f"\n**투자 결과**: {pnl_pct:+.1f}%\n" if pnl_pct is not None else ""
    reason_block = f"\n**청산 이유**: {exit_reason}\n" if exit_reason else ""
    signals_block = ""
    if signal_summaries:
        signals_block = "\n## 보유 기간 Break Monitor 관찰 이력\n" + "\n".join(f"- {s}" for s in signal_summaries) + "\n"

    user_message = f"""다음 투자의 복기 초안을 작성해 주세요.

## 진입 당시 Monitoring Contract / 논리 스냅샷 (변경 불가)
{original_logic}
{pnl_block}{reason_block}{signals_block}
3개 섹션(what_changed, weak_link, next_time)을 XML 태그로 감싸서 출력해 주세요.
"""

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    full_text = message.content[0].text

    result: dict = {"full_text": full_text}
    for sec in ["what_changed", "weak_link", "next_time"]:
        m = re.search(rf'<section name="{sec}">(.*?)</section>', full_text, re.DOTALL)
        result[sec] = m.group(1).strip() if m else ""

    _log({"event": "retrospective_complete"})
    return result


# ── Macro Report ──────────────────────────────────────────────────────────────

def generate_macro_report(indicators: dict) -> dict:
    """매크로 보고서 생성. 반환: {market_overview, macro_factors, portfolio_implication, full_text}"""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    _log({"event": "macro_report_start"})

    skill = _load_skill("macro-report")
    system_prompt = skill["instructions"]

    def fmt(d: dict | None, key: str, suffix: str = "") -> str:
        if not d:
            return "데이터 없음"
        return f"{d.get(key, 'N/A')}{suffix} (전일대비 {d.get('change_pct', 'N/A')}%)" if "change_pct" in d else f"{d.get(key, 'N/A')}{suffix}"

    vix = indicators.get("vix")
    sp500 = indicators.get("sp500")
    kospi = indicators.get("kospi")
    fg = indicators.get("fear_greed")

    user_message = f"""현재 시장 지표를 바탕으로 매크로 보고서를 작성해 주세요.

**현재 시장 지표**
- VIX (공포지수): {fmt(vix, 'price')}
- S&P 500: {fmt(sp500, 'price', 'pt')}
- KOSPI: {fmt(kospi, 'price', 'pt')}
- Fear & Greed Index: {f"{fg['score']} ({fg['rating']})" if fg else '데이터 없음'}

3개 섹션을 XML 태그로 감싸서 출력해 주세요.
"""

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    full_text = message.content[0].text

    result: dict = {"full_text": full_text}
    for sec in ["market_overview", "macro_factors", "portfolio_implication"]:
        m = re.search(rf'<section name="{sec}">(.*?)</section>', full_text, re.DOTALL)
        result[sec] = m.group(1).strip() if m else ""

    _log({"event": "macro_report_complete"})
    return result
