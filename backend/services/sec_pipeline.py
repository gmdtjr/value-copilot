"""
SEC EDGAR filing summarization pipeline.
Flow: filing_refs → EDGAR index → main doc HTML → section extraction → Claude summary → SecFilingSummary DB
8-K: EDGAR submissions API → primary doc + EX-99.1 → Claude Haiku summary → SecFilingSummary DB
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

# 8-K에서 의미 있는 items (실적/임원/계약/가이던스/주요이벤트)
_TARGET_8K_ITEMS = {"2.02", "5.02", "1.01", "7.01", "8.01"}

# CIK 조회 캐시 (프로세스 수명 동안 유지 — workers=1이므로 안전)
_cik_cache: dict[str, str] = {}

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


def _get_edgar_cik(ticker: str) -> str | None:
    """EDGAR company_tickers.json에서 ticker → CIK 조회. 프로세스 캐시 사용."""
    upper = ticker.upper()
    if upper in _cik_cache:
        return _cik_cache[upper]
    try:
        r = requests.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers=_HEADERS, timeout=10,
        )
        if r.status_code != 200:
            return None
        for entry in r.json().values():
            sym = entry.get("ticker", "").upper()
            cik = str(entry["cik_str"]).zfill(10)
            _cik_cache[sym] = cik  # 전체 결과를 한 번에 캐시
        return _cik_cache.get(upper)
    except Exception as e:
        logger.warning("CIK lookup failed for %s: %s", ticker, e)
    return None


def _get_edgar_8k_refs(ticker: str) -> list[dict]:
    """
    EDGAR submissions API로 최근 관련 8-K 목록 반환 (최대 5건).
    대상 items: 2.02(실적), 5.02(임원변경), 1.01(주요계약), 7.01(가이던스), 8.01(주요이벤트)
    """
    cik = _get_edgar_cik(ticker)
    if not cik:
        return []
    try:
        r = requests.get(
            f"https://data.sec.gov/submissions/CIK{cik}.json",
            headers=_HEADERS, timeout=10,
        )
        if r.status_code != 200:
            return []
        recent = r.json().get("filings", {}).get("recent", {})
        forms        = recent.get("form", [])
        accessions   = recent.get("accessionNumber", [])
        filed_dates  = recent.get("filingDate", [])
        items_list   = recent.get("items", [])
        primary_docs = recent.get("primaryDocument", [])

        cik_int = int(cik)
        refs = []
        for i, form in enumerate(forms):
            if form != "8-K":
                continue
            items_str = items_list[i] if i < len(items_list) else ""
            item_set = {it.strip() for it in items_str.split(",")}
            if not (item_set & _TARGET_8K_ITEMS):
                continue

            acc = accessions[i]
            acc_clean = acc.replace("-", "")
            date = filed_dates[i] if i < len(filed_dates) else ""
            primary_doc = primary_docs[i] if i < len(primary_docs) else ""

            if primary_doc and primary_doc.endswith(('.htm', '.html')):
                doc_url = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_clean}/{primary_doc}"
            else:
                doc_url = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_clean}/"

            refs.append({
                "period":    date,
                "url":       doc_url,
                "items":     items_str,
                "cik":       str(cik_int),
                "acc_nodash": acc_clean,
            })
            if len(refs) >= 5:
                break

        logger.info("8-K refs for %s: %d relevant found", ticker, len(refs))
        return refs
    except Exception as e:
        logger.warning("8-K refs failed for %s: %s", ticker, e)
        return []


def _fetch_8k_content(ref: dict) -> tuple[str, str]:
    """
    8-K index JSON → 주 문서 텍스트 + EX-99.1 텍스트 반환.
    EX-99.1는 실적 발표 press release를 포함하는 경우가 많음.
    Returns (main_text, ex991_text)
    """
    cik = ref.get("cik", "")
    acc_nodash = ref.get("acc_nodash", "")
    main_text = ex991_text = ""

    if cik and acc_nodash and len(acc_nodash) == 18:
        try:
            acc_dashed = f"{acc_nodash[:10]}-{acc_nodash[10:12]}-{acc_nodash[12:]}"
            base = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/"
            r = requests.get(f"{base}{acc_dashed}-index.json", headers=_HEADERS, timeout=10)
            if r.status_code == 200:
                docs = r.json().get("documents", [])
                main_url = ex991_url = None
                for doc in docs:
                    dtype = (doc.get("type") or "").upper().replace(" ", "")
                    name = doc.get("filename", "")
                    if not name:
                        continue
                    url = f"{base}{name}"
                    if dtype == "8-K" and not main_url and name.endswith(('.htm', '.html')):
                        main_url = url
                    elif dtype in ("EX-99.1", "EX-99") and not ex991_url and name.endswith(('.htm', '.html', '.txt')):
                        ex991_url = url

                if main_url:
                    html = _fetch_text(main_url)
                    main_text = _strip_html(html)[:3000] if html else ""
                if ex991_url:
                    time.sleep(0.5)
                    html = _fetch_text(ex991_url)
                    ex991_text = _strip_html(html)[:5000] if html else ""
                return main_text, ex991_text
        except Exception as e:
            logger.warning("8-K index JSON failed: %s", e)

    # Fallback: primaryDocument URL 직접 사용
    url = ref.get("url", "")
    if url.endswith(('.htm', '.html')):
        html = _fetch_text(url)
        main_text = _strip_html(html)[:4000] if html else ""
    return main_text, ex991_text


def _summarize_8k(client: anthropic.Anthropic, text: str, items: str) -> str:
    if not text.strip():
        return ""

    if "2.02" in items:
        instruction = (
            "This is an earnings release (Item 2.02 - Results of Operations). "
            "Summarize: (1) key financial results with specific numbers (revenue, EPS, key metrics vs prior period), "
            "(2) management guidance/outlook, (3) notable business developments. Max 350 words."
        )
    elif "5.02" in items:
        instruction = (
            "This involves executive/director changes (Item 5.02). "
            "Summarize: who is departing or joining, their role, stated reasons, and potential implications. Max 200 words."
        )
    elif "1.01" in items:
        instruction = (
            "This involves a material agreement (Item 1.01). "
            "Summarize: nature of the agreement, counterparties, key terms, financial impact if stated, strategic significance. Max 250 words."
        )
    elif "7.01" in items:
        instruction = (
            "This is a Regulation FD disclosure (Item 7.01). "
            "Summarize the key guidance, business update, or investor communication. Max 250 words."
        )
    else:
        instruction = (
            f"This 8-K covers item(s): {items}. "
            "Summarize the key business event and its significance for investors. Max 250 words."
        )

    try:
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            messages=[{"role": "user", "content": f"{instruction}\n\n---\n{text[:6000]}"}],
        )
        return msg.content[0].text.strip()
    except Exception as e:
        logger.warning("8-K summarize failed (items=%s): %s", items, e)
        return ""


def run_8k_pipeline(ticker: str, ticker_id: str, db) -> int:
    """
    최근 관련 8-K 공시를 가져와 요약 후 SecFilingSummary에 저장. US 종목 전용.
    반환: 새로 저장된 건수.
    """
    from models.db import SecFilingSummary
    import os

    refs = _get_edgar_8k_refs(ticker)
    if not refs:
        return 0

    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
    saved = 0

    for ref in refs:
        period = ref["period"]   # "2025-01-15"
        items  = ref["items"]    # "2.02,9.01"
        if not period:
            continue

        existing = (
            db.query(SecFilingSummary)
            .filter(
                SecFilingSummary.ticker_id == ticker_id,
                SecFilingSummary.report_period == period,
                SecFilingSummary.filing_type == "8-K",
            )
            .first()
        )
        if existing:
            continue

        logger.info("Processing 8-K: %s %s (items: %s)", ticker, period, items)
        time.sleep(1)

        main_text, ex991_text = _fetch_8k_content(ref)
        combined = f"[8-K Form]\n{main_text}\n\n[Exhibit 99.1]\n{ex991_text}".strip()
        if not main_text and not ex991_text:
            logger.warning("8-K content empty: %s %s", ticker, period)
            continue

        summary = _summarize_8k(client, combined, items)
        if not summary:
            continue

        # 이벤트 유형 레이블 (business_summary에 저장 → context 포맷용)
        labels = []
        if "2.02" in items: labels.append("실적 발표")
        if "5.02" in items: labels.append("임원 변경")
        if "1.01" in items: labels.append("주요 계약")
        if "7.01" in items: labels.append("가이던스")
        if "8.01" in items: labels.append("주요 이벤트")
        event_type = ", ".join(labels) if labels else f"Items {items}"

        row = SecFilingSummary(
            ticker_id=ticker_id,
            filing_type="8-K",
            report_period=period,
            filing_url=ref["url"],
            business_summary=event_type,
            mda_summary=summary,
        )
        db.add(row)
        db.commit()
        saved += 1
        logger.info("Saved 8-K summary: %s %s (%s)", ticker, period, event_type)
        time.sleep(1.5)

    return saved


def get_sec_context(ticker_id: str, db, limit: int = 2) -> str:
    """
    DB에서 SEC 공시 요약을 조회하여 report 프롬프트용 문자열로 반환.
    8-K(최근 3건)를 먼저, 그 뒤 10-K/10-Q(최근 limit건) 순서.
    """
    from models.db import SecFilingSummary

    eight_k = (
        db.query(SecFilingSummary)
        .filter(
            SecFilingSummary.ticker_id == ticker_id,
            SecFilingSummary.filing_type == "8-K",
        )
        .order_by(SecFilingSummary.report_period.desc())
        .limit(3)
        .all()
    )

    annual_quarterly = (
        db.query(SecFilingSummary)
        .filter(
            SecFilingSummary.ticker_id == ticker_id,
            SecFilingSummary.filing_type.in_(["10-K", "10-Q"]),
        )
        .order_by(SecFilingSummary.report_period.desc())
        .limit(limit)
        .all()
    )

    if not eight_k and not annual_quarterly:
        return ""

    parts = []

    for row in eight_k:
        event_type = row.business_summary or ""
        header = f"=== 8-K {row.report_period}"
        if event_type:
            header += f" [{event_type}]"
        header += " ==="
        parts.append(header)
        if row.mda_summary:
            parts.append(f"[Event Summary]\n{row.mda_summary}")

    for row in annual_quarterly:
        parts.append(f"=== {row.filing_type} {row.report_period} ===")
        if row.business_summary:
            parts.append(f"[Business Overview]\n{row.business_summary}")
        if row.risk_summary:
            parts.append(f"[Key Risk Factors]\n{row.risk_summary}")
        if row.mda_summary:
            parts.append(f"[MD&A Highlights]\n{row.mda_summary}")

    return "\n\n".join(parts)
