#!/usr/bin/env python3
import asyncio
import base64
import io
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

import external_bot as core

logger = logging.getLogger(__name__)
ORIGINAL_CALLBACK = core.callback
ORIGINAL_MESSAGE = core.message
ORIGINAL_PHOTO = core.photo


def money(value):
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value or 0)


def site_from(uid, site_id):
    try:
        site_id = int(site_id)
    except Exception:
        return None
    if not core.can_access(uid, site_id):
        return None
    return core.get_site(site_id)


def recipients_for(site_id):
    recipients = {core.OWNER_ID}
    with core.db() as conn:
        rows = conn.execute("SELECT telegram_id FROM site_admins WHERE site_id=?", (site_id,)).fetchall()
        recipients.update(int(row["telegram_id"]) for row in rows)
    return recipients


def event_text(event):
    payload = event.get("payload") or {}
    kind = event.get("kind")
    if kind == "order_created":
        lines = [
            "🧾 فاکتور جدید ساخته شد",
            f"کد: {payload.get('code','-')}",
            f"مشتری: {payload.get('full_name','-')}",
            f"موبایل: {payload.get('mobile','-')}",
            f"آدرس: {payload.get('province','')}، {payload.get('city','')} — {payload.get('address','')}",
            f"روش پرداخت: {payload.get('payment_method_label','-')}",
            f"جمع کالاها: {money(payload.get('subtotal'))} تومان",
        ]
        if payload.get("discount_amount"):
            lines.append(f"تخفیف: {money(payload.get('discount_amount'))} تومان")
        lines += [
            f"ارسال: {'رایگان' if not payload.get('shipping') else money(payload.get('shipping')) + ' تومان'}",
            f"مبلغ نهایی: {money(payload.get('total'))} تومان",
            "",
            "📦 محصولات:",
        ]
        for item in payload.get("items") or []:
            lines.append(f"• {item.get('title')} × {item.get('quantity')} — {money(item.get('total'))} تومان")
        remaining = int(payload.get("reservation_remaining_seconds") or 0)
        if remaining:
            lines += ["", f"⏳ رزرو موجودی: حدود {max(1, remaining // 60)} دقیقه"]
        return "\n".join(lines)
    if kind == "payment_success":
        return f"✅ پرداخت تأیید شد\nسفارش: {payload.get('code','-')}\nمبلغ: {money(payload.get('total'))} تومان\nمشتری: {payload.get('full_name','-')}"
    if kind == "payment_failed":
        return f"❌ پرداخت ناموفق/لغوشده\nسفارش: {payload.get('code','-')}\nمبلغ: {money(payload.get('total'))} تومان"
    if kind == "reservation_expired":
        return f"⌛ مهلت رزرو فاکتور تمام شد\nسفارش: {payload.get('code','-')}\nمشتری: {payload.get('full_name','-')}"
    if kind == "order_status":
        return f"📦 تغییر وضعیت سفارش\nسفارش: {payload.get('code','-')}\nوضعیت: {payload.get('status_label') or payload.get('status','-')}\nمبلغ: {money(payload.get('total'))} تومان"
    return f"🔔 رویداد جدید سایت\n{kind}"


async def send_event(application, site, event):
    payload = event.get("payload") or {}
    recipients = recipients_for(site["id"])
    delivered = False
    if event.get("kind") == "receipt_uploaded" and payload.get("receipt_id"):
        try:
            image_data = (await core.api(site, "receipt_image", {"id": payload["receipt_id"]}, timeout=45))["data"]
            raw = base64.b64decode(image_data["image_b64"])
            caption = (
                f"🧾 رسید کارت‌به‌کارت جدید\n"
                f"سفارش: {payload.get('code','-')}\n"
                f"مشتری: {payload.get('full_name','-')}\n"
                f"مبلغ: {money(payload.get('total'))} تومان"
            )
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("✅ تأیید رسید", callback_data=f"receipt_set:{site['id']}:{payload['receipt_id']}:approved"), InlineKeyboardButton("❌ رد رسید", callback_data=f"receipt_set:{site['id']}:{payload['receipt_id']}:rejected")]])
            for chat_id in recipients:
                try:
                    photo = io.BytesIO(raw)
                    photo.name = image_data.get("filename") or "receipt.jpg"
                    await application.bot.send_photo(chat_id=chat_id, photo=photo, caption=caption, reply_markup=keyboard)
                    delivered = True
                except Exception:
                    logger.exception("Could not send receipt event to %s", chat_id)
        except Exception:
            logger.exception("Could not load receipt image for site %s", site["id"])
        return delivered

    text = event_text(event)
    keyboard = None
    if payload.get("order_id"):
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("باز کردن سفارش", callback_data=f"order:{site['id']}:{payload['order_id']}")]])
    for chat_id in recipients:
        try:
            await application.bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard)
            delivered = True
        except Exception:
            logger.exception("Could not send site event to %s", chat_id)
    return delivered


async def notification_loop(application):
    await asyncio.sleep(3)
    while True:
        try:
            with core.db() as conn:
                sites = conn.execute("SELECT * FROM sites ORDER BY id").fetchall()
            for site in sites:
                try:
                    events = (await core.api(site, "events_poll", {"limit": 20}, timeout=20))["data"]
                except Exception:
                    continue
                ack = []
                for event in events:
                    if await send_event(application, site, event):
                        ack.append(event["id"])
                if ack:
                    try:
                        await core.api(site, "events_ack", {"ids": ack}, timeout=20)
                    except Exception:
                        logger.exception("Could not ack events for site %s", site["id"])
        except Exception:
            logger.exception("Notification loop error")
        await asyncio.sleep(8)


async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    data = q.data or ""

    if data.startswith("product:"):
        parts = data.split(":")
        if len(parts) == 3:
            site = site_from(uid, parts[1])
            if not site:
                return await q.answer("به این سایت دسترسی ندارید.", show_alert=True)
            await q.answer()
            p = (await core.api(site, "product_detail", {"id": int(parts[2])}))["data"]
            old = p.get("compare_at_price")
            text = (
                f"🛍 {p['name']}\n"
                f"کد: {p['sku']}\n"
                f"قیمت جدید: {money(p['price'])} تومان\n"
                f"قیمت قبلی: {money(old) + ' تومان' if old else '-'}\n"
                f"موجودی کل: {p['stock']}\n"
                f"رزرو: {p.get('reserved_stock',0)} | قابل فروش: {p.get('available_stock',p['stock'])}\n"
                f"شگفت‌انگیز: {'✅' if p['is_amazing'] else '❌'}\n"
                f"وضعیت: {'فعال' if p['is_active'] else 'غیرفعال'}"
            )
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("💰 قیمت جدید", callback_data=f"prod_price:{site['id']}:{p['id']}"), InlineKeyboardButton("🏷 قیمت قبلی", callback_data=f"prod_old:{site['id']}:{p['id']}")],
                [InlineKeyboardButton("📦 موجودی", callback_data=f"prod_stock:{site['id']}:{p['id']}"), InlineKeyboardButton("🔥 شگفت‌انگیز", callback_data=f"prod_amazing:{site['id']}:{p['id']}")],
                [InlineKeyboardButton("🔄 فعال/غیرفعال", callback_data=f"prod_toggle:{site['id']}:{p['id']}"), InlineKeyboardButton("🖼 تعویض عکس", callback_data=f"prod_photo:{site['id']}:{p['id']}")],
                [InlineKeyboardButton("⬅️ محصولات", callback_data=f"products:{site['id']}")],
            ])
            return await q.edit_message_text(text, reply_markup=kb)

    if data.startswith("prod_old:"):
        _, sid, pid = data.split(":")
        site = site_from(uid, sid)
        if not site:
            return await q.answer("عدم دسترسی", show_alert=True)
        await q.answer()
        context.user_data.clear()
        context.user_data.update(flow="prod_old_price", site_id=int(sid), product_id=int(pid))
        return await q.edit_message_text("قیمت قبلی/خط‌خورده را بفرستید. مثال: 2,900,000\nبرای حذف قیمت قبلی عدد 0 را بفرستید.")

    if data.startswith("category:"):
        parts = data.split(":")
        if len(parts) == 3:
            site = site_from(uid, parts[1])
            if not site:
                return await q.answer("عدم دسترسی", show_alert=True)
            await q.answer()
            c = (await core.api(site, "category_detail", {"id": int(parts[2])}))["data"]
            text = f"🗂 {c['name']}\nوضعیت نمایش: {'✅ فعال' if c['is_active'] else '⛔️ مخفی/متوقف'}\nعکس: {'✅ دارد' if c.get('has_image') else '❌ ندارد'}\nمحصولات فعال: {c['product_count']}"
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("✏️ تغییر نام", callback_data=f"cat_name:{site['id']}:{c['id']}"), InlineKeyboardButton("🔄 نمایش/توقف", callback_data=f"cat_toggle:{site['id']}:{c['id']}")],
                [InlineKeyboardButton("🖼 گذاشتن/تعویض عکس", callback_data=f"cat_photo:{site['id']}:{c['id']}"), InlineKeyboardButton("🗑 حذف عکس", callback_data=f"cat_photo_remove:{site['id']}:{c['id']}")],
                [InlineKeyboardButton("⬅️ دسته‌ها", callback_data=f"categories:{site['id']}")],
            ])
            return await q.edit_message_text(text, reply_markup=kb)

    if data.startswith("cat_photo:"):
        _, sid, cid = data.split(":")
        site = site_from(uid, sid)
        if not site:
            return await q.answer("عدم دسترسی", show_alert=True)
        await q.answer()
        context.user_data.clear()
        context.user_data.update(flow="cat_photo", site_id=int(sid), category_id=int(cid))
        return await q.edit_message_text("عکس دسته را ارسال کنید:")

    if data.startswith("cat_photo_remove:"):
        _, sid, cid = data.split(":")
        site = site_from(uid, sid)
        if not site:
            return await q.answer("عدم دسترسی", show_alert=True)
        await q.answer()
        await core.api(site, "category_image_remove", {"id": int(cid)})
        return await q.edit_message_text("✅ عکس دسته حذف شد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ دسته", callback_data=f"category:{sid}:{cid}")]]))

    if data.startswith("receipt:") and len(data.split(":")) == 3:
        _, sid, rid = data.split(":")
        site = site_from(uid, sid)
        if not site:
            return await q.answer("عدم دسترسی", show_alert=True)
        await q.answer()
        detail = (await core.api(site, "receipt_detail", {"id": int(rid)}))["data"]
        image = (await core.api(site, "receipt_image", {"id": int(rid)}, timeout=45))["data"]
        raw = base64.b64decode(image["image_b64"])
        photo = io.BytesIO(raw);photo.name=image.get("filename") or "receipt.jpg"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ تأیید", callback_data=f"receipt_set:{sid}:{rid}:approved"), InlineKeyboardButton("❌ رد", callback_data=f"receipt_set:{sid}:{rid}:rejected")],[InlineKeyboardButton("⬅️ رسیدها", callback_data=f"receipts:{sid}")]])
        await context.bot.send_photo(chat_id=q.message.chat_id, photo=photo, caption=f"🧾 رسید سفارش {detail['order_code']}\nمشتری: {detail.get('full_name','-')}\nمبلغ: {money(detail['total'])} تومان\nوضعیت: {detail['status']}", reply_markup=kb)
        return

    return await ORIGINAL_CALLBACK(update, context)


async def message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    flow = context.user_data.get("flow")
    if flow == "prod_old_price":
        site_id = context.user_data.get("site_id")
        if not site_id or not core.can_access(uid, int(site_id)):
            context.user_data.clear()
            return await update.message.reply_text("⛔️ دسترسی شما به این سایت لغو شده است.")
        text = (update.message.text or "").strip().replace(",", "")
        if not text.isdigit():
            return await update.message.reply_text("فقط عدد بفرستید؛ مثال 2,900,000")
        value = int(text)
        site = core.get_site(int(site_id))
        pid = context.user_data["product_id"]
        await core.api(site, "product_update", {"id": pid, "compare_at_price": value})
        context.user_data.clear()
        return await update.message.reply_text("✅ قیمت قبلی ذخیره شد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ محصول", callback_data=f"product:{site['id']}:{pid}")]]))
    return await ORIGINAL_MESSAGE(update, context)


async def photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if context.user_data.get("flow") == "cat_photo":
        site_id = context.user_data.get("site_id")
        if not site_id or not core.can_access(uid, int(site_id)):
            context.user_data.clear()
            return await update.message.reply_text("⛔️ دسترسی شما به این سایت لغو شده است.")
        site = core.get_site(int(site_id))
        tg_file = await update.message.photo[-1].get_file()
        raw = await tg_file.download_as_bytearray()
        encoded = base64.b64encode(bytes(raw)).decode("ascii")
        cid = context.user_data["category_id"]
        try:
            await core.api(site, "category_image_set", {"id": cid, "image_b64": encoded, "filename": "category.jpg"}, timeout=45)
        except Exception as exc:
            return await update.message.reply_text(f"❌ آپلود عکس دسته ناموفق بود:\n{exc}")
        context.user_data.clear()
        return await update.message.reply_text("✅ عکس دسته ذخیره شد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ دسته", callback_data=f"category:{site['id']}:{cid}")]]))
    return await ORIGINAL_PHOTO(update, context)


async def post_init(application):
    application.create_task(notification_loop(application), name="sanashop-site-events")


def run():
    core.db()
    app = Application.builder().token(core.TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", core.start))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.PHOTO, photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message))
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    run()
