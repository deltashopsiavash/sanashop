#!/usr/bin/env python3
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from bot_single_instance import acquire_single_instance_lock
import external_bot as core
import external_bot_plus as plus
import external_bot_v10 as v10
import external_bot_v13 as v13
import external_bot_v14 as v14

logger = logging.getLogger(__name__)


def _site(uid, sid):
    try:
        sid = int(sid)
    except (TypeError, ValueError):
        return None
    if not core.can_access(uid, sid):
        return None
    return core.get_site(sid)


def _money(value):
    return plus.money(value) if value is not None else "-"


async def _show_product(q, site, sid, pid):
    p = (await core.api(site, "product_detail", {"id": int(pid)}))["data"]
    discount = p.get("discount_price")
    amazing = p.get("amazing_price")
    label = p.get("promotion_label") or "بدون تخفیف"
    text = (
        f"🛍 {p['name']}\n"
        f"کد: {p['sku']}\n\n"
        f"💵 قیمت اصلی: {_money(p.get('base_price', p.get('price')))} تومان\n"
        f"🏷 قیمت تخفیف: {_money(discount)}{' تومان' if discount else ''}\n"
        f"🔥 قیمت شگفت‌انگیز: {_money(amazing)}{' تومان' if amazing else ''}\n"
        f"✅ قیمت فعلی سایت: {_money(p.get('effective_price'))} تومان\n"
        f"برچسب فعلی: {label}\n\n"
        f"📦 موجودی کل: {p['stock']}\n"
        f"رزرو: {p.get('reserved_stock', 0)} | قابل فروش: {p.get('available_stock', p['stock'])}\n"
        f"وضعیت: {'فعال' if p['is_active'] else 'غیرفعال'}"
    )
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💵 قیمت اصلی", callback_data=f"prod_base_v15:{sid}:{pid}"),
            InlineKeyboardButton("🏷 تخفیف", callback_data=f"prod_discount_v15:{sid}:{pid}"),
        ],
        [
            InlineKeyboardButton("📦 موجودی", callback_data=f"prod_stock:{sid}:{pid}"),
            InlineKeyboardButton("🔥 شگفت‌انگیز", callback_data=f"prod_amazing_v15:{sid}:{pid}"),
        ],
        [
            InlineKeyboardButton("🔄 فعال/غیرفعال", callback_data=f"prod_toggle:{sid}:{pid}"),
            InlineKeyboardButton("🖼 تعویض عکس", callback_data=f"prod_photo:{sid}:{pid}"),
        ],
        [InlineKeyboardButton("⬅️ محصولات", callback_data=f"products:{sid}")],
    ])
    return await q.edit_message_text(text, reply_markup=kb)


def _set_flow(context, flow, sid, pid):
    context.user_data.clear()
    context.user_data.update(flow=flow, site_id=int(sid), product_id=int(pid))


async def callback(update: Update, context):
    q = update.callback_query
    uid = q.from_user.id
    data = q.data or ""

    try:
        if data.startswith("product:") and len(data.split(":")) == 3:
            _, sid, pid = data.split(":")
            site = _site(uid, sid)
            if not site:
                return await q.answer("عدم دسترسی", show_alert=True)
            await q.answer()
            return await _show_product(q, site, sid, pid)

        if data.startswith("prod_discount_v15:") or data.startswith("prod_price:"):
            _, sid, pid = data.split(":")
            site = _site(uid, sid)
            if not site:
                return await q.answer("عدم دسترسی", show_alert=True)
            p = (await core.api(site, "product_detail", {"id": int(pid)}))["data"]
            await q.answer()
            _set_flow(context, "v15_discount_price", sid, pid)
            return await q.edit_message_text(
                f"🏷 قیمت تخفیف را بفرستید.\n\nقیمت اصلی: {_money(p.get('base_price'))} تومان\n"
                "مثال: اگر قیمت اصلی 200,000 است، 150000 بفرستید.\n"
                "برای حذف کامل تخفیف عدد 0 را بفرستید."
            )

        if data.startswith("prod_base_v15:") or data.startswith("prod_old:"):
            _, sid, pid = data.split(":")
            site = _site(uid, sid)
            if not site:
                return await q.answer("عدم دسترسی", show_alert=True)
            p = (await core.api(site, "product_detail", {"id": int(pid)}))["data"]
            await q.answer()
            _set_flow(context, "v15_base_price", sid, pid)
            return await q.edit_message_text(
                f"💵 قیمت اصلی جدید را بفرستید.\nقیمت اصلی فعلی: {_money(p.get('base_price'))} تومان\n\n"
                "اگر قیمت اصلی را پایین‌تر از قیمت‌های ویژه بگذارید، قیمت ویژه نامعتبر خودکار حذف می‌شود."
            )

        if data.startswith("prod_amazing_v15:") or data.startswith("prod_amazing:"):
            _, sid, pid = data.split(":")
            site = _site(uid, sid)
            if not site:
                return await q.answer("عدم دسترسی", show_alert=True)
            p = (await core.api(site, "product_detail", {"id": int(pid)}))["data"]
            await q.answer()
            _set_flow(context, "v15_amazing_price", sid, pid)
            current = p.get("amazing_price")
            return await q.edit_message_text(
                f"🔥 قیمت مخصوص شگفت‌انگیز را بفرستید.\n\nقیمت اصلی: {_money(p.get('base_price'))} تومان\n"
                f"قیمت شگفت‌انگیز فعلی: {_money(current)}{' تومان' if current else ''}\n\n"
                "قیمت باید از قیمت اصلی کمتر باشد.\nبرای حذف شگفت‌انگیز عدد 0 را بفرستید."
            )

        return await v14.callback(update, context)
    except Exception as exc:
        logger.exception("v15 promotion action failed: %s", data)
        site = v13._site_from_data(uid, data)
        try:
            await q.answer("عملیات ناموفق بود؛ اتصال سایت حفظ شده است.", show_alert=False)
        except Exception:
            pass
        return await v13._safe_reply(
            q,
            f"❌ عملیات قیمت انجام نشد:\n{str(exc)[:700]}",
            v13._site_keyboard(site, uid),
        )


async def message(update: Update, context):
    flow = context.user_data.get("flow")
    if flow not in {"v15_discount_price", "v15_base_price", "v15_amazing_price"}:
        return await v14.message(update, context)

    uid = update.effective_user.id
    site_id = context.user_data.get("site_id")
    pid = context.user_data.get("product_id")
    if not site_id or not pid or not core.can_access(uid, int(site_id)):
        context.user_data.clear()
        return await update.message.reply_text("⛔️ دسترسی شما به این سایت لغو شده است.")

    raw = (update.message.text or "").replace(",", "").replace("٬", "").strip()
    if not raw.isdigit():
        return await update.message.reply_text("فقط عدد بفرستید؛ مثال 150000 یا برای حذف 0")
    value = int(raw)
    site = core.get_site(int(site_id))

    try:
        if flow == "v15_base_price":
            if value <= 0:
                return await update.message.reply_text("قیمت اصلی باید بیشتر از صفر باشد.")
            await core.api(site, "product_update", {"id": int(pid), "price": value})
            done = "✅ قیمت اصلی ذخیره شد."
        elif flow == "v15_discount_price":
            await core.api(site, "product_update", {"id": int(pid), "discount_price": value})
            done = "✅ تخفیف حذف شد و قیمت اصلی برگشت." if value == 0 else "✅ قیمت تخفیف ذخیره شد."
        else:
            await core.api(site, "product_update", {"id": int(pid), "amazing_price": value})
            done = "✅ شگفت‌انگیز حذف شد." if value == 0 else "✅ قیمت مخصوص شگفت‌انگیز ذخیره و فعال شد."
    except Exception as exc:
        return await update.message.reply_text(f"❌ ذخیره نشد:\n{exc}")

    context.user_data.clear()
    p = (await core.api(site, "product_detail", {"id": int(pid)}))["data"]
    summary = (
        f"{done}\n\n"
        f"💵 اصلی: {_money(p.get('base_price'))} تومان\n"
        f"🏷 تخفیف: {_money(p.get('discount_price'))}{' تومان' if p.get('discount_price') else ''}\n"
        f"🔥 شگفت‌انگیز: {_money(p.get('amazing_price'))}{' تومان' if p.get('amazing_price') else ''}\n"
        f"✅ قیمت فعلی سایت: {_money(p.get('effective_price'))} تومان"
    )
    return await update.message.reply_text(
        summary,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ محصول", callback_data=f"product:{site_id}:{pid}")]]),
    )


async def media(update: Update, context):
    return await v14.media(update, context)


def run():
    try:
        acquire_single_instance_lock()
    except RuntimeError as exc:
        logger.error("SanaShop bot refused duplicate startup: %s", exc)
        raise SystemExit(73) from exc

    core.db()
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
