#!/usr/bin/env python3
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

import external_bot as core
import external_bot_plus as plus
import external_bot_v7 as v7


def _site(uid, sid):
    return plus.site_from(uid, sid)


def _fmt_date(value):
    if not value:
        return "-"
    return str(value).replace("T", " ")[:16]


def _user_text(u):
    lines = [
        "👤 مشخصات کامل مشتری",
        f"کد مشتری: {u.get('customer_code') or '-'}",
        f"نام: {u.get('first_name') or '-'}",
        f"نام خانوادگی: {u.get('last_name') or '-'}",
        f"ایمیل: {u.get('email') or '-'}",
        f"تلفن: {u.get('phone') or '-'}",
        f"وضعیت حساب: {'✅ فعال' if u.get('is_active') else '⛔️ غیرفعال'}",
        f"تاریخ عضویت: {_fmt_date(u.get('date_joined'))}",
        f"آخرین ورود: {_fmt_date(u.get('last_login'))}",
        "",
        f"🛒 کل سفارش‌ها: {u.get('order_count', 0)}",
        f"⏳ سفارش‌های در حال اجرا: {u.get('active_orders', 0)}",
        f"✅ تحویل‌شده: {u.get('completed_orders', 0)}",
        f"❌ لغوشده: {u.get('cancelled_orders', 0)}",
        f"💰 مجموع خرید موفق: {plus.money(u.get('total_spent'))} تومان",
    ]
    recent = u.get("orders") or []
    if recent:
        lines += ["", "📦 آخرین سفارش‌ها:"]
        for order in recent[:8]:
            lines.append(f"• {order['code']} | {order['status_label']} | {plus.money(order['total'])} تومان")
    return "\n".join(lines)[:3900]


async def callback(update: Update, context):
    q = update.callback_query
    uid = q.from_user.id
    data = q.data or ""

    if data.startswith("users:") and len(data.split(":")) == 2:
        _, sid = data.split(":")
        site = _site(uid, sid)
        if not site:
            return await q.answer("عدم دسترسی", show_alert=True)
        await q.answer()
        rows = (await core.api(site, "users"))["data"]
        keys = [
            [InlineKeyboardButton("🔎 جستجو با ایمیل / کد مشتری", callback_data=f"user_search_v7:{sid}")],
            [InlineKeyboardButton("📨 پیام همگانی ایمیلی", callback_data=f"broadcast_v8:{sid}")],
        ]
        for u in rows[:20]:
            keys.append([InlineKeyboardButton(
                f"{u.get('customer_code') or '-'} | {u.get('full_name') or u.get('email') or u['id']}",
                callback_data=f"user:{sid}:{u['id']}",
            )])
        keys.append([InlineKeyboardButton("⬅️ پنل سایت", callback_data=f"site_info:{sid}")])
        return await q.edit_message_text("👥 کاربران اخیر:\nجستجو، مدیریت مشخصات و ایمیل همگانی از همین بخش انجام می‌شود.", reply_markup=InlineKeyboardMarkup(keys))

    if data.startswith("user:") and len(data.split(":")) == 3:
        _, sid, user_id = data.split(":")
        site = _site(uid, sid)
        if not site:
            return await q.answer("عدم دسترسی", show_alert=True)
        await q.answer()
        u = (await core.api(site, "user_detail", {"id": int(user_id)}))["data"]
        keys = []
        for order in (u.get("orders") or [])[:4]:
            keys.append([InlineKeyboardButton(f"🧾 {order['code']} — {order['status_label']}", callback_data=f"order:{sid}:{order['id']}")])
        keys += [
            [InlineKeyboardButton("📱 تغییر تلفن", callback_data=f"user_phone_v8:{sid}:{user_id}"), InlineKeyboardButton("✉️ تغییر ایمیل", callback_data=f"user_email_v8:{sid}:{user_id}")],
            [InlineKeyboardButton("🔐 ارسال لینک بازیابی رمز", callback_data=f"user_reset_v8:{sid}:{user_id}")],
            [InlineKeyboardButton("🔄 فعال/غیرفعال کردن حساب", callback_data=f"user_toggle:{sid}:{user_id}")],
            [InlineKeyboardButton("⬅️ کاربران", callback_data=f"users:{sid}")],
        ]
        return await q.edit_message_text(_user_text(u), reply_markup=InlineKeyboardMarkup(keys))

    if data.startswith("user_email_v8:"):
        _, sid, user_id = data.split(":")
        site = _site(uid, sid)
        if not site:
            return await q.answer("عدم دسترسی", show_alert=True)
        await q.answer()
        context.user_data.clear()
        context.user_data.update(flow="v8_user_email", site_id=int(sid), user_id=int(user_id))
        return await q.edit_message_text("✉️ ایمیل جدید مشتری را بفرستید:")

    if data.startswith("user_phone_v8:"):
        _, sid, user_id = data.split(":")
        site = _site(uid, sid)
        if not site:
            return await q.answer("عدم دسترسی", show_alert=True)
        await q.answer()
        context.user_data.clear()
        context.user_data.update(flow="v8_user_phone", site_id=int(sid), user_id=int(user_id))
        return await q.edit_message_text("📱 شماره موبایل جدید را بفرستید؛ مثال: 09123456789")

    if data.startswith("user_reset_v8:"):
        _, sid, user_id = data.split(":")
        site = _site(uid, sid)
        if not site:
            return await q.answer("عدم دسترسی", show_alert=True)
        await q.answer("در حال ارسال...")
        try:
            result = await core.api(site, "user_password_reset", {"id": int(user_id)}, timeout=45)
            email = result["data"]["email"]
            return await q.edit_message_text(
                f"✅ لینک بازیابی رمز به {email} ارسال شد.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ مشتری", callback_data=f"user:{sid}:{user_id}")]]),
            )
        except Exception as exc:
            return await q.edit_message_text(f"❌ ارسال لینک بازیابی ناموفق بود:\n{exc}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ مشتری", callback_data=f"user:{sid}:{user_id}")]]))

    if data.startswith("broadcast_v8:"):
        _, sid = data.split(":")
        site = _site(uid, sid)
        if not site:
            return await q.answer("عدم دسترسی", show_alert=True)
        await q.answer()
        context.user_data.clear()
        context.user_data.update(flow="v8_broadcast_subject", site_id=int(sid))
        return await q.edit_message_text("📨 عنوان ایمیل همگانی را بفرستید:")

    if data.startswith("broadcast_confirm_v8:"):
        _, sid = data.split(":")
        site = _site(uid, sid)
        if not site:
            return await q.answer("عدم دسترسی", show_alert=True)
        subject = context.user_data.get("broadcast_subject")
        body = context.user_data.get("broadcast_body")
        if not subject or not body:
            context.user_data.clear()
            return await q.answer("متن پیام منقضی شده است.", show_alert=True)
        await q.answer("در حال ارسال...")
        try:
            result = await core.api(site, "broadcast_email", {"subject": subject, "body": body}, timeout=120)
            info = result["data"]
            context.user_data.clear()
            return await q.edit_message_text(
                f"✅ ایمیل همگانی ارسال شد.\nگیرندگان: {info.get('recipients', 0)}\nارسال‌شده: {info.get('sent', 0)}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ کاربران", callback_data=f"users:{sid}")]]),
            )
        except Exception as exc:
            return await q.edit_message_text(f"❌ ارسال همگانی ناموفق بود:\n{exc}")

    if data.startswith("broadcast_cancel_v8:"):
        _, sid = data.split(":")
        context.user_data.clear()
        await q.answer("لغو شد")
        return await q.edit_message_text("ارسال ایمیل همگانی لغو شد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ کاربران", callback_data=f"users:{sid}")]]))

    return await v7.callback(update, context)


async def message(update: Update, context):
    uid = update.effective_user.id
    flow = context.user_data.get("flow")
    text = (update.message.text or "").strip()
    site_id = context.user_data.get("site_id")

    if flow in {"v8_user_email", "v8_user_phone", "v8_broadcast_subject", "v8_broadcast_body"}:
        if not site_id or not core.can_access(uid, int(site_id)):
            context.user_data.clear()
            return await update.message.reply_text("⛔️ دسترسی شما به این سایت لغو شده است.")
        site = core.get_site(int(site_id))

        if flow == "v8_user_email":
            if "@" not in text or "." not in text.rsplit("@", 1)[-1]:
                return await update.message.reply_text("ایمیل معتبر بفرستید؛ مثال buyer@example.com")
            user_id = int(context.user_data["user_id"])
            try:
                await core.api(site, "user_update", {"id": user_id, "email": text}, timeout=35)
            except Exception as exc:
                return await update.message.reply_text(f"❌ تغییر ایمیل ناموفق بود:\n{exc}")
            context.user_data.clear()
            return await update.message.reply_text("✅ ایمیل مشتری تغییر کرد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ مشتری", callback_data=f"user:{site_id}:{user_id}")]]))

        if flow == "v8_user_phone":
            user_id = int(context.user_data["user_id"])
            try:
                await core.api(site, "user_update", {"id": user_id, "phone": text}, timeout=35)
            except Exception as exc:
                return await update.message.reply_text(f"❌ تغییر شماره ناموفق بود:\n{exc}")
            context.user_data.clear()
            return await update.message.reply_text("✅ شماره تلفن مشتری تغییر کرد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ مشتری", callback_data=f"user:{site_id}:{user_id}")]]))

        if flow == "v8_broadcast_subject":
            if len(text) < 2 or len(text) > 180:
                return await update.message.reply_text("عنوان باید بین ۲ تا ۱۸۰ کاراکتر باشد.")
            context.user_data["broadcast_subject"] = text
            context.user_data["flow"] = "v8_broadcast_body"
            return await update.message.reply_text("حالا متن کامل ایمیل را بفرستید:")

        if flow == "v8_broadcast_body":
            if len(text) < 2 or len(text) > 20000:
                return await update.message.reply_text("متن پیام باید بین ۲ تا ۲۰ هزار کاراکتر باشد.")
            context.user_data["broadcast_body"] = text
            context.user_data["flow"] = "v8_broadcast_confirm"
            preview = text[:2600] + ("…" if len(text) > 2600 else "")
            return await update.message.reply_text(
                f"📨 پیش‌نمایش ایمیل همگانی\n\nعنوان: {context.user_data['broadcast_subject']}\n\n{preview}\n\nارسال شود؟",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ ارسال به همه کاربران فعال", callback_data=f"broadcast_confirm_v8:{site_id}")],
                    [InlineKeyboardButton("❌ لغو", callback_data=f"broadcast_cancel_v8:{site_id}")],
                ]),
            )

    return await v7.message(update, context)


async def post_init(application):
    return await v7.post_init(application)


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
