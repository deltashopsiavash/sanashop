#!/usr/bin/env python3
import base64
import io
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

import external_bot as core
import external_bot_plus as plus
import external_bot_v5 as v5
from bot_resilience import resilient_api, resilient_notification_loop

logger = logging.getLogger(__name__)
ORIGINAL_SEND_EVENT = plus.send_event

# Upgrade every inherited API call to the stable keep-alive/retry transport.
core.api = resilient_api


def _site(uid, sid):
    return plus.site_from(uid, sid)


def _back(sid, label="⬅️ پنل سایت"):
    return InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data=f"site_info:{sid}")]])


def _fmt_date(value):
    if not value:
        return "-"
    return str(value).replace("T", " ")[:16]


async def send_event(application, site, event):
    """Keep v5 notifications and attach product photos to new-order reports."""
    delivered = await ORIGINAL_SEND_EVENT(application, site, event)
    if event.get("kind") != "order_created":
        return delivered

    payload = event.get("payload") or {}
    prepared = []
    seen = set()
    for item in (payload.get("items") or [])[:8]:
        product_id = item.get("product_id")
        if not product_id or product_id in seen:
            continue
        seen.add(product_id)
        try:
            image = (await core.api(site, "product_image", {"id": product_id}, timeout=35))["data"]
            prepared.append(
                (
                    base64.b64decode(image["image_b64"]),
                    image.get("filename") or "product.jpg",
                    f"🛍 {item.get('title','محصول')} × {item.get('quantity',1)}\n{plus.money(item.get('total'))} تومان",
                )
            )
        except Exception as exc:
            logger.info("Product image unavailable site=%s product=%s: %s", site["id"], product_id, exc)

    if not prepared:
        return delivered

    for chat_id in plus.recipients_for(site["id"]):
        for raw, filename, caption in prepared:
            try:
                photo = io.BytesIO(raw)
                photo.name = filename
                await application.bot.send_photo(chat_id=chat_id, photo=photo, caption=caption)
                delivered = True
            except Exception:
                logger.exception("Could not send order product image to %s", chat_id)
    return delivered


plus.send_event = send_event


async def notification_loop(application):
    await resilient_notification_loop(application, core, plus)


async def post_init(application):
    application.create_task(notification_loop(application), name="sanashop-site-events-v7")


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
        x = (await core.api(site, "settings_get"))["data"]
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🖼 لوگوی سایت", callback_data=f"logo:{sid}"), InlineKeyboardButton("📣 اعلان", callback_data=f"v4_announcement:{sid}")],
            [InlineKeyboardButton("✏️ نام سایت", callback_data=f"v4_name:{sid}"), InlineKeyboardButton("📜 قوانین و مقررات", callback_data=f"terms_v7:{sid}")],
            [InlineKeyboardButton("🦶 تنظیمات فوتر", callback_data=f"footer:{sid}"), InlineKeyboardButton("💳 اطلاعات کارت", callback_data=f"v4_card:{sid}")],
            [InlineKeyboardButton("🚚 هزینه ارسال", callback_data=f"v4_shipping:{sid}"), InlineKeyboardButton("🎁 حد ارسال رایگان", callback_data=f"v4_free:{sid}")],
            [InlineKeyboardButton("⬅️ پنل سایت", callback_data=f"site_info:{sid}")],
        ])
        text = (
            f"⚙️ تنظیمات {x['site_name']}\n"
            f"لوگو: {'✅' if x.get('has_logo') else '❌'}\n"
            f"اعلان: {x.get('announcement') or '-'}\n"
            f"قوانین: {'✅ تنظیم شده' if x.get('has_terms') else '❌ هنوز خالی'}\n"
            f"ارسال: {plus.money(x.get('shipping_fee'))} تومان\n"
            f"ارسال رایگان از: {plus.money(x.get('free_shipping_threshold'))} تومان"
        )
        return await q.edit_message_text(text, reply_markup=kb)

    if data.startswith("terms_v7:"):
        _, sid = data.split(":")
        site = _site(uid, sid)
        if not site:
            return await q.answer("عدم دسترسی", show_alert=True)
        await q.answer()
        x = (await core.api(site, "settings_get"))["data"]
        terms = (x.get("terms_text") or "").strip()
        shown = terms[:2600] + ("…" if len(terms) > 2600 else "")
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ تنظیم / ویرایش قوانین", callback_data=f"terms_edit_v7:{sid}")],
            [InlineKeyboardButton("⬅️ تنظیمات", callback_data=f"settings:{sid}")],
        ])
        return await q.edit_message_text(f"📜 قوانین و مقررات\n\n{shown or 'هنوز متنی ثبت نشده است.'}", reply_markup=kb)

    if data.startswith("terms_edit_v7:"):
        _, sid = data.split(":")
        site = _site(uid, sid)
        if not site:
            return await q.answer("عدم دسترسی", show_alert=True)
        await q.answer()
        context.user_data.clear()
        context.user_data.update(flow="v7_terms_edit", site_id=int(sid))
        return await q.edit_message_text("📜 متن کامل قوانین و مقررات را بفرستید.\nاین متن در لینک «قوانین و مقررات» سایت نمایش داده می‌شود.")

    if data.startswith("users:") and len(data.split(":")) == 2:
        _, sid = data.split(":")
        site = _site(uid, sid)
        if not site:
            return await q.answer("عدم دسترسی", show_alert=True)
        await q.answer()
        rows = (await core.api(site, "users"))["data"]
        keys = [[InlineKeyboardButton(
            f"{u.get('customer_code') or '-'} | {u.get('full_name') or u.get('email') or u['id']}",
            callback_data=f"user:{sid}:{u['id']}",
        )] for u in rows[:20]]
        keys.insert(0, [InlineKeyboardButton("🔎 جستجو با ایمیل / کد مشتری", callback_data=f"user_search_v7:{sid}")])
        keys.append([InlineKeyboardButton("⬅️ پنل سایت", callback_data=f"site_info:{sid}")])
        return await q.edit_message_text("👥 کاربران اخیر:\nبرای پیدا کردن سریع مشتری از جستجو استفاده کن.", reply_markup=InlineKeyboardMarkup(keys))

    if data.startswith("user_search_v7:"):
        _, sid = data.split(":")
        site = _site(uid, sid)
        if not site:
            return await q.answer("عدم دسترسی", show_alert=True)
        await q.answer()
        context.user_data.clear()
        context.user_data.update(flow="v7_user_search", site_id=int(sid))
        return await q.edit_message_text("🔎 ایمیل یا کد مشتری را بفرست.\nمثال: buyer@example.com یا V1001\nشماره موبایل هم قابل جستجو است.")

    if data.startswith("user:") and len(data.split(":")) == 3:
        _, sid, user_id = data.split(":")
        site = _site(uid, sid)
        if not site:
            return await q.answer("عدم دسترسی", show_alert=True)
        await q.answer()
        u = (await core.api(site, "user_detail", {"id": int(user_id)}))["data"]
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
            f"🛒 کل سفارش‌ها: {u.get('order_count',0)}",
            f"⏳ سفارش‌های در حال اجرا: {u.get('active_orders',0)}",
            f"✅ تحویل‌شده: {u.get('completed_orders',0)}",
            f"❌ لغوشده: {u.get('cancelled_orders',0)}",
            f"💰 مجموع خرید موفق: {plus.money(u.get('total_spent'))} تومان",
        ]
        recent = u.get("orders") or []
        if recent:
            lines += ["", "📦 آخرین سفارش‌ها:"]
            for order in recent[:8]:
                lines.append(f"• {order['code']} | {order['status_label']} | {plus.money(order['total'])} تومان")
        keys = []
        for order in recent[:5]:
            keys.append([InlineKeyboardButton(f"🧾 {order['code']} — {order['status_label']}", callback_data=f"order:{sid}:{order['id']}")])
        keys.append([InlineKeyboardButton("🔄 فعال/غیرفعال کردن حساب", callback_data=f"user_toggle:{sid}:{user_id}")])
        keys.append([InlineKeyboardButton("⬅️ کاربران", callback_data=f"users:{sid}")])
        return await q.edit_message_text("\n".join(lines)[:3900], reply_markup=InlineKeyboardMarkup(keys))

    if data.startswith("order:") and len(data.split(":")) == 3:
        _, sid, order_id = data.split(":")
        site = _site(uid, sid)
        if not site:
            return await q.answer("عدم دسترسی", show_alert=True)
        await q.answer()
        o = (await core.api(site, "order_detail", {"id": int(order_id)}))["data"]
        lines = [
            f"🛒 سفارش {o['code']}",
            f"مشتری: {o.get('full_name') or '-'}",
            f"کد مشتری: {o.get('customer_code') or '-'}",
            f"موبایل: {o.get('mobile') or '-'}",
            f"ایمیل: {o.get('email') or '-'}",
            f"آدرس: {o.get('province','')}، {o.get('city','')} — {o.get('address','')}",
            f"کد پستی: {o.get('postal_code') or '-'}",
            f"مبلغ: {plus.money(o.get('total'))} تومان",
            f"روش پرداخت: {o.get('payment_method_label') or o.get('payment_method') or '-'}",
            f"وضعیت: {o.get('status_label') or o.get('status')}",
            f"رسید: {o.get('receipt_status') or '-'}",
            f"کد رهگیری: {o.get('tracking_code') or '-'}",
            "",
            "📦 محصولات:",
        ]
        for item in o.get("items") or []:
            lines.append(f"• {item.get('title')} × {item.get('quantity')} — {plus.money(item.get('total'))} تومان")
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ پرداخت", callback_data=f"order_status:{sid}:{o['id']}:paid"), InlineKeyboardButton("📦 آماده‌سازی", callback_data=f"order_status:{sid}:{o['id']}:processing")],
            [InlineKeyboardButton("🚚 کد رهگیری", callback_data=f"order_track:{sid}:{o['id']}"), InlineKeyboardButton("❌ لغو", callback_data=f"order_status:{sid}:{o['id']}:cancelled")],
            [InlineKeyboardButton("⬅️ سفارش‌ها", callback_data=f"orders:{sid}")],
        ])
        return await q.edit_message_text("\n".join(lines)[:3900], reply_markup=kb)

    if data.startswith("receipt_set:"):
        parts = data.split(":")
        if len(parts) == 4:
            _, sid, receipt_id, status = parts
            site = _site(uid, sid)
            if not site:
                return await q.answer("عدم دسترسی", show_alert=True)
            await q.answer("در حال ثبت...")
            try:
                await core.api(site, "receipt_update", {"id": int(receipt_id), "status": status}, timeout=35)
                detail = (await core.api(site, "receipt_detail", {"id": int(receipt_id)}))["data"]
                result = "✅ رسید تأیید شد و سفارش پرداخت‌شده ثبت شد." if status == "approved" else "❌ رسید رد شد."
                caption = f"{result}\nسفارش: {detail.get('order_code','-')}\nمبلغ: {plus.money(detail.get('total'))} تومان"
                if q.message.photo:
                    try:
                        return await q.edit_message_caption(caption=caption, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ رسیدها", callback_data=f"receipts:{sid}")]]))
                    except Exception:
                        pass
                return await q.edit_message_text(caption, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ رسیدها", callback_data=f"receipts:{sid}")]]))
            except Exception as exc:
                return await q.message.reply_text(f"❌ ثبت وضعیت رسید ناموفق بود:\n{exc}", reply_markup=_back(sid))

    return await v5.callback(update, context)


async def message(update: Update, context):
    uid = update.effective_user.id
    flow = context.user_data.get("flow")
    text = (update.message.text or "").strip()
    site_id = context.user_data.get("site_id")

    if flow == "v7_terms_edit":
        if not site_id or not core.can_access(uid, int(site_id)):
            context.user_data.clear()
            return await update.message.reply_text("⛔️ دسترسی شما به این سایت لغو شده است.")
        if len(text) < 10:
            return await update.message.reply_text("متن قوانین خیلی کوتاه است؛ متن کامل‌تری بفرستید.")
        if len(text) > 15000:
            return await update.message.reply_text("متن قوانین حداکثر ۱۵ هزار کاراکتر باشد.")
        site = core.get_site(int(site_id))
        await core.api(site, "settings_update", {"terms_text": text}, timeout=35)
        context.user_data.clear()
        return await update.message.reply_text("✅ قوانین و مقررات ذخیره و لینک سایت هم به‌روزرسانی شد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📜 مشاهده قوانین", callback_data=f"terms_v7:{site_id}")]]))

    if flow == "v7_user_search":
        if not site_id or not core.can_access(uid, int(site_id)):
            context.user_data.clear()
            return await update.message.reply_text("⛔️ دسترسی شما به این سایت لغو شده است.")
        if len(text) < 2:
            return await update.message.reply_text("ایمیل، کد مشتری یا شماره موبایل را کامل‌تر بفرستید.")
        site = core.get_site(int(site_id))
        rows = (await core.api(site, "user_search", {"query": text}, timeout=25))["data"]
        if not rows:
            return await update.message.reply_text("کاربری با این مشخصات پیدا نشد. دوباره جستجو کن.")
        keys = [[InlineKeyboardButton(
            f"{u.get('customer_code') or '-'} | {u.get('full_name') or u.get('email') or u['id']}",
            callback_data=f"user:{site_id}:{u['id']}",
        )] for u in rows[:20]]
        keys.append([InlineKeyboardButton("⬅️ کاربران", callback_data=f"users:{site_id}")])
        context.user_data.clear()
        return await update.message.reply_text(f"🔎 {len(rows)} نتیجه پیدا شد:", reply_markup=InlineKeyboardMarkup(keys))

    return await v5.message(update, context)


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
