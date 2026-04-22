"""
SEC EDGAR filing summarization pipeline.
Flow: filing_refs → EDGAR index → main doc HTML → section extraction → Claude summary → SecFilingSummary DB
"""
import logging
import re
import time

import requests
import anthropic

logger = logging.getLogger(__name__)

_EDGAR_BASE = "https://www.sec.gov"
_HEADERS = {
    "User-Agent": "value-copilot research@example.com",
    "Accept-Encoding": "gzip, deflate",
}

_SECTION_PATTERNS = {
    "business": [
        r"item\s*1[\.\s]*business",
        r"item\s*1\b",
    ],
    "risk": [
        r"item\s*1a[\.\s]*risk\s*factors?",
        r"item\s*1a\b",
    ],
    "mda": [
        r"item\s*7[\.\s]*management.{0,40}discussion",
        r"item\s*7\b",
    ],
}

_SECTION_END_PATTERNS = {
    "business": r"item\s*1a\b",
    "risk":     r"item\s*2\b",
    "mda":      r"item\s*7a\b",
}


def _fetch_text(url: str, timeout: int = 20) -> str:
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=timeout)
        if resp.status_code == 200:
            return resp.text
        logger.warning("EDGAR fetch %s → %s", url, resp.status_code)
    except Exception as e:
        logger.warning("fetch failed %s: %s", url, e)
    return ""


def _strip_html(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"\s{3,}", "\n\n", text)
    return text.strip()


def _extract_section(text: str, section_key: str, max_chars: int = 6000) -> str:
    lower = text.lower()
    start = -1
    for pat in _SECTION_PATTERNS[section_key]:
        m = re.search(pat, lower)
        if m:
            start = m.start()
            break
    if start == -1:
        return ""

    end_pat = _SECTION_END_PATTERNS.get(section_key, "")
    end = len(text)
    if end_pat:
        m = re.search(end_pat, lower[start + 50:])
        if m:
            end = start + 50 + m.start()

    chunk = text[start:end][:max_chars]
    return chunk.strip()


def _resolve_main_doc_url(index_url: str) -> str | None:
    """EDGAR index URL → primary 10-K/10-Q HTML document URL.

    Uses EDGAR index JSON (sequence=1, type=10-K/10-Q) for accuracy.
    Falls back to HTML parsing if JSON unavailable.
    """
    # ── Try EDGAR index JSON first (most reliable) ────────────────────────────
    # index_url: https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/
    # JSON url:  https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/{acc_dashed}-index.json
    try:
        parts = index_url.rstrip('/').split('/')
        cik_part = parts[-2]
        acc_nodash = parts[-1]
        # reconstruct dashed accession: 0000731766-26-000062
        if len(acc_nodash) == 18:
            acc_dashed = f"{acc_nodash[:10]}-{acc_nodash[10:12]}-{acc_nodash[12:]}"
            json_url = f"{index_url}{acc_dashed}-index.json"
            r = requests.get(json_url, headers=_HEADERS, timeout=10)
            if r.status_code == 200:
                docs = r.json().get('documents', [])
                # sequence 1 = primary document
                for doc in sorted(docs, key=lambda d: int(d.get('sequence') or 99)):
                    dtype = (doc.get('type') or '').upper()
                    name = doc.get('filename', '')
                    if dtype in ('10-K', '10-Q', '10-K/A', '10-Q/A') and name.endswith(('.htm', '.html')):
                        return f"https://www.sec.gov/Archives/edgar/data/{cik_part}/{acc_nodash}/{name}"
    except Exception as e:
        logger.debug("index JSON failed, falling back to HTML: %s", e)

    # ── HTML fallback: parse directory listing ────────────────────────────────
    html = _fetch_text(index_url)
    if not html:
        return None
    matches = re.findall(
        r'href="(/Archives/edgar/data/[^"]+?\.htm[l]?)"',
        html, re.IGNORECASE
    )
    _SKIP = re.compile(r'(/r\d+\.htm|exhibit|xbrl|ex\d)', re.IGNORECASE)
    for href in matches:
        if _SKIP.search(href):
            continue
        return f"https://www.sec.gov{href}"
    return None


def _summarize_section(client: anthropic.Anthropic, section_text: str, section_type: str) -> str:
    if not section_text.strip():
        return ""
    prompts = {
        "business": "Summarize the key business model, products/services, revenue streams, and competitive positioning from this 10-K Business section (Item 1). Be specific and concise. Max 400 words.",
        "risk": "Extract and summarize the 5-7 most material risk factors from this 10-K Risk Factors section (Item 1A). Focus on risks that could impact the investment thesis. Max 400 words.",
        "mda": "Summarize management's key commentary on: (1) financial performance drivers, (2) margin trends, (3) outlook and guidance from this MD&A section (Item 7). Max 400 words.",
    }
    prompt = prompts.get(section_type, "Summarize this SEC filing section. Max 400 words.")
    try:
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            messages=[{
                "role": "user",
                "content": f"{prompt}\n\n---\n{section_text[:5000]}",
            }],
        )
        return msg.content[0].text.strip()
    except Exception as e:
        logger.warning("summarize failed (%s): %s", section_type, e)
        return ""


def run_sec_pipeline(filing_refs: list[dict], ticker_id: str, db) -> int:
    """
    Process filing_refs from fetch_all(), summarize each, save to SecFilingSummary.
    Returns count of new summaries saved.
    """
    from models.db import SecFilingSummary
    import os

    if not filing_refs:
        return 0

    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
    saved = 0

    for ref in filing_refs[:6]:  # 10-K 최대 3건 + 10-Q 최대 3건 수준
        period = ref.get("period", "")
        index_url = ref.get("url", "")
        if not period or not index_url:
            continue

        # Skip if already summarized
        existing = (
            db.query(SecFilingSummary)
            .filter(
                SecFilingSummary.ticker_id == ticker_id,
                SecFilingSummary.report_period == period,
            )
            .first()
        )
        if existing:
            logger.debug("SEC summary already exists: %s/%s", ticker_id, period)
            continue

        logger.info("Processing SEC filing: %s %s", ticker_id, period)

        # URL이 직접 .htm 문서면 바로 사용, 아니면 index 파싱
        if index_url.endswith(('.htm', '.html')):
            main_url = index_url
        else:
            main_url = _resolve_main_doc_url(index_url)
        if not main_url:
            logger.warning("Could not resolve main doc from %s", index_url)
            continue

        time.sleep(1)  # EDGAR rate limit 보호
        html = _fetch_text(main_url)
        if not html:
            continue

        text = _strip_html(html)

        # Extract sections
        biz_text  = _extract_section(text, "business")
        risk_text = _extract_section(text, "risk")
        mda_text  = _extract_section(text, "mda")

        # Summarize with Claude Haiku (cheaper for bulk)
        biz_summary  = _summarize_section(client, biz_text, "business")
        time.sleep(1.5)
        risk_summary = _summarize_section(client, risk_text, "risk")
        time.sleep(1.5)
        mda_summary  = _summarize_section(client, mda_text, "mda")
        time.sleep(1.5)  # 다음 filing 전 쿨다운

        filing_type = "10-K" if len(period) == 4 else "10-Q"
        row = SecFilingSummary(
            ticker_id=ticker_id,
            filing_type=filing_type,
            report_period=period,
            filing_url=main_url,
            business_summary=biz_summary or None,
            risk_summary=risk_summary or None,
            mda_summary=mda_summary or None,
        )
        db.add(row)
        db.commit()
        saved += 1
        logger.info("Saved SEC summary: %s %s (%s)", ticker_id, period, filing_type)

    return saved


def get_sec_context(ticker_id: str, db, limit: int = 2) -> str:
    """
    Retrieve SEC summaries from DB and format as context string for report prompt.
    """
    from models.db import SecFilingSummary
    rows = (
        db.query(SecFilingSummary)
        .filter(SecFilingSummary.ticker_id == ticker_id)
        .order_by(SecFilingSummary.report_period.desc())
        .limit(limit)
        .all()
    )
    if not rows:
        return ""

    parts = []
    for row in rows:
        parts.append(f"=== {row.filing_type} {row.report_period} ===")
        if row.business_summary:
            parts.append(f"[Business Overview]\n{row.business_summary}")
        if row.risk_summary:
            parts.append(f"[Key Risk Factors]\n{row.risk_summary}")
        if row.mda_summary:
            parts.append(f"[MD&A Highlights]\n{row.mda_summary}")

    return "\n\n".join(parts)
