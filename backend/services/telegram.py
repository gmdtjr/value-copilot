import logging
import os
import httpx

logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
APP_URL = os.environ.get("APP_URL", "http://3.26.145.173").rstrip("/")


def send_message(text: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram not configured — skipping notification")
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        httpx.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=5)
    except Exception:
        logger.exception("Telegram send failed")


def _report_link(report_id: str) -> str:
    return f"{APP_URL}/reports?id={report_id}"


def _thesis_link(ticker_id: str) -> str:
    return f"{APP_URL}/tickers/{ticker_id}/thesis"


def notify_thesis_confirmed(symbol: str, name: str, market: str, ticker_id: str = "") -> None:
    market_label = "🇺🇸" if market == "US_Stock" else "🇰🇷"
    link = f'\n🔗 <a href="{_thesis_link(ticker_id)}">Thesis 보기</a>' if ticker_id else ""
    send_message(
        f"✅ <b>Thesis Confirmed</b>\n"
        f"{market_label} <b>{symbol}</b> — {name}\n"
        f"Break Monitor 활성화 대상으로 등록됩니다."
        f"{link}"
    )


def notify_thesis_needs_review(symbol: str, name: str, market: str, ticker_id: str = "") -> None:
    market_label = "🇺🇸" if market == "US_Stock" else "🇰🇷"
    link = f'\n🔗 <a href="{_thesis_link(ticker_id)}">Thesis 확인 후 Confirm</a>' if ticker_id else ""
    send_message(
        f"⚠️ <b>Thesis 재검토 필요</b>\n"
        f"{market_label} <b>{symbol}</b> — {name}\n"
        f"AI 재분석 완료. 내용 확인 후 Confirm 해주세요."
        f"{link}"
    )


def notify_break_monitor(symbol: str, name: str, signal: str, assessment: str, ticker_id: str = "") -> None:
    icon = {"intact": "✅", "weakening": "⚠️", "broken": "🚨"}.get(signal, "❓")
    link = f'\n🔗 <a href="{_thesis_link(ticker_id)}">Thesis 보기</a>' if ticker_id else ""
    send_message(
        f"{icon} <b>Break Monitor — {symbol}</b> ({name})\n"
        f"신호: <b>{signal.upper()}</b>\n\n"
        f"{assessment[:400] if assessment else ''}"
        f"{link}"
    )


def notify_report_generated(symbol: str, name: str, summary: str, report_id: str = "") -> None:
    link = f'\n🔗 <a href="{_report_link(report_id)}">보고서 보기</a>' if report_id else f"\n웹앱에서 전체 내용을 확인하세요."
    send_message(
        f"📋 <b>{symbol} 심층 분석 완료</b> — {name}\n\n"
        f"{summary[:300] if summary else ''}"
        f"{link}"
    )


def notify_daily_briefing(report_id: str, macro_snippet: str) -> None:
    from datetime import datetime, timezone, timedelta
    now_kst = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M KST")
    link = f'\n🔗 <a href="{_report_link(report_id)}">브리핑 보기</a>'
    send_message(
        f"☀️ <b>데일리 브리핑</b> — {now_kst}\n\n"
        f"{macro_snippet[:300] if macro_snippet else ''}"
        f"{link}"
    )


def notify_macro_saved(report_id: str) -> None:
    from datetime import datetime, timezone, timedelta
    now_kst = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M KST")
    link = f'\n🔗 <a href="{_report_link(report_id)}">매크로 보고서 보기</a>'
    send_message(f"📊 <b>매크로 보고서 생성 완료</b> — {now_kst}{link}")


def notify_discovery_saved(report_id: str, idea_snippet: str = "") -> None:
    idea_part = f"\n💡 아이디어: {idea_snippet[:80]}" if idea_snippet else ""
    link = f'\n🔗 <a href="{_report_link(report_id)}">탐색 보고서 보기</a>'
    send_message(f"🔍 <b>종목 탐색 완료</b>{idea_part}{link}")


def notify_trades_detected(trades: list[dict]) -> None:
    ACTION_LABEL = {"buy": "신규매수", "sell": "전량매도", "add": "추가매수", "reduce": "일부매도"}
    ACTION_ICON = {"buy": "🟢", "sell": "🔴", "add": "📈", "reduce": "📉"}
    lines = []
    for t in trades:
        action = t.get("action", "")
        label = ACTION_LABEL.get(action, action)
        icon = ACTION_ICON.get(action, "•")
        qty_before = t.get("quantity_before", 0)
        qty_after = t.get("quantity_after", 0)
        if action == "buy":
            qty_str = f"{qty_after:.2f}주"
        elif action == "sell":
            qty_str = f"{qty_before:.2f}주 전량"
        elif action == "add":
            qty_str = f"{qty_before:.2f} → {qty_after:.2f}주 (+{qty_after - qty_before:.2f})"
        else:
            qty_str = f"{qty_before:.2f} → {qty_after:.2f}주 (-{qty_before - qty_after:.2f})"
        lines.append(f"{icon} <b>{t['symbol']}</b> {label} {qty_str}")

    link = f'\n🔗 <a href="{APP_URL}/journal">투자 일지 작성하기</a>'
    send_message(
        f"📝 <b>거래 감지됨</b> — KIS 동기화\n\n"
        + "\n".join(lines)
        + f"\n\n거래 이유를 기록해 두세요."
        + link
    )


def notify_portfolio_review_saved(report_id: str) -> None:
    from datetime import datetime, timezone, timedelta
    now_kst = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M KST")
    link = f'\n🔗 <a href="{_report_link(report_id)}">포트폴리오 점검 보기</a>'
    send_message(f"📦 <b>포트폴리오 점검 완료</b> — {now_kst}{link}")
