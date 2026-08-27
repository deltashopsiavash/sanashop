#!/usr/bin/env python3
import io
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from bot_single_instance import acquire_single_instance_lock
import external_bot as core
import external_bot_v10 as v10
import external_bot_v12 as v12
import external_bot_v13 as v13

logger = logging.getLogger(__name__)


async def _show_full_backups(q, site, sid):
    """One API request only; v13 used to ping before this and doubled button latency."""
    info = (await core.api(site, "backup_status", timeout=25))["data"]
    interval = int(info.get("interval_minutes") or 0)
    interval_text = f"هر {interval} دقیقه" if interval else "غیرفعال"
    last = v10._fmt_time(info.get("last_backup_at"))
    text = (
        "🔐 بکاپ کامل صفر تا صد فروشگاه\n\n"
        f"⏱ زمان‌بندی: {interval_text}\n"
        f"🕒 آخرین بکاپ زمان‌بندی‌شده: {last}\n\n"
        "هر فایل .sanabackup یک Snapshot کامل از اطلاعات سایت است:\n"
        "✅ تمام کاربران و پروفایل‌ها\n"
        "✅ تمام محصولات، موجودی، گالری و دسته‌ها\n"
        "✅ تمام سفارش‌ها، آیتم‌ها، رسیدها و تاریخچه وضعیت\n"
        "✅ تمام تنظیمات فروشگاه، پرداخت، فوتر و شبکه‌های اجتماعی\n"
        "✅ بنرها، استوری‌ها، صفحات، کدهای تخفیف و رویدادها\n"
        "✅ تمام عکس‌ها و فایل‌های آپلودشده در media\n\n"
        "هنگام Restore، دیتابیس و media دقیقاً به وضعیت همان بکاپ برمی‌گردند."
    )
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📤 بکاپ کامل همین حالا", callback_data=f"backup_now_v10:{sid}"),
            InlineKeyboardButton("⏱ زمان‌بندی", callback_data=f"backup_interval_v10:{sid}"),
        ],
        [InlineKeyboardButton("♻️ بازگردانی بکاپ کامل", callback_data=f"backup_restore_v10:{sid}")],
        [InlineKeyboardButton("⬅️ تنظیمات فروشگاه", callback_data=f"settings:{sid}")],
    ])
    return await q.edit_message_text(text, reply_markup=kb)


async def _send_full_backup(bot, chat_id, site, label="manual"):
    raw, filename = await v10._build_backup(site, label)
    document = io.BytesIO(raw)
    document.name = filename
    await bot.send_document(
        chat_id=chat_id,
        document=document,
        filename=filename,
        caption=(
            "🔐 بکاپ کامل صفر تا صد SanaShop\n"
            "Database کامل فروشگاه + تمام media و فایل‌های آپلودی.\n"
            "برای Restore کامل همین فایل .sanabackup را نگه دارید."
        ),
        read_timeout=180,
        write_timeout=180,
    )
    return filename


# Existing v10 callback flow automatically uses these upgraded implementations.
v10._show_backups = _show_full_backups
v10._send_backup = _send_full_backup


async def callback(update: Update, context):
    """Safe callback path without the extra backup-version ping introduced in v13."""
    q = update.callback_query
    uid = q.from_user.id
    data = q.data or ""
    try:
        return await v12.callback(update, context)
    except Exception as exc:
        logger.exception("v14 action failed; saved site connection remains untouched: %s", data)
        site = v13._site_from_data(uid, data)
        try:
            await q.answer("عملیات ناموفق بود؛ اتصال سایت حفظ شده است.", show_alert=False)
        except Exception:
            pass
        detail = str(exc).strip() or exc.__class__.__name__
        if len(detail) > 700:
            detail = detail[:700] + "…"
        return await v13._safe_reply(
            q,
            "⚠️ این بخش اجرا نشد، اما اتصال سایت همچنان در دیتابیس ربات ذخیره است.\n\n"
            f"خطا: {detail}\n\n"
            "می‌توانید با یک بار لمس یکی از دکمه‌های پنل دوباره ادامه دهید.",
            v13._site_keyboard(site, uid),
        )


async def message(update: Update, context):
    return await v13.message(update, context)


async def media(update: Update, context):
    return await v13.media(update, context)


def run():
    try:
        acquire_single_instance_lock()
    except RuntimeError as exc:
        logger.error("SanaShop bot refused duplicate startup: %s", exc)
        raise SystemExit(73) from exc

    core.db()
    # PTB processes updates sequentially by default. A slow API/backup therefore made every
    # following button look dead until users tapped again. Process independent updates in
    # parallel and give Telegram's HTTP client enough pooled connections for those callbacks.
    app = (
        Application.builder()
        .token(core.TOKEN)
        .concurrent_updates(16)
        .connection_pool_size(32)
        .pool_timeout(10.0)
        .post_init(v10.post_init)
        .build()
    )
    app.add_handler(CommandHandler("start", core.start))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.Document.ALL, media))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message))
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    run()
