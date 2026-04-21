"""
DART 사업보고서/반기보고서 요약 파이프라인.
Flow: main.do (TOC node1 파싱) → viewer.do (섹션 HTML) → Claude Haiku → SecFilingSummary

- document.xml ZIP은 XBRL XML만 반환 → 사용 불가
- selectTransIndex.do는 JS 렌더링 → 사용 불가
- main.do의 treeData(node1) → viewer.do 방식으로 직접 섹션 HTML 접근
"""
import logging
import os
import re
import time

import requests
import anthropic

logger = logging.getLogger(__name__)

_DART_SITE = "https://dart.fss.or.kr"
_HEADERS   = {"User-Agent": "Mozilla/5.0 (compatible; value-copilot/1.0)"}


# ── TOC 파싱 + 섹션 HTML 취득 ─────────────────────────────────────────────────

def _parse_toc(rcept_no: str) -> list[dict]:
    """main.do에서 top-level TOC 섹션 목록 반환.
    node1['key'] = "value" 패턴만 파싱 (node2+는 자식 섹션이므로 제외).
    """
    try:
        resp = requests.get(
            f"{_DART_SITE}/dsaf001/main.do",
            params={"rcpNo": rcept_no},
            headers=_HEADERS,
            timeout=15,
        )
        if resp.status_code != 200:
            logger.warning("DART main.do %s → HTTP %s", rcept_no, resp.status_code)
            return []

        text = resp.content.decode("utf-8", errors="ignore")
        blocks = text.split("treeData.push(")
        sections = []
        for block in blocks[1:]:
            props = {}
            for m in re.finditer(r"node1\['(\w+)'\]\s*=\s*\"([^\"]*)\";", block):
                props[m.group(1)] = m.group(2)
            if props.get("text") and props.get("offset") and props.get("length") and props.get("eleId"):
                sections.append(props)

        logger.info("DART TOC parsed: %d top-level sections for %s", len(sections), rcept_no)
        return sections

    except Exception as e:
        logger.warning("DART TOC parse failed %s: %s", rcept_no, e)
        return []


def _fetch_section_text(section: dict) -> str:
    """viewer.do로 섹션 HTML 다운로드 → 스트립 텍스트 반환."""
    try:
        url = (
            f"{_DART_SITE}/report/viewer.do"
            f"?rcpNo={section['rcpNo']}&dcmNo={section['dcmNo']}"
            f"&eleId={section['eleId']}&offset={section['offset']}"
            f"&length={section['length']}&dtd={section.get('dtd','dart4.xsd')}"
        )
        resp = requests.get(url, headers=_HEADERS, timeout=30)
        if resp.status_code != 200 or not resp.text:
            return ""
        return _strip_html(resp.text)
    except Exception as e:
        logger.warning("DART viewer fetch failed: %s", e)
        return ""


def _strip_html(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html)
    for ent, rep in [("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">")]:
        text = text.replace(ent, rep)
    return re.sub(r"\s{3,}", "\n\n", text).strip()


# ── 섹션 키워드 매핑 ──────────────────────────────────────────────────────────

_SECTION_KEYWORDS = {
    "business": ["사업의 내용"],
    "risk":     ["위험", "투자위험", "사업위험"],
    "mda":      ["경영진단", "이사의 경영"],
}

# 위험요소는 별도 top-level 섹션 없으면 사업의 내용 내 텍스트에서 추출
_MDA_FALLBACK = ["재무에 관한 사항"]


def _get_section_text(toc: list[dict], section_type: str, max_chars: int = 8000) -> str:
    """TOC에서 해당 섹션 텍스트 반환. 없으면 ""."""
    keywords = _SECTION_KEYWORDS.get(section_type, [])
    for s in toc:
        title = s.get("text", "")
        if any(kw in title for kw in keywords):
            text = _fetch_section_text(s)
            logger.info("DART section '%s' fetched: %d chars", title, len(text))
            return text[:max_chars]

    # mda fallback: 재무에 관한 사항
    if section_type == "mda":
        for s in toc:
            title = s.get("text", "")
            if any(kw in title for kw in _MDA_FALLBACK):
                text = _fetch_section_text(s)
                logger.info("DART mda fallback '%s': %d chars", title, len(text))
                return text[:max_chars]

    return ""


def _extract_risk_from_business(business_text: str, max_chars: int = 5000) -> str:
    """사업의 내용 텍스트에서 위험요소 부분 추출."""
    patterns = [r"위험요소", r"투자\s*위험", r"주요\s*위험", r"사업\s*위험"]
    for pat in patterns:
        m = re.search(pat, business_text, re.IGNORECASE)
        if m:
            return business_text[m.start():][:max_chars]
    return ""


# ── Claude Haiku 요약 ──────────────────────────────────────────────────────────

_PROMPTS = {
    "business": "아래 한국 기업 사업보고서 '사업의 내용' 섹션에서 핵심 사업 모델, 주요 제품/서비스, 매출 구조, 경쟁 포지셔닝을 한국어로 300자 이내 요약하세요.",
    "risk":     "아래 사업보고서 위험요소 섹션에서 투자 thesis에 영향을 줄 수 있는 5~7가지 핵심 위험 요소를 한국어로 300자 이내 요약하세요.",
    "mda":      "아래 사업보고서 재무/경영진단 섹션에서 (1) 실적 주요 요인, (2) 마진 트렌드, (3) 경영진 전망을 한국어로 300자 이내 요약하세요.",
}


def _summarize(client: anthropic.Anthropic, text: str, section_type: str) -> str:
    if not text.strip():
        return ""
    try:
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            messages=[{"role": "user", "content": f"{_PROMPTS[section_type]}\n\n---\n{text[:5000]}"}],
        )
        return msg.content[0].text.strip()
    except Exception as e:
        logger.warning("DART summarize failed (%s): %s", section_type, e)
        return ""


# ── 메인 파이프라인 ───────────────────────────────────────────────────────────

def run_dart_pipeline(filing_refs: list[dict], ticker_id: str, db) -> int:
    """
    DART 정기공시 요약 파이프라인. SecFilingSummary 테이블에 저장.
    filing_refs: [{"period": "2025-03", "filing_type": "사업보고서", "url": "...", "rcept_no": "..."}]
    """
    from models.db import SecFilingSummary

    if not filing_refs:
        return 0

    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
    saved = 0

    for ref in filing_refs[:4]:
        period      = ref.get("period", "")
        rcept_no    = ref.get("rcept_no", "")
        url         = ref.get("url", "")
        filing_type = ref.get("filing_type", "사업보고서")

        if not period or not rcept_no:
            continue

        existing = (
            db.query(SecFilingSummary)
            .filter(
                SecFilingSummary.ticker_id == ticker_id,
                SecFilingSummary.report_period == period,
            )
            .first()
        )
        if existing:
            logger.debug("DART summary exists: %s/%s", ticker_id, period)
            continue

        logger.info("DART pipeline: ticker=%s period=%s rcept_no=%s type=%s",
                    ticker_id, period, rcept_no, filing_type)

        # 1. TOC 파싱
        toc = _parse_toc(rcept_no)
        if not toc:
            logger.warning("DART TOC empty for rcept_no=%s", rcept_no)
            continue

        # 2. 섹션별 텍스트 취득
        biz_text = _get_section_text(toc, "business")
        time.sleep(0.3)

        # 위험요소: 별도 섹션 없으면 사업의 내용에서 추출
        risk_text = _get_section_text(toc, "risk")
        if not risk_text and biz_text:
            risk_text = _extract_risk_from_business(biz_text)
        time.sleep(0.3)

        mda_text = _get_section_text(toc, "mda")
        time.sleep(0.3)

        logger.info("DART sections: biz=%d risk=%d mda=%d chars for %s",
                    len(biz_text), len(risk_text), len(mda_text), rcept_no)

        # 3. Claude Haiku 요약
        biz_summary  = _summarize(client, biz_text, "business")
        time.sleep(0.5)
        risk_summary = _summarize(client, risk_text, "risk")
        time.sleep(0.5)
        mda_summary  = _summarize(client, mda_text, "mda")

        # 4. DB 저장
        row = SecFilingSummary(
            ticker_id=ticker_id,
            filing_type=filing_type,
            report_period=period,
            filing_url=url,
            business_summary=biz_summary or None,
            risk_summary=risk_summary or None,
            mda_summary=mda_summary or None,
        )
        db.add(row)
        db.commit()
        saved += 1
        logger.info("DART summary saved: ticker=%s period=%s type=%s", ticker_id, period, filing_type)

    return saved
