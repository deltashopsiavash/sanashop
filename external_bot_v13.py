#!/usr/bin/env python3
import logging

from telegram import InlineKeyboardMarkup, InlineKeyboardButton, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from bot_single_instance import acquire_single_instance_lock
import external_bot as core
import external_bot_v10 as v10
import external_bot_v12 as v12

logger = logging.getLogger(__name__)
BACKUP_PREFIXES = (
    "backups_v10:",
    "backup_now_v10:",
    "backup_interval_v10:",
    "backup_restore_v10:",
    "backup_restore_confirm_v10:",
    "backup_restore_cancel_v10:",
)


def _site_from_data(uid, data):
    parts = str(data or "").split(":")
    if len(parts) < 2:
        return None
    try:
        site_id = int(parts[1])
    except (TypeError, ValueError):
        return None
    if not core.can_access(uid, site_id):
        return None
    return core.get_site(site_id)


def _site_keyboard(site, uid):
    if not site:
        return core.owner_home() if core.is_owner(uid) else None
    return core.site_panel(site, uid)


async def _safe_reply(q, text, keyboard=None):
    """Never let Telegram message-edit limitations turn an API error into a dead panel."""
    try:
        return await q.edit_message_text(text, reply_markup=keyboard)
    except Exception:
        try:
            return await q.message.reply_text(text, reply_markup=keyboard)
        except Exception:
            logger.exception("Could not render safe callback response")
            return None


async def _backup_version_guard(q, uid, data):
    if not str(data or "").startswith(BACKUP_PREFIXES):
        return False
    site = _site_from_data(uid, data)
    if not site:
        return False
    try:
        info = await core.api(site, "ping", timeout=20)
        version = int((info.get("site") or {}).get("version") or 0)
    except Exception:
        # Let the normal callback run; the global safety wrapper below will preserve the panel.
        return False
    if version >= 8:
        return False
    try:
        await q.answer()
    except Exception:
        pass
    await _safe_reply(
        q,
        "⚠️ اتصال سایت برقرار و ذخیره است، اما بخش بکاپ روی نسخه فعلی سایت ایران فعال نیست.\n\n"
        f"نسخه API سایت: {version or '-'}\n"
        "ابتدا سایت ایران را آپدیت کنید و بعد دوباره بکاپ را بزنید.\n\n"
        "curl -fsSL https://raw.githubusercontent.com/deltashopsiavash/sanashop/main/update-site.sh | sudo bash\n\n"
        "✅ خود اتصال سایت حذف یا قطع نشده است.",
        _site_keyboard(site, uid),
    )
    return True


async def callback(update: Update, context):
    q = update.callback_query
    uid = q.from_user.id
    data = q.data or ""

    if await _backup_version_guard(q, uid, data):
        return

    try:
        return await v12.callback(update, context)
    except Exception as exc:
        logger.exception("Bot action failed but site connection is preserved: callback=%s", data)
        site = _site_from_data(uid, data)
        try:
            await q.answer("عملیات ناموفق بود؛ اتصال سایت حفظ شده است.", show_alert=False)
        except Exception:
            pass

        detail = str(exc).strip() or exc.__class__.__name__
        if len(detail) > 700:
            detail = detail[:700] + "…"
        extra = ""
        if data.startswith(BACKUP_PREFIXES):
            extra = "\n\nاگر خطا مربوط به backup_status یا unknown_action است، سایت ایران باید به آخرین نسخه آپدیت شود."
        text = (
            "⚠️ اجرای این بخش ناموفق بود، اما اتصال سایت از ربات حذف نشده و همچنان ذخیره است.\n\n"
            f"خطا: {detail}{extra}\n\n"
            "از دکمه‌های زیر دوباره وارد همان سایت شوید."
        )
        return await _safe_reply(q, text, _site_keyboard(site, uid))


async def message(update: Update, context):
    try:
        return await v12.message(update, context)
    except Exception as exc:
        logger.exception("Bot text flow failed; saved site remains intact")
        uid = update.effective_user.id
        site_id = context.user_data.get("site_id")
        site = None
        try:
            if site_id and core.can_access(uid, int(site_id)):
                site = core.get_site(int(site_id))
        except Exception:
            site = None
        detail = str(exc).strip() or exc.__class__.__name__
        return await update.message.reply_text(
            "⚠️ این عملیات انجام نشد، ولی اتصال ذخیره‌شده سایت دست‌نخورده باقی ماند.\n\n"
            f"خطا: {detail[:700]}",
            reply_markup=_site_keyboard(site, uid),
        )


async def media(update: Update, context):
    try:
        return await v10.media(update, context)
    except Exception as exc:
        logger.exception("Bot media flow failed; saved site remains intact")
        uid = update.effective_user.id
        site_id = context.user_data.get("site_id")
        site = None
        try:
            if site_id and core.can_access(uid, int(site_id)):
                site = core.get_site(int(site_id))
        except Exception:
            site = None
        detail = str(exc).strip() or exc.__class__.__name__
        return await update.message.reply_text(
            "⚠️ دریافت/ارسال فایل ناموفق بود، اما اتصال سایت حذف نشده است.\n\n"
            f"خطا: {detail[:700]}",
            reply_markup=_site_keyboard(site, uid),
        )


def run():
    try:
        acquire_single_instance_lock()
    except RuntimeError as exc:
        logger.error("SanaShop bot refused duplicate startup: %s", exc)
        raise SystemExit(73) from exc

    core.db()
    app = Application.builder().token(core.TOKEN).post_init(v10.post_init).build()
    app.add_handler(CommandHandler("start", core.start))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.Document.ALL, media))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message))
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    run()
