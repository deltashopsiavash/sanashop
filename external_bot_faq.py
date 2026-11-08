"""Per-site FAQ editing from Telegram store settings."""
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

import external_bot as core

logger = logging.getLogger(__name__)
PREFIXES = ("faq_v22:", "faq_replace_v22:", "faq_append_v22:")
FLOWS = {"v22_faq_replace", "v22_faq_append"}


def handles(data):
    return str(data or "").startswith(PREFIXES)


def _site(uid, sid):
    try:
        sid = int(sid)
    except (TypeError, ValueError):
        return None
    return core.get_site(sid) if core.can_access(uid, sid) else None


async def callback(update, context):
    q = update.callback_query
    data = str(q.data or "")
    if not handles(data) or len(data.split(":")) != 2:
        return await q.answer("درخواست نامعتبر است.", show_alert=True)
    action, raw_sid = data.split(":")
    site = _site(q.from_user.id, raw_sid)
    if not site:
        return await q.answer("عدم دسترسی به این سایت", show_alert=True)
    sid = int(raw_sid)
    await q.answer()
    if action == "faq_v22":
        ping = (await core.api(site, "ping"))["site"]
        if "faq_edit_v22" not in ping.get("capabilities", []):
            return await q.edit_message_text(
                "⚠️ ابتدا نسخه سایت انتخاب‌شده را آپدیت کن تا سؤالات متداول از ربات قابل ویرایش شود.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ تنظیمات", callback_data=f"settings:{sid}")]]),
            )
        faq = (await core.api(site, "faq_get"))["data"]
        body = faq.get("body") or ""
        shown = body[:2700] + ("\n…" if len(body) > 2700 else "")
        return await q.edit_message_text(
            f"❓ سؤالات متداول سایت «{site['name']}»\n\n"
            f"{shown or 'هنوز سوال و پاسخی ثبت نشده است.'}\n\n"
            "متن با فاصله‌گذاری و خطوط جداگانه در صفحه سؤالات متداول سایت نمایش داده می‌شود.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✏️ جایگزینی کل متن", callback_data=f"faq_replace_v22:{sid}")],
                [InlineKeyboardButton("➕ افزودن سؤال و جواب", callback_data=f"faq_append_v22:{sid}")],
                [InlineKeyboardButton("⬅️ تنظیمات فروشگاه", callback_data=f"settings:{sid}")],
            ]),
        )
    if action in ("faq_replace_v22", "faq_append_v22"):
        context.user_data.clear()
        context.user_data.update(
            flow="v22_faq_replace" if action == "faq_replace_v22" else "v22_faq_append",
            site_id=sid,
        )
        return await q.edit_message_text(
            "❓ متن سؤالات متداول را بفرست. نمونه:\n\n"
            "سؤال: نحوه ارسال سفارش چگونه است؟\n"
            "جواب: سفارش پس از تأیید پرداخت آماده و ارسال می‌شود.\n\n"
            "سؤال: شرایط مرجوعی چیست؟\n"
            "جواب: از بخش قوانین و مقررات فروشگاه مطالعه کنید.\n\n"
            + ("تمام متن فعلی جایگزین می‌شود." if action == "faq_replace_v22" else "این متن به انتهای سؤالات فعلی اضافه می‌شود."),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ انصراف", callback_data=f"faq_v22:{sid}")]]),
        )


async def message(update, context):
    flow = context.user_data.get("flow")
    if flow not in FLOWS:
        return False
    sid = context.user_data.get("site_id")
    site = _site(update.effective_user.id, sid)
    if not site:
        context.user_data.clear()
        await update.message.reply_text("⛔️ به سایت انتخاب‌شده دسترسی ندارید.")
        return True
    text = (update.message.text or "").strip()
    if not text or len(text) > 15000:
        await update.message.reply_text("❌ متن سؤالات متداول نباید خالی یا بیش از ۱۵۰۰۰ حرف باشد.")
        return True
    try:
        if flow == "v22_faq_append":
            existing = (await core.api(site, "faq_get"))["data"].get("body") or ""
            text = (existing.strip() + "\n\n" + text).strip()
        if len(text) > 20000:
            await update.message.reply_text("❌ مجموع متن سؤالات متداول بیشتر از ۲۰ هزار حرف می‌شود.")
            return True
        await core.api(site, "faq_set", {"body": text})
    except Exception:
        logger.exception("FAQ update failed on site=%s", sid)
        await update.message.reply_text("❌ سؤالات ذخیره نشد. اتصال این سایت و نسخه API را بررسی کن.")
        return True
    context.user_data.clear()
    await update.message.reply_text(
        "✅ سؤالات متداول ذخیره شد و صفحه سایت به‌روزرسانی شد.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❓ مشاهده سؤالات", callback_data=f"faq_v22:{sid}")]]),
    )
    return True
