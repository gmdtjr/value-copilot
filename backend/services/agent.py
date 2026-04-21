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

SECTION_NAMES = ["thesis", "risk", "key_assumptions", "valuation"]

def _build_thesis_user_message(
    symbol: str, name: str, market: str, financial_context: str = ""
) -> str:
    fin_block = (
        f"\n{financial_context}\n"
        if financial_context
        else "\n*(재무 데이터 미제공 — 공개 정보 기반으로 작성하되 불확실한 수치는 '데이터 수집 필요'로 표시)*\n"
    )
    return f"""다음 종목의 가치투자 thesis를 생성해 주세요.

**종목 정보**
- 심볼: {symbol}
- 회사명: {name}
- 시장: {market}
{fin_block}
아래 4개 섹션을 각각 XML 태그로 감싸서 출력해 주세요.
각 섹션은 마크다운으로 작성하고 충분한 분량(섹션당 최소 200자)으로 작성하세요.
재무 데이터가 제공된 경우 실제 수치를 반드시 인용하고, valuation 섹션의 DCF 가정은 제공된 재무 데이터를 근거로 작성하세요.

<section name="thesis">투자 논거 (핵심 thesis, 비즈니스 모델, 경쟁우위, 성장 동인)</section>
<section name="risk">주요 리스크 (사업 리스크, 재무 리스크, 시장 리스크, 외부 요인)</section>
<section name="key_assumptions">핵심 가정 (thesis가 유효하려면 참이어야 할 조건들 — 측정 가능한 수치 기반으로)</section>
<section name="valuation">밸류에이션 (DCF 가정, 적정가 추정, Margin of Safety)</section>
"""


def generate_thesis_stream(
    symbol: str,
    name: str,
    market: str,
    ticker_id: str,
    financial_context: str = "",
) -> Iterator[str]:
    """
    Thesis 4섹션 AI 초안을 SSE 이벤트로 스트림.
    financial_context: fetch_all() 결과를 포맷한 문자열 (없으면 종목명만으로 생성).

    이벤트 타입:
      - start   : 생성 시작
      - chunk   : 텍스트 청크 (실시간 스트리밍)
      - complete: 완료 + 파싱된 4섹션
      - error   : 오류
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        yield f"data: {json.dumps({'type': 'error', 'message': 'ANTHROPIC_API_KEY not set'})}\n\n"
        return

    _log({"event": "thesis_start", "ticker_id": ticker_id, "symbol": symbol,
          "has_financial_data": bool(financial_context)})

    # Load skill
    try:
        skill = _load_skill("thesis-generator")
    except FileNotFoundError as e:
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        return

    refs = _load_refs(skill["refs_dir"])
    system_prompt = skill["instructions"]
    if refs:
        system_prompt += f"\n\n---\n\n# Reference Materials\n\n{refs}"

    user_message = _build_thesis_user_message(symbol, name, market, financial_context)

    yield f"data: {json.dumps({'type': 'start', 'symbol': symbol})}\n\n"

    client = anthropic.Anthropic(api_key=api_key)
    full_text = ""

    try:
        with client.messages.stream(
            model="claude-sonnet-4-6",
            max_tokens=4096,
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

**사람의 피드백 (이 내용을 반드시 반영하여 수정하세요)**
{feedback}

피드백을 충실히 반영하되, 피드백이 언급하지 않은 섹션도 전체적 일관성을 위해 필요 시 보완하세요.
아래 4개 섹션을 각각 XML 태그로 감싸서 출력해 주세요.
각 섹션은 마크다운으로 작성하고 충분한 분량(섹션당 최소 200자)으로 작성하세요.
기존 thesis에 실제 재무 수치가 포함되어 있으면 그 수치를 유지하거나 더 보완하세요.

<section name="thesis">투자 논거 (핵심 thesis, 비즈니스 모델, 경쟁우위, 성장 동인)</section>
<section name="risk">주요 리스크 (사업 리스크, 재무 리스크, 시장 리스크, 외부 요인)</section>
<section name="key_assumptions">핵심 가정 (thesis가 유효하려면 참이어야 할 조건들 — 측정 가능한 수치 기반으로)</section>
<section name="valuation">밸류에이션 (DCF 가정, 적정가 추정, Margin of Safety)</section>
"""

    yield f"data: {json.dumps({'type': 'start', 'symbol': symbol})}\n\n"

    client = anthropic.Anthropic(api_key=api_key)
    full_text = ""

    try:
        with client.messages.stream(
            model="claude-sonnet-4-6",
            max_tokens=4096,
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
) -> dict:
    """Non-streaming version for Telegram bot. Returns sections dict."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    _log({"event": "thesis_start", "ticker_id": ticker_id, "symbol": symbol, "mode": "sync",
          "has_financial_data": bool(financial_context)})

    skill = _load_skill("thesis-generator")
    refs = _load_refs(skill["refs_dir"])
    system_prompt = skill["instructions"]
    if refs:
        system_prompt += f"\n\n---\n\n# Reference Materials\n\n{refs}"

    user_message = _build_thesis_user_message(symbol, name, market, financial_context)

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
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

BRIEFING_SECTIONS = ["macro", "portfolio_summary", "watchlist"]


def generate_daily_briefing(
    portfolio: list[dict],
    watchlist: list[dict],
    macro_context: str = "",
) -> dict:
    """
    데일리 브리핑 생성.
    portfolio/watchlist 항목에 news, daily_pct, current_price 포함 가능.
    반환: {macro, portfolio_summary, watchlist, full_text}
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    _log({"event": "briefing_start", "portfolio_count": len(portfolio), "watchlist_count": len(watchlist)})

    skill = _load_skill("daily-briefing")
    system_prompt = skill["instructions"]

    def fmt_ticker(t: dict) -> str:
        line = f"- **{t['symbol']}** ({t['name']}): thesis={t.get('thesis_status', 'none')}"
        if t.get("current_price"):
            pct = t.get("daily_pct", 0) or 0
            sign = "+" if pct >= 0 else ""
            line += f" | 현재가 ${t['current_price']:.2f} ({sign}{pct:.1f}%)"
        news = t.get("news_snippet", "")
        if news:
            line += f"\n  최근 뉴스:\n{news}"
        return line

    def fmt_tickers(items: list[dict]) -> str:
        return "\n".join(fmt_ticker(t) for t in items) if items else "없음"

    macro_block = f"\n## 오늘의 시장 지표\n{macro_context}\n" if macro_context else ""

    user_message = f"""오늘의 데일리 브리핑을 생성해 주세요.
{macro_block}
## 포트폴리오 종목
{fmt_tickers(portfolio)}

## 관심 종목
{fmt_tickers(watchlist)}

3개 섹션을 XML 태그로 감싸서 출력해 주세요.
"""

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    full_text = message.content[0].text

    sections: dict = {"full_text": full_text}
    for sec in BRIEFING_SECTIONS:
        pattern = rf'<section name="{sec}">(.*?)</section>'
        m = re.search(pattern, full_text, re.DOTALL)
        sections[sec] = m.group(1).strip() if m else ""

    _log({"event": "briefing_complete"})
    return sections


# ── Ticker Report (Deep Research) ─────────────────────────────────────────────

REPORT_SECTIONS = [
    "business_overview",
    "moat_analysis",
    "financial_analysis",
    "management_quality",
    "valuation",
    "risk_matrix",
    "recent_developments",
    "investment_conclusion",
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
    월가 수준 심층 보고서 생성.
    financialdatasets.ai 실제 재무 데이터 + SEC 공시 요약 + 기존 thesis 컨텍스트 활용.
    반환: {business_overview, moat_analysis, ..., investment_conclusion, full_text}
    참고: virattt/ai-hedge-fund, langalpha/initiating-coverage, agi-now/buffett-skills
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

    # ── 2. 스킬 로드 (buffett-skills refs 포함) ───────────────────────────────
    skill = _load_skill("report-generator")
    refs = _load_refs(skill["refs_dir"])
    system_prompt = skill["instructions"]
    if refs:
        system_prompt += f"\n\n---\n\n# Reference Materials (Buffett Investment Framework)\n\n{refs}"

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

    user_message = f"""다음 종목에 대해 월가 수준의 심층 분석 보고서를 작성해 주세요.

## 종목 정보
- 심볼: {symbol}
- 회사명: {name}
- 시장: {market}
{fin['company_info']}

## 실제 재무 데이터

### Income Statement (연간, 최근 5년)
{fin['income_table']}

### Cash Flow Statement (연간, 최근 5년)
{fin['cf_table']}

### Balance Sheet (연간, 최근 5년)
{fin['bs_table']}

### Key Metrics (TTM)
{fin['key_metrics']}

### Insider Trades (최근 20건) — 경영진 매수/매도 신호
{fin['insider_trades']}

### 최근 뉴스 (최근 10건)
{fin['news']}
{("### " + ("DART 공시 요약 (사업보고서/반기보고서)" if market == "KR_Stock" else "SEC 공시 원문 요약 (10-K/10-Q)") + chr(10) + sec_context) if sec_context else ""}
{thesis_context}
---

위 실제 데이터를 기반으로 8개 섹션을 XML 태그로 감싸서 출력해 주세요.
각 섹션은 최소 400자 이상, 제공된 실제 수치를 반드시 인용하세요.
Insider Trades 데이터는 management_quality 섹션에서 반드시 분석하세요.
SEC 공시 요약이 있으면 business_overview, risk_matrix 섹션에서 반드시 인용하세요.
데이터가 없는 항목은 "데이터 미확인"으로 명시하고 정성적 분석으로 대체하세요.
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

SIGNAL_VALUES = {"intact", "weakening", "broken"}


def run_break_monitor(
    symbol: str,
    name: str,
    ticker_id: str,
    thesis: str,
    key_assumptions: str,
    news_context: str = "",
    metrics_context: str = "",
) -> dict:
    """
    Break Monitor 실행.
    news_context: FinancialCache news 데이터 포맷 문자열
    metrics_context: FinancialCache metrics TTM 포맷 문자열
    반환: {signal, assessment, assumptions_status, watch_points}
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    _log({"event": "break_monitor_start", "ticker_id": ticker_id, "symbol": symbol,
          "has_news": bool(news_context), "has_metrics": bool(metrics_context)})

    skill = _load_skill("break-monitor")
    system_prompt = skill["instructions"]

    news_block = f"\n## 최근 뉴스 (오늘 기준)\n{news_context}\n" if news_context else "\n*(뉴스 데이터 없음 — 논리적 유효성만 판단)*\n"
    metrics_block = f"\n## 현재 Key Metrics (TTM)\n{metrics_context}\n" if metrics_context else ""

    user_message = f"""다음 종목의 thesis 이탈 여부를 판단해 주세요.

**종목**: {symbol} — {name}

**기존 Thesis**
{thesis or '(없음)'}

**핵심 가정 (Key Assumptions)**
{key_assumptions or '(없음)'}
{news_block}{metrics_block}
signal 태그와 3개 섹션을 출력해 주세요.
"""

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    full_text = message.content[0].text

    signal_match = re.search(r"<signal>(.*?)</signal>", full_text)
    signal = signal_match.group(1).strip().lower() if signal_match else "intact"
    if signal not in SIGNAL_VALUES:
        signal = "intact"

    result: dict = {"signal": signal, "full_text": full_text}
    for sec in ["assessment", "assumptions_status", "watch_points"]:
        m = re.search(rf'<section name="{sec}">(.*?)</section>', full_text, re.DOTALL)
        result[sec] = m.group(1).strip() if m else ""

    _log({"event": "break_monitor_complete", "ticker_id": ticker_id, "symbol": symbol, "signal": signal})
    return result


# ── Portfolio Review ──────────────────────────────────────────────────────────

PORTFOLIO_REVIEW_SECTIONS = [
    "portfolio_overview",
    "holdings_assessment",
    "concentration_risk",
    "thesis_health_check",
    "action_items",
]


def generate_portfolio_review_stream(portfolio_context: str) -> Iterator[str]:
    """
    포트폴리오 전체 점검 보고서 SSE 스트림.
    portfolio_context: 종목별 보유현황 + thesis + metrics 포맷 문자열.
    이벤트: start | chunk | complete | error
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        yield f"data: {json.dumps({'type': 'error', 'message': 'ANTHROPIC_API_KEY not set'})}\n\n"
        return

    _log({"event": "portfolio_review_start"})

    try:
        skill = _load_skill("portfolio-review")
    except FileNotFoundError as e:
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        return

    system_prompt = skill["instructions"]
    user_message = f"""현재 포트폴리오를 가치투자 관점에서 점검하고 5개 섹션 보고서를 작성해 주세요.

{portfolio_context}

5개 섹션을 XML 태그로 감싸서 출력해 주세요.
"""

    yield f"data: {json.dumps({'type': 'start'})}\n\n"

    client = anthropic.Anthropic(api_key=api_key)
    full_text = ""

    try:
        with client.messages.stream(
            model="claude-sonnet-4-6",
            max_tokens=6000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        ) as stream:
            for text in stream.text_stream:
                full_text += text
                yield f"data: {json.dumps({'type': 'chunk', 'text': text})}\n\n"

    except anthropic.APIError as e:
        _log({"event": "portfolio_review_error", "error": str(e)})
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        return

    sections: dict = {}
    for sec in PORTFOLIO_REVIEW_SECTIONS:
        m = re.search(rf'<section name="{sec}">(.*?)</section>', full_text, re.DOTALL)
        sections[sec] = m.group(1).strip() if m else ""

    _log({"event": "portfolio_review_complete",
          "sections_found": [s for s in PORTFOLIO_REVIEW_SECTIONS if sections.get(s)]})
    yield f"data: {json.dumps({'type': 'complete', 'sections': sections, 'full_text': full_text})}\n\n"


# ── Stock Discovery ───────────────────────────────────────────────────────────

DISCOVERY_SECTIONS = ["theme_analysis", "us_picks", "kr_picks", "screening_criteria", "next_steps"]


def generate_discovery_stream(idea: str) -> Iterator[str]:
    """
    투자 아이디어 → 미국/한국 유망 종목 탐색 보고서 SSE 스트림.
    이벤트: start | chunk | complete | error
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        yield f"data: {json.dumps({'type': 'error', 'message': 'ANTHROPIC_API_KEY not set'})}\n\n"
        return

    _log({"event": "discovery_start", "idea_len": len(idea)})

    try:
        skill = _load_skill("stock-discovery")
    except FileNotFoundError as e:
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        return

    system_prompt = skill["instructions"]
    user_message = f"""다음 투자 아이디어를 바탕으로 미국과 한국 상장 종목 중 유망 후보를 발굴해 주세요.

**투자 아이디어**
{idea.strip()}

가치투자 원칙에 따라 5개 섹션을 XML 태그로 감싸서 출력해 주세요.
"""

    yield f"data: {json.dumps({'type': 'start'})}\n\n"

    client = anthropic.Anthropic(api_key=api_key)
    full_text = ""

    try:
        with client.messages.stream(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        ) as stream:
            for text in stream.text_stream:
                full_text += text
                yield f"data: {json.dumps({'type': 'chunk', 'text': text})}\n\n"

    except anthropic.APIError as e:
        _log({"event": "discovery_error", "error": str(e)})
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        return

    sections: dict = {}
    for sec in DISCOVERY_SECTIONS:
        m = re.search(rf'<section name="{sec}">(.*?)</section>', full_text, re.DOTALL)
        sections[sec] = m.group(1).strip() if m else ""

    _log({"event": "discovery_complete", "sections_found": [s for s in DISCOVERY_SECTIONS if sections.get(s)]})
    yield f"data: {json.dumps({'type': 'complete', 'sections': sections, 'full_text': full_text})}\n\n"


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
        max_tokens=2048,
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
