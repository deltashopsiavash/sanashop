#!/usr/bin/env python3
import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

import external_bot as core
import external_bot_plus as plus
import external_bot_v8 as v8


def _site(uid, sid):
    return plus.site_from(uid, sid)


def site_panel(site, uid):
    """Compact main panel: operational actions first, configuration last."""
    sid = site["id"]
    rows = [
        [InlineKeyboardButton("📊 داشبورد", callback_data=f"dash:{sid}")],
        [InlineKeyboardButton("🛍 محصولات", callback_data=f"products:{sid}"), InlineKeyboardButton("🗂 دسته‌ها", callback_data=f"categories:{sid}")],
        [InlineKeyboardButton("🛒 سفارش‌ها", callback_data=f"orders:{sid}"), InlineKeyboardButton("🧾 رسیدها", callback_data=f"receipts:{sid}")],
        [InlineKeyboardButton("🎞 بنرها", callback_data=f"banners:{sid}"), InlineKeyboardButton("🔴 معرفی محصولات", callback_data=f"stories:{sid}")],
        [InlineKeyboardButton("🎟 کد تخفیف", callback_data=f"discounts:{sid}")],
        [InlineKeyboardButton("⚙️ تنظیمات فروشگاه", callback_data=f"settings:{sid}")],
    ]
    if core.is_owner(uid):
        rows.append([InlineKeyboardButton("⬅️ سایت‌های متصل", callback_data="owner_sites")])
    return InlineKeyboardMarkup(rows)


core.site_panel = site_panel


def _settings_keyboard(sid, data):
    phone_label = "☎️ شماره تلفن ✅" if data.get("has_contact_phone") else "⚪ ثبت شماره تلفن"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(phone_label, callback_data=f"contact_phone_v9:{sid}")],
        [InlineKeyboardButton("🖼 لوگوی سایت", callback_data=f"logo:{sid}"), InlineKeyboardButton("✏️ نام سایت", callback_data=f"v4_name:{sid}")],
        [InlineKeyboardButton("📣 اعلان", callback_data=f"v4_announcement:{sid}"), InlineKeyboardButton("💳 اطلاعات کارت", callback_data=f"v4_card:{sid}")],
        [InlineKeyboardButton("🚚 هزینه ارسال", callback_data=f"v4_shipping:{sid}"), InlineKeyboardButton("🎁 حد ارسال رایگان", callback_data=f"v4_free:{sid}")],
        [InlineKeyboardButton("📜 قوانین و مقررات", callback_data=f"terms_v7:{sid}")],
        [InlineKeyboardButton("🔗 شبکه‌های اجتماعی", callback_data=f"socials:{sid}"), InlineKeyboardButton("🦶 فوتر", callback_data=f"footer:{sid}")],
        [InlineKeyboardButton("👥 کاربران", callback_data=f"users:{sid}")],
        [InlineKeyboardButton("⬅️ پنل سایت", callback_data=f"site_info:{sid}")],
    ])


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
        "تنظیمات ظاهری، شبکه‌های اجتماعی، فوتر و کاربران از همین بخش مدیریت می‌شوند."
    )
    return await q.edit_message_text(text, reply_markup=_settings_keyboard(sid, data))


def _normalize_phone(value):
    value = str(value or "").strip()
    fa = "۰۱۲۳۴۵۶۷۸۹"
    ar = "٠١٢٣٤٥٦٧٨٩"
    value = value.translate(str.maketrans(fa + ar, "0123456789" * 2))
    value = re.sub(r"[\s\-()]+", "", value)
    if value.startswith("00"):
        value = "+" + value[2:]
    return value


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

    if data.startswith("contact_phone_v9:"):
        _, sid = data.split(":")
        site = _site(uid, sid)
        if not site:
            return await q.answer("عدم دسترسی", show_alert=True)
        await q.answer()
        info = (await core.api(site, "settings_get"))["data"]
        phone = (info.get("contact_phone") or "").strip()
        if phone:
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("✏️ تغییر شماره", callback_data=f"contact_phone_edit_v9:{sid}"), InlineKeyboardButton("🗑 حذف شماره", callback_data=f"contact_phone_remove_v9:{sid}")],
                [InlineKeyboardButton("⬅️ تنظیمات فروشگاه", callback_data=f"settings:{sid}")],
            ])
            return await q.edit_message_text(
                f"☎️ شماره تلفن بالای سایت\n\nشماره فعلی: {phone}\n\nاین شماره مستقل از شماره فوتر است.",
                reply_markup=kb,
            )
        context.user_data.clear()
        context.user_data.update(flow="v9_contact_phone", site_id=int(sid))
        return await q.edit_message_text(
            "☎️ شماره‌ای که باید برای آیکن تلفن بالای سایت نمایش داده شود بفرستید.\nمثال: 02112345678 یا 09123456789"
        )

    if data.startswith("contact_phone_edit_v9:"):
        _, sid = data.split(":")
        site = _site(uid, sid)
        if not site:
            return await q.answer("عدم دسترسی", show_alert=True)
        await q.answer()
        context.user_data.clear()
        context.user_data.update(flow="v9_contact_phone", site_id=int(sid))
        return await q.edit_message_text("☎️ شماره تلفن جدید را بفرستید:")

    if data.startswith("contact_phone_remove_v9:"):
        _, sid = data.split(":")
        site = _site(uid, sid)
        if not site:
            return await q.answer("عدم دسترسی", show_alert=True)
        await q.answer("حذف شد")
        await core.api(site, "settings_update", {"contact_phone": ""})
        return await _show_settings(q, site, sid)

    return await v8.callback(update, context)


async def message(update: Update, context):
    if context.user_data.get("flow") == "v9_contact_phone":
        uid = update.effective_user.id
        site_id = context.user_data.get("site_id")
        if not site_id or not core.can_access(uid, int(site_id)):
            context.user_data.clear()
            return await update.message.reply_text("⛔️ دسترسی شما به این سایت لغو شده است.")

        phone = _normalize_phone(update.message.text)
        if not re.fullmatch(r"\+?\d{7,15}", phone):
            return await update.message.reply_text("شماره معتبر نیست. فقط شماره تماس را بفرستید؛ مثال 02112345678 یا 09123456789")

        site = core.get_site(int(site_id))
        await core.api(site, "settings_update", {"contact_phone": phone})
        context.user_data.clear()
        return await update.message.reply_text(
            f"✅ شماره تماس بالای سایت روی {phone} تنظیم شد.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⚙️ تنظیمات فروشگاه", callback_data=f"settings:{site_id}")]]),
        )

    return await v8.message(update, context)


async def post_init(application):
    return await v8.post_init(application)


def run():
    core.db()
    app = Application.builder().token(core.TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", core.start))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.Document.ALL, plus.media))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message))
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    run()
