#!/usr/bin/env python3
import asyncio
import logging
import os
from pathlib import Path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django
django.setup()

from asgiref.sync import sync_to_async
from django.core.files.base import ContentFile
from django.utils import timezone
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from shop.models import Category, Order, PaymentReceipt, Product, SiteSetting

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
ADMIN_IDS = {int(x) for x in os.environ.get("TELEGRAM_ADMIN_IDS", "").split(",") if x.strip().isdigit()}


def allowed(update):
    return bool(update.effective_user and update.effective_user.id in ADMIN_IDS)


def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛍 محصولات", callback_data="products"), InlineKeyboardButton("🗂 دسته‌ها", callback_data="categories")],
        [InlineKeyboardButton("🛒 سفارش‌ها", callback_data="orders"), InlineKeyboardButton("🧾 رسیدها", callback_data="receipts")],
        [InlineKeyboardButton("⚙️ تنظیمات فروشگاه", callback_data="settings")],
    ])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        await update.effective_message.reply_text("دسترسی غیرمجاز است.")
        return
    context.user_data.clear()
    store = await sync_to_async(SiteSetting.load)()
    await update.effective_message.reply_text(f"💎 پنل مدیریت <b>{store.site_name}</b>\nاز منوی زیر انتخاب کنید:", parse_mode="HTML", reply_markup=main_keyboard())


async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return
    q = update.callback_query
    await q.answer()
    data = q.data
    if data == "home":
        context.user_data.clear()
        await q.edit_message_text("💎 پنل مدیریت", reply_markup=main_keyboard())
    elif data == "products":
        products = await sync_to_async(list)(Product.objects.select_related("category")[:30])
        keys = [[InlineKeyboardButton(f"{'✅' if p.is_active else '⛔️'} {p.name} — {p.price:,}", callback_data=f"product:{p.id}")] for p in products]
        keys += [[InlineKeyboardButton("➕ محصول جدید", callback_data="product_add")], [InlineKeyboardButton("⬅️ بازگشت", callback_data="home")]]
        await q.edit_message_text("🛍 محصولات:", reply_markup=InlineKeyboardMarkup(keys))
    elif data.startswith("product:"):
        product = await Product.objects.aget(pk=int(data.split(":")[1]))
        text = f"<b>{product.name}</b>\nقیمت: {product.price:,} تومان\nموجودی: {product.stock}\nوضعیت: {'فعال' if product.is_active else 'غیرفعال'}"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💰 قیمت", callback_data=f"edit_price:{product.id}"), InlineKeyboardButton("📦 موجودی", callback_data=f"edit_stock:{product.id}")],
            [InlineKeyboardButton("🖼 عکس", callback_data=f"edit_photo:{product.id}"), InlineKeyboardButton("🔄 فعال/غیرفعال", callback_data=f"toggle_product:{product.id}")],
            [InlineKeyboardButton("🗑 حذف", callback_data=f"delete_product:{product.id}"), InlineKeyboardButton("⬅️ بازگشت", callback_data="products")],
        ])
        await q.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
    elif data == "product_add":
        cats = await sync_to_async(list)(Category.objects.filter(is_active=True)[:30])
        if not cats:
            await q.edit_message_text("ابتدا یک دسته بسازید.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("➕ ساخت دسته", callback_data="category_add")]]))
            return
        await q.edit_message_text("دسته محصول را انتخاب کنید:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(c.name, callback_data=f"new_product_cat:{c.id}")] for c in cats]))
    elif data.startswith("new_product_cat:"):
        context.user_data.update(flow="new_product", step="name", category_id=int(data.split(":")[1]))
        await q.edit_message_text("نام محصول را بفرستید:")
    elif data.startswith(("edit_price:", "edit_stock:", "edit_photo:")):
        action, pk = data.split(":")
        context.user_data.update(flow=action, product_id=int(pk))
        prompt = {"edit_price": "قیمت جدید به تومان:", "edit_stock": "موجودی جدید:", "edit_photo": "عکس جدید محصول را بفرستید:"}[action]
        await q.edit_message_text(prompt)
    elif data.startswith("toggle_product:"):
        product = await Product.objects.aget(pk=int(data.split(":")[1]))
        product.is_active = not product.is_active
        await product.asave(update_fields=["is_active", "updated_at"])
        await q.edit_message_text("وضعیت محصول تغییر کرد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ محصولات", callback_data="products")]]))
    elif data.startswith("delete_product:"):
        await Product.objects.filter(pk=int(data.split(":")[1])).aupdate(is_active=False)
        await q.edit_message_text("محصول غیرفعال شد تا سوابق سفارش‌ها حفظ شود.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ محصولات", callback_data="products")]]))
    elif data == "categories":
        cats = await sync_to_async(list)(Category.objects.all()[:40])
        keys = [[InlineKeyboardButton(f"{'✅' if c.is_active else '⛔️'} {c.name}", callback_data=f"toggle_category:{c.id}")] for c in cats]
        keys += [[InlineKeyboardButton("➕ دسته جدید", callback_data="category_add")], [InlineKeyboardButton("⬅️ بازگشت", callback_data="home")]]
        await q.edit_message_text("🗂 دسته‌ها (برای فعال/غیرفعال ضربه بزنید):", reply_markup=InlineKeyboardMarkup(keys))
    elif data == "category_add":
        context.user_data.update(flow="new_category")
        await q.edit_message_text("نام دسته جدید را بفرستید:")
    elif data.startswith("toggle_category:"):
        cat = await Category.objects.aget(pk=int(data.split(":")[1]))
        cat.is_active = not cat.is_active
        await cat.asave(update_fields=["is_active"])
        await q.edit_message_text("وضعیت دسته تغییر کرد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ دسته‌ها", callback_data="categories")]]))
    elif data in ("orders", "receipts"):
        orders = await sync_to_async(list)(Order.objects.filter(status="review" if data == "receipts" else "pending")[:25])
        keys = [[InlineKeyboardButton(f"{o.code} | {o.full_name} | {o.total:,}", callback_data=f"order:{o.id}")] for o in orders]
        keys.append([InlineKeyboardButton("⬅️ بازگشت", callback_data="home")])
        await q.edit_message_text("سفارش‌ها:" if orders else "موردی پیدا نشد.", reply_markup=InlineKeyboardMarkup(keys))
    elif data.startswith("order:"):
        order = await Order.objects.aget(pk=int(data.split(":")[1]))
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ تایید پرداخت", callback_data=f"approve:{order.id}"), InlineKeyboardButton("❌ رد", callback_data=f"reject:{order.id}")], [InlineKeyboardButton("📦 آماده‌سازی", callback_data=f"processing:{order.id}"), InlineKeyboardButton("🚚 ارسال شد", callback_data=f"shipped:{order.id}")], [InlineKeyboardButton("⬅️ بازگشت", callback_data="home")]])
        await q.edit_message_text(f"<b>سفارش {order.code}</b>\n{order.full_name} | {order.mobile}\n{order.province}، {order.city}\n{order.address}\nمبلغ: {order.total:,} تومان\nوضعیت: {order.get_status_display()}", parse_mode="HTML", reply_markup=kb)
    elif data.startswith(("approve:", "reject:", "processing:", "shipped:")):
        action, pk = data.split(":")
        status = {"approve": "paid", "reject": "cancelled", "processing": "processing", "shipped": "shipped"}[action]
        await Order.objects.filter(pk=int(pk)).aupdate(status=status, updated_at=timezone.now())
        if action in ("approve", "reject"):
            await PaymentReceipt.objects.filter(order_id=int(pk)).aupdate(status="approved" if action == "approve" else "rejected", reviewed_at=timezone.now())
        await q.edit_message_text("وضعیت سفارش به‌روز شد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ منو", callback_data="home")]]))
    elif data == "settings":
        store = await sync_to_async(SiteSetting.load)()
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("✏️ نام سایت", callback_data="setting_name"), InlineKeyboardButton("💳 روش پرداخت", callback_data="setting_payment")], [InlineKeyboardButton("🏦 شماره کارت", callback_data="setting_card"), InlineKeyboardButton("📢 نوار اعلان", callback_data="setting_announcement")], [InlineKeyboardButton("⬅️ بازگشت", callback_data="home")]])
        await q.edit_message_text(f"⚙️ تنظیمات\nنام: <b>{store.site_name}</b>\nپرداخت: {store.get_payment_mode_display()}", parse_mode="HTML", reply_markup=kb)
    elif data in ("setting_name", "setting_card", "setting_announcement"):
        context.user_data.update(flow=data)
        prompts = {"setting_name": "نام جدید سایت را بفرستید:", "setting_card": "شماره کارت و نام صاحب حساب را با | جدا کنید:\nمثال: 6037... | سیاوش قادری", "setting_announcement": "متن جدید نوار اعلان را بفرستید:"}
        await q.edit_message_text(prompts[data])
    elif data == "setting_payment":
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("زرین‌پال", callback_data="payment:zarinpal"), InlineKeyboardButton("کارت", callback_data="payment:card")], [InlineKeyboardButton("هر دو", callback_data="payment:both")]])
        await q.edit_message_text("روش پرداخت فعال را انتخاب کنید:", reply_markup=kb)
    elif data.startswith("payment:"):
        store = await sync_to_async(SiteSetting.load)()
        store.payment_mode = data.split(":")[1]
        await store.asave(update_fields=["payment_mode", "updated_at"])
        await q.edit_message_text("روش پرداخت تغییر کرد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ تنظیمات", callback_data="settings")]]))


async def message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return
    flow = context.user_data.get("flow")
    text = (update.message.text or "").strip()
    if flow == "new_category" and text:
        await Category.objects.acreate(name=text)
        context.user_data.clear()
        await update.message.reply_text("✅ دسته ساخته شد.", reply_markup=main_keyboard())
    elif flow == "new_product":
        step = context.user_data.get("step")
        if step == "name" and text:
            context.user_data.update(step="price", name=text)
            await update.message.reply_text("قیمت به تومان (فقط عدد):")
        elif step == "price" and text.replace(",", "").isdigit():
            context.user_data.update(step="stock", price=int(text.replace(",", "")))
            await update.message.reply_text("موجودی اولیه:")
        elif step == "stock" and text.isdigit():
            context.user_data.update(step="description", stock=int(text))
            await update.message.reply_text("توضیح محصول را بفرستید (یا -):")
        elif step == "description":
            product = await Product.objects.acreate(category_id=context.user_data["category_id"], name=context.user_data["name"], price=context.user_data["price"], stock=context.user_data["stock"], description="" if text == "-" else text)
            context.user_data.update(step="photo", product_id=product.id)
            await update.message.reply_text("عکس محصول را بفرستید (یا /skip):")
    elif flow in ("edit_price", "edit_stock") and text.replace(",", "").isdigit():
        value = int(text.replace(",", ""))
        field = "price" if flow == "edit_price" else "stock"
        await Product.objects.filter(pk=context.user_data["product_id"]).aupdate(**{field: value, "updated_at": timezone.now()})
        context.user_data.clear()
        await update.message.reply_text("✅ ذخیره شد.", reply_markup=main_keyboard())
    elif flow in ("setting_name", "setting_announcement") and text:
        store = await sync_to_async(SiteSetting.load)()
        field = "site_name" if flow == "setting_name" else "announcement"
        setattr(store, field, text)
        await store.asave(update_fields=[field, "updated_at"])
        context.user_data.clear()
        await update.message.reply_text("✅ همان لحظه روی سایت اعمال شد.", reply_markup=main_keyboard())
    elif flow == "setting_card" and "|" in text:
        card, owner = [x.strip() for x in text.split("|", 1)]
        store = await sync_to_async(SiteSetting.load)()
        store.card_number, store.card_owner = card, owner
        await store.asave(update_fields=["card_number", "card_owner", "updated_at"])
        context.user_data.clear()
        await update.message.reply_text("✅ اطلاعات کارت ذخیره شد.", reply_markup=main_keyboard())
    else:
        await update.message.reply_text("ورودی نامعتبر است. از /start شروع کنید.")


async def photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update) or context.user_data.get("flow") not in ("new_product", "edit_photo"):
        return
    file = await update.message.photo[-1].get_file()
    data = await file.download_as_bytearray()
    product = await Product.objects.aget(pk=context.user_data["product_id"])
    await sync_to_async(product.image.save)(f"telegram-{product.id}.jpg", ContentFile(bytes(data)), save=True)
    context.user_data.clear()
    await update.message.reply_text("✅ عکس ذخیره شد و روی سایت قرار گرفت.", reply_markup=main_keyboard())


async def skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if allowed(update) and context.user_data.get("flow") == "new_product" and context.user_data.get("step") == "photo":
        context.user_data.clear()
        await update.message.reply_text("✅ محصول ساخته شد.", reply_markup=main_keyboard())


def run():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is required")
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("skip", skip))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.PHOTO, photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message))
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    run()

