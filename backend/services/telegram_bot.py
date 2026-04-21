import logging
import os
from datetime import datetime

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from models.db import SessionLocal, Ticker, Thesis, Report, ThesisStatusEnum, ReportTypeEnum
from services.agent import generate_thesis, generate_ticker_report
from services.telegram import notify_thesis_needs_review, notify_report_generated

logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")

_app: Application | None = None


async def cmd_analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args or []
    if not args:
        await update.message.reply_text("사용법: /analyze <심볼>\n예: /analyze NVDA")
        return

    symbol = args[0].upper()
    await update.message.reply_text(f"⏳ {symbol} 재분석 시작...")

    db = SessionLocal()
    try:
        ticker = db.query(Ticker).filter(Ticker.symbol == symbol).first()
        if not ticker:
            await update.message.reply_text(f"❌ {symbol} 종목을 찾을 수 없습니다.\n대시보드에서 먼저 종목을 추가해주세요.")
            return

        from services.financial_data import fetch_all
        try:
            fin = await _run_in_thread(fetch_all, ticker.symbol, str(ticker.id), db)
            financial_context = ""
            if fin.get("has_data"):
                from routes.tickers import _format_financial_context
                financial_context = _format_financial_context(fin)
        except Exception:
            financial_context = ""

        sections = await _run_in_thread(
            generate_thesis,
            ticker.symbol, ticker.name, ticker.market.value, str(ticker.id), financial_context,
        )

        thesis = db.query(Thesis).filter(Thesis.ticker_id == ticker.id).first()
        if thesis:
            prev_status = thesis.confirmed
            thesis.thesis = sections.get("thesis")
            thesis.risk = sections.get("risk")
            thesis.key_assumptions = sections.get("key_assumptions")
            thesis.valuation = sections.get("valuation")
            thesis.confirmed = (
                ThesisStatusEnum.NEEDS_REVIEW
                if prev_status == ThesisStatusEnum.CONFIRMED
                else ThesisStatusEnum.DRAFT
            )
            thesis.last_analyzed_at = datetime.utcnow()
            db.commit()

            if thesis.confirmed == ThesisStatusEnum.NEEDS_REVIEW:
                notify_thesis_needs_review(ticker.symbol, ticker.name, ticker.market.value)

        await update.message.reply_text(
            f"✅ <b>{symbol}</b> 재분석 완료\n"
            f"상태: {'⚠️ needs_review — 웹앱에서 확인 후 Confirm 해주세요.' if thesis and thesis.confirmed == ThesisStatusEnum.NEEDS_REVIEW else '📝 draft'}",
            parse_mode="HTML",
        )
    except Exception as e:
        logger.exception("analyze command failed for %s", symbol)
        await update.message.reply_text(f"❌ 분석 실패: {e}")
    finally:
        db.close()


async def _run_in_thread(fn, *args):
    import asyncio
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, fn, *args)


async def cmd_macro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ 매크로 보고서 생성 중...")
    try:
        from services.market_data import get_market_indicators
        from services.agent import generate_macro_report
        from models.db import SessionLocal, Report, ReportTypeEnum

        indicators = await _run_in_thread(get_market_indicators)
        sections = await _run_in_thread(generate_macro_report, indicators)

        db = SessionLocal()
        try:
            report = Report(ticker_id=None, type=ReportTypeEnum.MACRO, content=sections["full_text"])
            db.add(report)
            db.commit()
        finally:
            db.close()

        summary = sections.get("market_overview", "")[:500]
        await update.message.reply_text(
            f"📊 <b>매크로 보고서</b>\n\n{summary}\n\n웹앱에서 전체 내용을 확인하세요.",
            parse_mode="HTML",
        )
    except Exception as e:
        logger.exception("macro command failed")
        await update.message.reply_text(f"❌ 매크로 보고서 실패: {e}")


async def cmd_sync(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ KIS 전 계좌 동기화 시작...")
    try:
        from services.portfolio_sync import sync_portfolio
        result = await _run_in_thread(sync_portfolio)
        await update.message.reply_text(
            f"✅ <b>포트폴리오 동기화 완료</b>\n"
            f"계좌: {result['accounts']}개 / 종목: {result['synced']}개"
            + (f"\n❌ 실패: {', '.join(result['errors'])}" if result['errors'] else ""),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.exception("sync command failed")
        await update.message.reply_text(f"❌ 동기화 실패: {e}")


async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args or []
    if not args:
        await update.message.reply_text("사용법: /report <심볼>\n예: /report NVDA")
        return

    symbol = args[0].upper()
    await update.message.reply_text(f"⏳ {symbol} 보고서 생성 시작...")

    db = SessionLocal()
    try:
        ticker = db.query(Ticker).filter(Ticker.symbol == symbol).first()
        if not ticker:
            await update.message.reply_text(f"❌ {symbol} 종목을 찾을 수 없습니다.")
            return
        thesis = db.query(Thesis).filter(Thesis.ticker_id == ticker.id).first()

        sections = await _run_in_thread(
            generate_ticker_report,
            ticker.symbol, ticker.name, ticker.market.value, str(ticker.id),
            thesis.thesis or "" if thesis else "",
            thesis.risk or "" if thesis else "",
            thesis.key_assumptions or "" if thesis else "",
            thesis.valuation or "" if thesis else "",
        )

        report = Report(
            ticker_id=ticker.id,
            type=ReportTypeEnum.ANALYSIS,
            content=sections["full_text"],
        )
        db.add(report)
        db.commit()
        logger.info("Deep report saved for %s via Telegram", symbol)
        summary = sections.get("investment_conclusion", sections.get("business_overview", ""))[:300]
        notify_report_generated(ticker.symbol, ticker.name, summary)

    except Exception as e:
        logger.exception("report command failed for %s", symbol)
        await update.message.reply_text(f"❌ 보고서 생성 실패: {e}")
    finally:
        db.close()


def build_app() -> Application | None:
    if not TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN not set — Telegram bot disabled")
        return None
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("analyze", cmd_analyze))
    application.add_handler(CommandHandler("report", cmd_report))
    application.add_handler(CommandHandler("sync", cmd_sync))
    application.add_handler(CommandHandler("macro", cmd_macro))
    return application


async def start_bot():
    global _app
    _app = build_app()
    if not _app:
        return
    await _app.initialize()
    await _app.start()
    await _app.updater.start_polling(drop_pending_updates=True)
    logger.info("Telegram bot polling started")


async def stop_bot():
    global _app
    if _app:
        await _app.updater.stop()
        await _app.stop()
        await _app.shutdown()
        logger.info("Telegram bot stopped")
