#!/usr/bin/env python3
import asyncio
import base64
import io
import logging
import tempfile
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

import external_bot as core
import external_bot_plus as plus
import external_bot_v9 as v9

logger = logging.getLogger(__name__)
MAX_RESTORE_BYTES = 35 * 1024 * 1024


def _site(uid, sid):
    return plus.site_from(uid, sid)


def _settings_keyboard(sid, data):
    rows = [list(row) for row in v9._settings_keyboard(sid, data).inline_keyboard]
    rows.insert(-1, [InlineKeyboardButton("🔐 بکاپ", callback_data=f"backups_v10:{sid}")])
    return InlineKeyboardMarkup(rows)


async def _show_settings(q, site, sid):
    data = (await core.api(site, "settings_get"))["data"]
    phone = data.get("contact_phone") or "تنظیم نشده"
    text = (
        f"⚙️ تنظیمات فروشگاه {data.get('site_name') or site['name']}\n\n"
        f"☎️ شماره تماس بالای سایت: {phone}\n"
        f"🖼 لوگو: {'✅' if data.get('has_logo') else '❌'}\n"
        f"📜 قوانین: {'✅ تنظیم شده' if data.get('has_terms') else '❌ خالی'}\n"
        f"🚚 هزینه ارسال: {plus.money(data.get('shipping_fee'))} تومان\n"
        f"🎁 ارسال رایگان از: {plus.money(data.get('free_shipping_threshold'))} تومان\n\n"
        "تنظیمات ظاهری، شبکه‌های اجتماعی، فوتر، کاربران و بکاپ از همین بخش مدیریت می‌شوند."
    )
    return await q.edit_message_text(text, reply_markup=_settings_keyboard(sid, data))


def _fmt_time(value):
    if not value:
        return "-"
    return str(value).replace("T", " ")[:16]


async def _show_backups(q, site, sid):
    info = (await core.api(site, "backup_status", timeout=35))["data"]
    interval = int(info.get("interval_minutes") or 0)
    interval_text = f"هر {interval} دقیقه" if interval else "غیرفعال"
    text = (
        "🔐 بکاپ فروشگاه\n\n"
        f"⏱ زمان‌بندی: {interval_text}\n"
        f"🕒 آخرین بکاپ زمان‌بندی‌شده: {_fmt_time(info.get('last_backup_at'))}\n\n"
        "فایل .sanabackup شامل کاربران، سفارش‌ها، محصولات، تنظیمات و تصاویر است."
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 بکاپ همین حالا", callback_data=f"backup_now_v10:{sid}"), InlineKeyboardButton("⏱ زمان‌بندی", callback_data=f"backup_interval_v10:{sid}")],
        [InlineKeyboardButton("♻️ بازگردانی بکاپ", callback_data=f"backup_restore_v10:{sid}")],
        [InlineKeyboardButton("⬅️ تنظیمات فروشگاه", callback_data=f"settings:{sid}")],
    ])
    return await q.edit_message_text(text, reply_markup=kb)


async def _build_backup(site, label="manual"):
    data = (await core.api(site, "backup_create", {"label": label}, timeout=240))["data"]
    raw = base64.b64decode(data["backup_b64"])
    return raw, data.get("filename") or "sanashop-backup.sanabackup"


async def _send_backup(bot, chat_id, site, label="manual"):
    raw, filename = await _build_backup(site, label)
    document = io.BytesIO(raw)
    document.name = filename
    await bot.send_document(
        chat_id=chat_id,
        document=document,
        filename=filename,
        caption="🔐 بکاپ کامل SanaShop؛ شامل کاربران، سفارش‌ها، محصولات، تنظیمات و تصاویر",
        read_timeout=180,
        write_timeout=180,
    )
    return filename


async def scheduled_backup_loop(application):
    await asyncio.sleep(20)
    while True:
        try:
            with core.db() as conn:
                sites = conn.execute("SELECT * FROM sites ORDER BY id").fetchall()
            for site in sites:
                try:
                    status = (await core.api(site, "backup_status", timeout=25))["data"]
                    if not status.get("due"):
                        continue
                    delivered = False
                    raw, filename = await _build_backup(site, "auto")
                    for chat_id in plus.recipients_for(site["id"]):
                        try:
                            document = io.BytesIO(raw)
                            document.name = filename
                            await application.bot.send_document(
                                chat_id=chat_id,
                                document=document,
                                filename=filename,
                                caption="🔐 بکاپ زمان‌بندی‌شده SanaShop",
                                read_timeout=180,
                                write_timeout=180,
                            )
                            delivered = True
                        except Exception:
                            logger.exception("Could not send scheduled backup site=%s chat=%s", site["id"], chat_id)
                    if delivered:
                        await core.api(site, "backup_touch", timeout=25)
                except Exception:
                    logger.exception("Scheduled backup failed for site=%s", site["id"])
        except Exception:
            logger.exception("Scheduled backup loop error")
        await asyncio.sleep(60)


async def callback(update: Update, context):
    q = update.callback_query
    uid = q.from_user.id
    data = q.data or ""

    if data.startswith("settings:") and len(data.split(":")) == 2:
        _, sid = data.split(":")
        site = _site(uid, sid)
        if not site:
            return await q.answer("عدم دسترسی", show_alert=True)
        await q.answer()
        return await _show_settings(q, site, sid)

    if data.startswith("backups_v10:"):
        _, sid = data.split(":")
        site = _site(uid, sid)
        if not site:
            return await q.answer("عدم دسترسی", show_alert=True)
        await q.answer()
        return await _show_backups(q, site, sid)

    if data.startswith("backup_now_v10:"):
        _, sid = data.split(":")
        site = _site(uid, sid)
        if not site:
            return await q.answer("عدم دسترسی", show_alert=True)
        await q.answer("در حال ساخت بکاپ...")
        await q.edit_message_text("⏳ بکاپ کامل روی سرور ایران در حال ساخته‌شدن است...")
        try:
            filename = await _send_backup(context.bot, update.effective_chat.id, site, "manual")
            return await q.message.reply_text(
                f"✅ بکاپ ساخته و ارسال شد.\n{filename}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ بکاپ", callback_data=f"backups_v10:{sid}")]]),
            )
        except Exception as exc:
            return await q.message.reply_text(
                f"❌ ساخت یا ارسال بکاپ ناموفق بود:\n{exc}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ بکاپ", callback_data=f"backups_v10:{sid}")]]),
            )

    if data.startswith("backup_interval_v10:"):
        _, sid = data.split(":")
        site = _site(uid, sid)
        if not site:
            return await q.answer("عدم دسترسی", show_alert=True)
        await q.answer()
        context.user_data.clear()
        context.user_data.update(flow="v10_backup_interval", site_id=int(sid))
        return await q.edit_message_text("⏱ فاصله بکاپ خودکار را به دقیقه بفرستید.\nحداقل ۵ دقیقه؛ برای غیرفعال‌کردن ۰ بفرستید.")

    if data.startswith("backup_restore_v10:"):
        _, sid = data.split(":")
        site = _site(uid, sid)
        if not site:
            return await q.answer("عدم دسترسی", show_alert=True)
        await q.answer()
        context.user_data.clear()
        context.user_data.update(flow="v10_restore_upload", site_id=int(sid))
        return await q.edit_message_text("♻️ فایل .sanabackup را به‌صورت Document بفرستید.\nبعد از بررسی، تأیید نهایی می‌گیرم.")

    if data.startswith("backup_restore_confirm_v10:"):
        _, sid = data.split(":")
        site = _site(uid, sid)
        if not site:
            return await q.answer("عدم دسترسی", show_alert=True)
        path = Path(context.user_data.get("restore_path") or "")
        if not path.is_file():
            context.user_data.clear()
            return await q.answer("فایل موقت پیدا نشد؛ دوباره ارسال کنید.", show_alert=True)
        await q.answer("در حال بازگردانی...")
        await q.edit_message_text("⏳ بازگردانی بکاپ در حال انجام است. در این مدت سایت ممکن است چند لحظه پاسخ ندهد...")
        try:
            raw = path.read_bytes()
            result = await core.api(
                site,
                "backup_restore",
                {"filename": path.name, "backup_b64": base64.b64encode(raw).decode("ascii")},
                timeout=360,
            )
            created_at = (result.get("data") or {}).get("created_at") or "-"
            return await q.message.reply_text(
                f"✅ بکاپ با موفقیت بازگردانی شد.\nتاریخ فایل: {created_at}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ پنل سایت", callback_data=f"site_info:{sid}")]]),
            )
        except Exception as exc:
            return await q.message.reply_text(f"❌ بازگردانی ناموفق بود:\n{exc}")
        finally:
            path.unlink(missing_ok=True)
            context.user_data.clear()

    if data.startswith("backup_restore_cancel_v10:"):
        _, sid = data.split(":")
        path = Path(context.user_data.get("restore_path") or "")
        if path.is_file():
            path.unlink(missing_ok=True)
        context.user_data.clear()
        await q.answer("لغو شد")
        site = _site(uid, sid)
        if site:
            return await _show_backups(q, site, sid)
        return None

    return await v9.callback(update, context)


async def message(update: Update, context):
    if context.user_data.get("flow") == "v10_backup_interval":
        uid = update.effective_user.id
        site_id = context.user_data.get("site_id")
        text = (update.message.text or "").strip()
        if not site_id or not core.can_access(uid, int(site_id)):
            context.user_data.clear()
            return await update.message.reply_text("⛔️ دسترسی شما به این سایت لغو شده است.")
        if not text.isdigit():
            return await update.message.reply_text("فقط عدد بفرستید؛ مثال 60 یا برای غیرفعال‌کردن 0")
        minutes = int(text)
        if minutes != 0 and minutes < 5:
            return await update.message.reply_text("حداقل فاصله امن ۵ دقیقه است.")
        site = core.get_site(int(site_id))
        try:
            await core.api(site, "backup_interval_set", {"minutes": minutes}, timeout=35)
        except Exception as exc:
            return await update.message.reply_text(f"❌ ذخیره زمان‌بندی ناموفق بود:\n{exc}")
        context.user_data.clear()
        return await update.message.reply_text(
            "✅ بکاپ خودکار غیرفعال شد." if minutes == 0 else f"✅ بکاپ خودکار روی هر {minutes} دقیقه تنظیم شد.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔐 بکاپ", callback_data=f"backups_v10:{site_id}")]]),
        )
    return await v9.message(update, context)


async def media(update: Update, context):
    if context.user_data.get("flow") != "v10_restore_upload":
        return await plus.media(update, context)

    uid = update.effective_user.id
    site_id = context.user_data.get("site_id")
    if not site_id or not core.can_access(uid, int(site_id)):
        context.user_data.clear()
        return await update.message.reply_text("⛔️ دسترسی شما به این سایت لغو شده است.")
    doc = update.message.document
    if not doc or not (doc.file_name or "").lower().endswith(".sanabackup"):
        return await update.message.reply_text("فقط فایل .sanabackup را به‌صورت Document بفرستید.")
    if doc.file_size and doc.file_size > MAX_RESTORE_BYTES:
        return await update.message.reply_text("حجم فایل برای بازگردانی از طریق ربات زیاد است؛ حداکثر ۳۵ مگابایت.")

    handle = tempfile.NamedTemporaryFile(prefix="sanashop-restore-", suffix=".sanabackup", delete=False)
    handle.close()
    path = Path(handle.name)
    try:
        tg_file = await doc.get_file()
        await tg_file.download_to_drive(custom_path=str(path))
        if path.stat().st_size > MAX_RESTORE_BYTES:
            raise ValueError("حجم فایل بیشتر از ۳۵ مگابایت است.")
    except Exception as exc:
        path.unlink(missing_ok=True)
        return await update.message.reply_text(f"❌ دریافت فایل ناموفق بود:\n{exc}")

    context.user_data.update(flow="v10_restore_confirm", restore_path=str(path))
    return await update.message.reply_text(
        "⚠️ با تأیید، دیتابیس و تصاویر فعلی با محتوای این بکاپ جایگزین می‌شوند. ادامه می‌دهید؟",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ تأیید بازگردانی", callback_data=f"backup_restore_confirm_v10:{site_id}")],
            [InlineKeyboardButton("❌ لغو", callback_data=f"backup_restore_cancel_v10:{site_id}")],
        ]),
    )


async def post_init(application):
    await v9.post_init(application)
    application.create_task(scheduled_backup_loop(application), name="sanashop-backups-v10")


def run():
    core.db()
    app = Application.builder().token(core.TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", core.start))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.Document.ALL, media))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message))
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    run()
