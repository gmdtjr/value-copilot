import logging
import os
import httpx

logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


def send_message(text: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram not configured — skipping notification")
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        httpx.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=5)
    except Exception:
        logger.exception("Telegram send failed")


def notify_thesis_confirmed(symbol: str, name: str, market: str) -> None:
    market_label = "🇺🇸" if market == "US_Stock" else "🇰🇷"
    send_message(
        f"✅ <b>Thesis Confirmed</b>\n"
        f"{market_label} <b>{symbol}</b> — {name}\n"
        f"Break Monitor 활성화 대상으로 등록됩니다."
    )


def notify_break_monitor(symbol: str, name: str, signal: str, assessment: str) -> None:
    icon = {"intact": "✅", "weakening": "⚠️", "broken": "🚨"}.get(signal, "❓")
    send_message(
        f"{icon} <b>Break Monitor — {symbol}</b> ({name})\n"
        f"신호: <b>{signal.upper()}</b>\n\n"
        f"{assessment[:400] if assessment else ''}"
    )


def notify_report_generated(symbol: str, name: str, summary: str) -> None:
    send_message(
        f"📋 <b>{symbol} 보고서 생성 완료</b> — {name}\n\n"
        f"{summary[:300] if summary else ''}\n\n"
        f"웹앱에서 전체 내용을 확인하세요."
    )


def notify_thesis_needs_review(symbol: str, name: str, market: str) -> None:
    market_label = "🇺🇸" if market == "US_Stock" else "🇰🇷"
    send_message(
        f"⚠️ <b>Thesis 재검토 필요</b>\n"
        f"{market_label} <b>{symbol}</b> — {name}\n"
        f"AI 재분석 완료. 웹앱에서 내용 확인 후 Confirm 해주세요."
    )
