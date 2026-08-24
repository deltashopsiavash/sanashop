#!/usr/bin/env python3
import asyncio
import html
import logging
import os
import tempfile
from pathlib import Path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django
django.setup()

from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import PasswordResetForm
from django.core.files.base import ContentFile
from django.db.models import Count, Q, Sum
from django.utils import timezone
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from backup_worker import MAX_TELEGRAM_BYTES, send_backup
from shop.backup import restore_backup_archive, validate_backup_archive
from shop.models import Category, ContentPage, DiscountCode, HeroSlide, Order, PaymentReceipt, Product, SiteSetting, SocialLink
from shop.services import set_order_status

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
ADMIN_IDS = {int(x) for x in os.environ.get("TELEGRAM_ADMIN_IDS", "").split(",") if x.strip().isdigit()}
User = get_user_model()


def allowed(update):
    return bool(update.effective_user and update.effective_user.id in ADMIN_IDS)


def back_button(target="home", label="⬅️ بازگشت"):
    return [InlineKeyboardButton(label, callback_data=target)]


def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛍 محصولات", callback_data="products"), InlineKeyboardButton("🗂 دسته‌ها", callback_data="categories")],
        [InlineKeyboardButton("👥 کاربران", callback_data="users"), InlineKeyboardButton("🛒 سفارش‌ها", callback_data="orders")],
        [InlineKeyboardButton("🧾 رسیدها", callback_data="receipts"), InlineKeyboardButton("⚙️ تنظیمات فروشگاه", callback_data="settings")],
        [InlineKeyboardButton("📄 صفحات سایت", callback_data="pages"), InlineKeyboardButton("🎞 بنرها", callback_data="banners")],
        [InlineKeyboardButton("🔗 شبکه‌های اجتماعی", callback_data="socials"), InlineKeyboardButton("🎟 کد تخفیف", callback_data="discounts")],
        [InlineKeyboardButton("🔐 بکاپ", callback_data="backups")],
    ])




def _h(value):
    return html.escape(str(value or ""))


def _send_password_reset(user):
    if not user.is_active:
        raise ValueError("حساب غیرفعال است؛ ابتدا آن را فعال کنید.")
    if not user.email:
        raise ValueError("برای این کاربر ایمیل ثبت نشده است.")
    form = PasswordResetForm({"email": user.email})
    if not form.is_valid():
        raise ValueError("ایمیل کاربر معتبر نیست.")
    domain = (os.environ.get("DOMAIN") or "").strip() or None
    kwargs = {
        "use_https": True,
        "email_template_name": "registration/password_reset_email.txt",
    }
    if domain:
        kwargs["domain_override"] = domain
    form.save(**kwargs)


async def show_user(q, user):
    stats = await sync_to_async(lambda: Order.objects.filter(customer=user).aggregate(count=Count("id"), spent=Sum("total")))()
    name = (user.get_full_name() or user.first_name or "").strip() or "بدون نام"
    joined = timezone.localtime(user.date_joined).strftime("%Y/%m/%d %H:%M") if user.date_joined else "-"
    last_login = timezone.localtime(user.last_login).strftime("%Y/%m/%d %H:%M") if user.last_login else "هرگز"
    text = (
        f"👤 <b>{_h(name)}</b>\n"
        f"ایمیل: <code>{_h(user.email or user.username)}</code>\n"
        f"وضعیت: {'✅ فعال' if user.is_active else '⛔️ غیرفعال'}\n"
        f"عضویت: {joined}\nآخرین ورود: {last_login}\n"
        f"سفارش‌ها: {stats.get('count') or 0}\n"
        f"مجموع خرید: {(stats.get('spent') or 0):,} تومان"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 سفارش‌های کاربر", callback_data=f"user_orders:{user.id}")],
        [InlineKeyboardButton("✏️ نام", callback_data=f"user_name:{user.id}"), InlineKeyboardButton("📧 ایمیل", callback_data=f"user_email:{user.id}")],
        [InlineKeyboardButton("🔐 ارسال بازیابی رمز", callback_data=f"user_reset:{user.id}")],
        [InlineKeyboardButton("⛔️ غیرفعال" if user.is_active else "✅ فعال", callback_data=f"user_toggle:{user.id}"), InlineKeyboardButton("🗑 حذف حساب", callback_data=f"user_delete:{user.id}")],
        [InlineKeyboardButton("⬅️ کاربران", callback_data="users")],
    ])
    await q.edit_message_text(text, parse_mode="HTML", reply_markup=kb)

async def show_product(q, product):
    assurances = [x for x in (product.assurance_1, product.assurance_2, product.assurance_3) if x]
    assurance_text = "\n".join(f"✓ {item}" for item in assurances) or "-"
    text = (f"<b>{product.name}</b>\nکد محصول: <code>{product.sku}</code>\n"
            f"قیمت: {product.price:,} تومان\nموجودی: {product.stock}\nوضعیت: {'فعال' if product.is_active else 'غیرفعال'}\n\n"
            f"<b>مزایای محصول:</b>\n{assurance_text}")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 قیمت فروش", callback_data=f"edit_price:{product.id}"), InlineKeyboardButton("🏷 قیمت قبل", callback_data=f"edit_compare_price:{product.id}")],
        [InlineKeyboardButton("📦 موجودی", callback_data=f"edit_stock:{product.id}"), InlineKeyboardButton("✅ مزایای محصول", callback_data=f"edit_assurances:{product.id}")],
        [InlineKeyboardButton("🖼 عکس", callback_data=f"edit_photo:{product.id}"), InlineKeyboardButton("🔄 فعال/غیرفعال", callback_data=f"toggle_product:{product.id}")],
        [InlineKeyboardButton(("🔥 حذف از شگفت‌انگیز" if product.is_amazing else "🔥 شگفت‌انگیز"), callback_data=f"toggle_amazing:{product.id}")],
        [InlineKeyboardButton("🗑 حذف", callback_data=f"delete_product:{product.id}"), InlineKeyboardButton("⬅️ محصولات", callback_data="products")],
    ])
    await q.edit_message_text(text, parse_mode="HTML", reply_markup=kb)


async def show_order(q, order, back_target="orders", back_label="⬅️ سفارش‌ها"):
    receipt = await sync_to_async(lambda: getattr(order, "receipt", None))()
    receipt_line = f"\nرسید: {receipt.get_status_display()}" if receipt else ""
    tracking_line = f"\nکد رهگیری: <code>{order.tracking_code}</code>" if order.tracking_code else ""
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ تایید پرداخت", callback_data=f"approve:{order.id}"), InlineKeyboardButton("❌ رد", callback_data=f"reject:{order.id}")],
        [InlineKeyboardButton("📦 آماده‌سازی", callback_data=f"processing:{order.id}"), InlineKeyboardButton("🚚 ثبت کد رهگیری", callback_data=f"tracking:{order.id}")],
        [InlineKeyboardButton(back_label, callback_data=back_target)],
    ])
    await q.edit_message_text(
        f"<b>سفارش {order.code}</b>\n{order.full_name} | {order.mobile}\n{order.province}، {order.city}\n"
        f"{order.address}\nمبلغ: {order.total:,} تومان\nوضعیت: {order.get_status_display()}{receipt_line}{tracking_line}",
        parse_mode="HTML", reply_markup=kb,
    )


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
        keys = [[InlineKeyboardButton(f"{'✅' if p.is_active else '⛔️'} {p.name} | {p.sku}", callback_data=f"product:{p.id}")] for p in products]
        keys += [[InlineKeyboardButton("🔎 جست‌وجو با کد محصول", callback_data="product_search")], [InlineKeyboardButton("➕ محصول جدید", callback_data="product_add")], back_button()]
        await q.edit_message_text("🛍 محصولات:", reply_markup=InlineKeyboardMarkup(keys))
    elif data == "product_search":
        context.user_data.clear(); context.user_data["flow"] = "search_product"
        await q.edit_message_text("کد محصول را بفرستید؛ مثال: SNA-12AB34CD")
    elif data.startswith("product:"):
        await show_product(q, await Product.objects.aget(pk=int(data.split(":")[1])))
    elif data == "product_add":
        cats = await sync_to_async(list)(Category.objects.filter(is_active=True)[:30])
        if not cats:
            await q.edit_message_text("ابتدا یک دسته بسازید.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("➕ ساخت دسته", callback_data="category_add")]])); return
        await q.edit_message_text("دسته محصول را انتخاب کنید:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(c.name, callback_data=f"new_product_cat:{c.id}")] for c in cats]))
    elif data.startswith("new_product_cat:"):
        context.user_data.update(flow="new_product", step="name", category_id=int(data.split(":")[1]))
        await q.edit_message_text("نام محصول را بفرستید:")
    elif data.startswith(("edit_price:", "edit_compare_price:", "edit_stock:", "edit_photo:")):
        action, pk = data.split(":"); context.user_data.update(flow=action, product_id=int(pk))
        await q.edit_message_text({"edit_price": "قیمت فروش جدید به تومان:", "edit_compare_price": "قیمت قبل از تخفیف را به تومان بفرستید؛ برای حذف 0:", "edit_stock": "موجودی جدید:", "edit_photo": "عکس جدید محصول را بفرستید:"}[action])
    elif data.startswith("edit_assurances:"):
        context.user_data.clear(); context.user_data.update(flow="edit_assurances", step="assurance_1", product_id=int(data.split(":")[1]))
        await q.edit_message_text("مزیت یا تضمین اول محصول را بفرستید؛ برای خالی گذاشتن - بفرستید:")
    elif data.startswith("toggle_product:"):
        product = await Product.objects.aget(pk=int(data.split(":")[1])); product.is_active = not product.is_active
        await product.asave(update_fields=["is_active", "updated_at"])
        await q.edit_message_text("وضعیت محصول تغییر کرد.", reply_markup=InlineKeyboardMarkup([back_button("products", "⬅️ محصولات")]))
    elif data.startswith("delete_product:"):
        await Product.objects.filter(pk=int(data.split(":")[1])).aupdate(is_active=False)
        await q.edit_message_text("محصول غیرفعال شد تا سوابق سفارش‌ها حفظ شود.", reply_markup=InlineKeyboardMarkup([back_button("products", "⬅️ محصولات")]))
    elif data.startswith("toggle_amazing:"):
        product = await Product.objects.aget(pk=int(data.split(":")[1])); product.is_amazing = not product.is_amazing
        await product.asave(update_fields=["is_amazing", "updated_at"])
        await q.edit_message_text("✅ وضعیت پیشنهاد شگفت‌انگیز تغییر کرد.", reply_markup=InlineKeyboardMarkup([back_button(f"product:{product.id}", "⬅️ محصول")]))

    elif data == "categories":
        cats = await sync_to_async(list)(Category.objects.all()[:40])
        keys = [[InlineKeyboardButton(f"{'✅' if c.is_active else '⛔️'} {c.name}", callback_data=f"category:{c.id}")] for c in cats]
        keys += [[InlineKeyboardButton("➕ دسته جدید", callback_data="category_add")], back_button()]
        await q.edit_message_text("🗂 دسته‌ها:", reply_markup=InlineKeyboardMarkup(keys))
    elif data == "category_add":
        cats = await sync_to_async(list)(Category.objects.filter(is_active=True, parent__isnull=True)[:25])
        keys = [[InlineKeyboardButton("دسته اصلی (بدون والد)", callback_data="new_category_parent:0")]]
        keys += [[InlineKeyboardButton(f"زیردستهٔ {cat.name}", callback_data=f"new_category_parent:{cat.id}")] for cat in cats]
        await q.edit_message_text("این دسته اصلی است یا زیردسته؟", reply_markup=InlineKeyboardMarkup(keys))
    elif data.startswith("new_category_parent:"):
        parent_id = int(data.split(":")[1])
        context.user_data.clear(); context.user_data.update(flow="new_category", parent_id=parent_id or None)
        await q.edit_message_text("نام دسته جدید را بفرستید:")
    elif data.startswith("category:"):
        cat = await Category.objects.aget(pk=int(data.split(":")[1])); count = await cat.products.filter(is_active=True).acount()
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ تغییر نام", callback_data=f"rename_category:{cat.id}"), InlineKeyboardButton("🖼 عکس دسته", callback_data=f"category_photo:{cat.id}")],
            [InlineKeyboardButton("⏸ توقف/فعال", callback_data=f"toggle_category:{cat.id}"), InlineKeyboardButton("🗑 حذف", callback_data=f"delete_category:{cat.id}")],
            [InlineKeyboardButton("⬅️ دسته‌ها", callback_data="categories")],
        ])
        await q.edit_message_text(f"<b>{cat.name}</b>\nوضعیت: {'فعال' if cat.is_active else 'متوقف'}\nتعداد محصولات: {count}", parse_mode="HTML", reply_markup=kb)
    elif data.startswith("rename_category:"):
        context.user_data.update(flow="rename_category", category_id=int(data.split(":")[1])); await q.edit_message_text("نام جدید دسته را بفرستید:")
    elif data.startswith("category_photo:"):
        context.user_data.clear(); context.user_data.update(flow="category_photo", category_id=int(data.split(":")[1]))
        await q.edit_message_text("عکس اصلی دسته را بفرستید؛ این عکس در صفحه اصلی و دسته‌بندی نمایش داده می‌شود:")
    elif data.startswith("toggle_category:"):
        cat = await Category.objects.aget(pk=int(data.split(":")[1])); cat.is_active = not cat.is_active
        await cat.asave(update_fields=["is_active"])
        await q.edit_message_text("وضعیت دسته تغییر کرد.", reply_markup=InlineKeyboardMarkup([back_button("categories", "⬅️ دسته‌ها")]))
    elif data.startswith("delete_category:"):
        cat = await Category.objects.aget(pk=int(data.split(":")[1]))
        if await cat.products.aexists() or await cat.children.aexists():
            cat.is_active = False; await cat.asave(update_fields=["is_active"]); text = "این دسته سابقه محصول/زیردسته دارد؛ برای حفظ اطلاعات متوقف و از سایت پنهان شد."
        else:
            await cat.adelete(); text = "دسته کاملاً حذف شد."
        await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup([back_button("categories", "⬅️ دسته‌ها")]))

    elif data == "users":
        users = await sync_to_async(list)(User.objects.filter(is_staff=False).order_by("-date_joined")[:30])
        keys = []
        for user in users:
            label = (user.get_full_name() or user.first_name or user.email or user.username or f"کاربر {user.id}").strip()
            keys.append([InlineKeyboardButton(f"{'✅' if user.is_active else '⛔️'} {label[:34]}", callback_data=f"user:{user.id}")])
        keys += [[InlineKeyboardButton("🔎 جست‌وجوی کاربر", callback_data="user_search")], back_button()]
        await q.edit_message_text("👥 کاربران فروشگاه:", reply_markup=InlineKeyboardMarkup(keys))
    elif data == "user_search":
        context.user_data.clear(); context.user_data["flow"] = "search_user"
        await q.edit_message_text("نام یا ایمیل کاربر را بفرستید:")
    elif data.startswith("user:"):
        user = await User.objects.aget(pk=int(data.split(":")[1]), is_staff=False)
        await show_user(q, user)
    elif data.startswith("user_orders:"):
        user_id = int(data.split(":")[1])
        user = await User.objects.aget(pk=user_id, is_staff=False)
        orders = await sync_to_async(list)(Order.objects.filter(customer_id=user_id).order_by("-created_at")[:25])
        keys = [[InlineKeyboardButton(f"{o.code} | {o.get_status_display()} | {o.total:,}", callback_data=f"userorder:{o.id}:{user_id}")] for o in orders]
        keys.append([InlineKeyboardButton("⬅️ کاربر", callback_data=f"user:{user_id}")])
        await q.edit_message_text(f"🛒 سفارش‌های {_h(user.get_full_name() or user.email)}" if orders else "این کاربر هنوز سفارشی ندارد.", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keys))
    elif data.startswith("userorder:"):
        _, order_id, user_id = data.split(":")
        order = await Order.objects.aget(pk=int(order_id), customer_id=int(user_id))
        await show_order(q, order, back_target=f"user_orders:{user_id}", back_label="⬅️ سفارش‌های کاربر")
    elif data.startswith(("user_name:", "user_email:")):
        action, pk = data.split(":")
        context.user_data.clear(); context.user_data.update(flow=action, user_id=int(pk))
        await q.edit_message_text("نام و نام خانوادگی جدید را بفرستید:" if action == "user_name" else "ایمیل جدید کاربر را بفرستید:")
    elif data.startswith("user_toggle:"):
        user = await User.objects.aget(pk=int(data.split(":")[1]), is_staff=False)
        user.is_active = not user.is_active
        await user.asave(update_fields=["is_active"])
        await show_user(q, user)
    elif data.startswith("user_reset:"):
        user = await User.objects.aget(pk=int(data.split(":")[1]), is_staff=False)
        try:
            await sync_to_async(_send_password_reset)(user)
            text = "✅ لینک بازیابی رمز به ایمیل کاربر ارسال شد."
        except Exception as exc:
            text = f"❌ ارسال بازیابی انجام نشد: {_h(exc)}"
        await q.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup([back_button(f"user:{user.id}", "⬅️ کاربر")]))
    elif data.startswith("user_delete:"):
        user = await User.objects.aget(pk=int(data.split(":")[1]), is_staff=False)
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("⚠️ بله، حذف شود", callback_data=f"user_delete_confirm:{user.id}")], [InlineKeyboardButton("لغو", callback_data=f"user:{user.id}")]])
        await q.edit_message_text(f"حساب <b>{_h(user.get_full_name() or user.email)}</b> حذف شود؟\nسفارش‌ها برای سوابق فروشگاه باقی می‌مانند اما دیگر به حساب کاربری متصل نخواهند بود.", parse_mode="HTML", reply_markup=kb)
    elif data.startswith("user_delete_confirm:"):
        user = await User.objects.aget(pk=int(data.split(":")[1]), is_staff=False)
        label = user.email or user.username
        await user.adelete()
        await q.edit_message_text(f"✅ حساب {_h(label)} حذف شد.", parse_mode="HTML", reply_markup=InlineKeyboardMarkup([back_button("users", "⬅️ کاربران")]))

    elif data in ("orders", "receipts"):
        if data == "receipts":
            orders = await sync_to_async(list)(Order.objects.filter(receipt__isnull=False).select_related("receipt")[:25])
            keys = [[InlineKeyboardButton(f"{o.code} | {o.receipt.get_status_display()}", callback_data=f"order:{o.id}")] for o in orders]
            keys.append([InlineKeyboardButton("🔎 جست‌وجوی کد سفارش", callback_data="receipt_search")])
        else:
            orders = await sync_to_async(list)(Order.objects.exclude(status="cancelled")[:25])
            keys = [[InlineKeyboardButton(f"{o.code} | {o.get_status_display()} | {o.total:,}", callback_data=f"order:{o.id}")] for o in orders]
        keys.append(back_button()); await q.edit_message_text("سفارش‌ها:" if orders else "موردی پیدا نشد.", reply_markup=InlineKeyboardMarkup(keys))
    elif data == "receipt_search":
        context.user_data.clear(); context.user_data["flow"] = "search_receipt"; await q.edit_message_text("کد سفارش را بفرستید:")
    elif data.startswith("order:"):
        await show_order(q, await Order.objects.aget(pk=int(data.split(":")[1])))
    elif data.startswith(("approve:", "reject:", "processing:")):
        action, pk = data.split(":"); order = await Order.objects.aget(pk=int(pk))
        status, note = {"approve": ("paid", "رسید پرداخت توسط مدیر تایید شد"), "reject": ("cancelled", "رسید پرداخت توسط مدیر رد شد"), "processing": ("processing", "سفارش وارد مرحله آماده‌سازی شد")}[action]
        await sync_to_async(set_order_status)(order, status, note)
        if action in ("approve", "reject"):
            await PaymentReceipt.objects.filter(order_id=order.id).aupdate(status="approved" if action == "approve" else "rejected", reviewed_at=timezone.now())
        await q.edit_message_text("وضعیت سفارش به‌روز شد و در حساب مشتری نمایش داده می‌شود.", reply_markup=InlineKeyboardMarkup([back_button(f"order:{order.id}", "⬅️ سفارش")]))
    elif data.startswith("tracking:"):
        context.user_data.update(flow="tracking_code", order_id=int(data.split(":")[1])); await q.edit_message_text("کد رهگیری پستی را بفرستید:")

    elif data == "settings":
        store = await sync_to_async(SiteSetting.load)()
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ نام سایت", callback_data="setting_name"), InlineKeyboardButton("🖼 لوگو", callback_data="setting_logo")],
            [InlineKeyboardButton("💳 روش پرداخت", callback_data="setting_payment"), InlineKeyboardButton("🏦 شماره کارت", callback_data="setting_card")],
            [InlineKeyboardButton("🚚 هزینه ارسال", callback_data="setting_shipping"), InlineKeyboardButton("🎁 ارسال رایگان", callback_data="setting_free_shipping")],
            [InlineKeyboardButton("📢 نوار اعلان", callback_data="setting_announcement"), InlineKeyboardButton("✅ اینماد", callback_data="setting_enamad")], back_button(),
        ])
        enamad_status = "✅ تنظیم شده" if store.enamad_html else "➖ ثبت نشده"
        await q.edit_message_text(f"⚙️ تنظیمات\nنام: <b>{store.site_name}</b>\nپرداخت: {store.get_payment_mode_display()}\nارسال: {store.shipping_fee:,} تومان\nاینماد: {enamad_status}", parse_mode="HTML", reply_markup=kb)
    elif data in ("setting_name", "setting_card", "setting_announcement", "setting_shipping", "setting_free_shipping", "setting_logo", "setting_enamad"):
        context.user_data.clear(); context.user_data["flow"] = data
        prompts = {"setting_name": "نام جدید سایت را بفرستید:", "setting_card": "شماره کارت و نام صاحب حساب را با | جدا کنید:\nمثال: 6037... | سیاوش قادری", "setting_announcement": "متن جدید نوار اعلان را بفرستید:", "setting_shipping": "هزینه ارسال جدید به تومان (فقط عدد):", "setting_free_shipping": "حداقل خرید برای ارسال رایگان به تومان:", "setting_logo": "لوگوی جدید را به‌صورت عکس بفرستید:", "setting_enamad": "کد HTML اینماد را دقیقاً همان‌طور که از پنل اینماد دریافت کرده‌اید بفرستید. برای حذف نماد، فقط - بفرستید:"}
        await q.edit_message_text(prompts[data])
    elif data == "setting_payment":
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("زرین‌پال", callback_data="payment:zarinpal"), InlineKeyboardButton("کارت", callback_data="payment:card")], [InlineKeyboardButton("هر دو", callback_data="payment:both")]])
        await q.edit_message_text("روش پرداخت فعال را انتخاب کنید:", reply_markup=kb)
    elif data.startswith("payment:"):
        store = await sync_to_async(SiteSetting.load)(); store.payment_mode = data.split(":")[1]
        await store.asave(update_fields=["payment_mode", "updated_at"])
        await q.edit_message_text("روش پرداخت تغییر کرد.", reply_markup=InlineKeyboardMarkup([back_button("settings", "⬅️ تنظیمات")]))

    elif data == "pages":
        pages = await sync_to_async(list)(ContentPage.objects.all()[:40])
        keys = [[InlineKeyboardButton(f"{'✅' if p.is_active else '⛔️'} {p.title}", callback_data=f"page:{p.id}")] for p in pages]
        keys += [[InlineKeyboardButton("➕ صفحه جدید", callback_data="page_add")], back_button()]
        await q.edit_message_text("📄 صفحات و فوتر سایت:", reply_markup=InlineKeyboardMarkup(keys))
    elif data == "page_add":
        context.user_data.clear(); context.user_data.update(flow="page_add", step="title")
        await q.edit_message_text("عنوان صفحه را بفرستید؛ مثال: شرایط ارسال")
    elif data.startswith("page:"):
        page = await ContentPage.objects.aget(pk=int(data.split(":")[1]))
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("✏️ عنوان", callback_data=f"page_title:{page.id}"), InlineKeyboardButton("📝 متن", callback_data=f"page_body:{page.id}")], [InlineKeyboardButton("🔄 فعال/غیرفعال", callback_data=f"page_toggle:{page.id}"), InlineKeyboardButton("🗑 حذف", callback_data=f"page_delete:{page.id}")], [InlineKeyboardButton("⬅️ صفحات", callback_data="pages")]])
        await q.edit_message_text(f"<b>{page.title}</b>\nشناسه: <code>{page.slug}</code>\nفوتر: {page.get_footer_group_display()}\nوضعیت: {'فعال' if page.is_active else 'غیرفعال'}", parse_mode="HTML", reply_markup=kb)
    elif data.startswith(("page_title:", "page_body:")):
        action, pk = data.split(":"); context.user_data.clear(); context.user_data.update(flow=action, page_id=int(pk))
        await q.edit_message_text("عنوان جدید را بفرستید:" if action == "page_title" else "متن کامل جدید صفحه را بفرستید:")
    elif data.startswith("page_toggle:"):
        page = await ContentPage.objects.aget(pk=int(data.split(":")[1])); page.is_active = not page.is_active
        await page.asave(update_fields=["is_active", "updated_at"]); await q.edit_message_text("✅ وضعیت صفحه تغییر کرد.", reply_markup=InlineKeyboardMarkup([back_button("pages", "⬅️ صفحات")]))
    elif data.startswith("page_delete:"):
        await ContentPage.objects.filter(pk=int(data.split(":")[1])).adelete(); await q.edit_message_text("✅ صفحه حذف شد.", reply_markup=InlineKeyboardMarkup([back_button("pages", "⬅️ صفحات")]))

    elif data == "banners":
        banners = await sync_to_async(list)(HeroSlide.objects.all()[:20])
        keys = [[InlineKeyboardButton(f"{'✅' if b.is_active else '⛔️'} {b.title or 'بنر بدون عنوان'}", callback_data=f"banner:{b.id}")] for b in banners]
        keys += [[InlineKeyboardButton("➕ بنر جدید", callback_data="banner_add")], back_button()]
        await q.edit_message_text("🎞 بنرهای اسلایدر صفحه اصلی:", reply_markup=InlineKeyboardMarkup(keys))
    elif data == "banner_add":
        context.user_data.clear(); context.user_data.update(flow="banner_add", step="title")
        await q.edit_message_text("عنوان بنر را بفرستید (یا - برای بدون عنوان):")
    elif data.startswith("banner:"):
        banner = await HeroSlide.objects.aget(pk=int(data.split(":")[1]))
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔄 فعال/غیرفعال", callback_data=f"banner_toggle:{banner.id}"), InlineKeyboardButton("🗑 حذف", callback_data=f"banner_delete:{banner.id}")], [InlineKeyboardButton("⬅️ بنرها", callback_data="banners")]])
        await q.edit_message_text(f"🎞 {banner.title or 'بنر'}\nمتن: {banner.subtitle or '-'}\nلینک: {banner.link}", reply_markup=kb)
    elif data.startswith("banner_toggle:"):
        banner = await HeroSlide.objects.aget(pk=int(data.split(":")[1])); banner.is_active = not banner.is_active
        await banner.asave(update_fields=["is_active"]); await q.edit_message_text("✅ وضعیت بنر تغییر کرد.", reply_markup=InlineKeyboardMarkup([back_button("banners", "⬅️ بنرها")]))
    elif data.startswith("banner_delete:"):
        await HeroSlide.objects.filter(pk=int(data.split(":")[1])).adelete(); await q.edit_message_text("✅ بنر حذف شد.", reply_markup=InlineKeyboardMarkup([back_button("banners", "⬅️ بنرها")]))

    elif data == "socials":
        items = await sync_to_async(list)(SocialLink.objects.all()[:30])
        keys = [[InlineKeyboardButton(f"{'✅' if item.is_active else '⛔️'} {item.title}", callback_data=f"social:{item.id}")] for item in items]
        keys += [[InlineKeyboardButton("➕ شبکه اجتماعی جدید", callback_data="social_add")], back_button()]
        await q.edit_message_text("🔗 شبکه‌های اجتماعی و پیام‌رسان‌های فوتر:", reply_markup=InlineKeyboardMarkup(keys))
    elif data == "social_add":
        context.user_data.clear(); context.user_data.update(flow="social_add", step="title")
        await q.edit_message_text("نام شبکه اجتماعی را بفرستید؛ مثال: اینستاگرام، تلگرام، ایتا یا روبیکا")
    elif data.startswith("social:"):
        item = await SocialLink.objects.aget(pk=int(data.split(":")[1]))
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ نام", callback_data=f"social_title:{item.id}"), InlineKeyboardButton("🔗 لینک", callback_data=f"social_url:{item.id}")],
            [InlineKeyboardButton("🖼 عکس/آیکن", callback_data=f"social_photo:{item.id}"), InlineKeyboardButton("🔄 فعال/غیرفعال", callback_data=f"social_toggle:{item.id}")],
            [InlineKeyboardButton("🗑 حذف", callback_data=f"social_delete:{item.id}"), InlineKeyboardButton("⬅️ شبکه‌ها", callback_data="socials")],
        ])
        await q.edit_message_text(f"<b>{item.title}</b>\nلینک: {item.url}\nوضعیت: {'فعال' if item.is_active else 'غیرفعال'}", parse_mode="HTML", reply_markup=kb)
    elif data.startswith(("social_title:", "social_url:", "social_photo:")):
        action, pk = data.split(":"); context.user_data.clear(); context.user_data.update(flow=action, social_id=int(pk))
        prompt = {"social_title": "نام جدید را بفرستید:", "social_url": "لینک مستقیم جدید را بفرستید:", "social_photo": "عکس یا آیکن جدید را بفرستید:"}[action]
        await q.edit_message_text(prompt)
    elif data.startswith("social_toggle:"):
        item = await SocialLink.objects.aget(pk=int(data.split(":")[1])); item.is_active = not item.is_active
        await item.asave(update_fields=["is_active", "updated_at"]); await q.edit_message_text("✅ وضعیت شبکه اجتماعی تغییر کرد.", reply_markup=InlineKeyboardMarkup([back_button("socials", "⬅️ شبکه‌ها")]))
    elif data.startswith("social_delete:"):
        await SocialLink.objects.filter(pk=int(data.split(":")[1])).adelete(); await q.edit_message_text("✅ شبکه اجتماعی حذف شد.", reply_markup=InlineKeyboardMarkup([back_button("socials", "⬅️ شبکه‌ها")]))

    elif data == "discounts":
        items = await sync_to_async(list)(DiscountCode.objects.all()[:30])
        keys = [[InlineKeyboardButton(f"{'✅' if d.is_active else '⛔️'} {d.code} | {d.percent}%", callback_data=f"discount:{d.id}")] for d in items]
        keys += [[InlineKeyboardButton("➕ کد تخفیف جدید", callback_data="discount_add")], back_button()]
        await q.edit_message_text("🎟 کدهای تخفیف درصدی:", reply_markup=InlineKeyboardMarkup(keys))
    elif data == "discount_add":
        context.user_data.clear(); context.user_data.update(flow="discount_add", step="code")
        await q.edit_message_text("کد تخفیف را بفرستید؛ مثال SANA20")
    elif data.startswith("discount:"):
        item = await DiscountCode.objects.aget(pk=int(data.split(":")[1]))
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔄 فعال/غیرفعال", callback_data=f"discount_toggle:{item.id}"), InlineKeyboardButton("🗑 حذف", callback_data=f"discount_delete:{item.id}")], [InlineKeyboardButton("⬅️ تخفیف‌ها", callback_data="discounts")]])
        await q.edit_message_text(f"🎟 <b>{item.code}</b>\nتخفیف: {item.percent}%\nحداقل سفارش: {item.min_order_amount:,} تومان\nاستفاده: {item.used_count}/{item.max_uses or '∞'}", parse_mode="HTML", reply_markup=kb)
    elif data.startswith("discount_toggle:"):
        item = await DiscountCode.objects.aget(pk=int(data.split(":")[1])); item.is_active = not item.is_active
        await item.asave(update_fields=["is_active"]); await q.edit_message_text("✅ وضعیت کد تغییر کرد.", reply_markup=InlineKeyboardMarkup([back_button("discounts", "⬅️ تخفیف‌ها")]))
    elif data.startswith("discount_delete:"):
        await DiscountCode.objects.filter(pk=int(data.split(":")[1])).adelete(); await q.edit_message_text("✅ کد تخفیف حذف شد.", reply_markup=InlineKeyboardMarkup([back_button("discounts", "⬅️ تخفیف‌ها")]))

    elif data == "backups":
        store = await sync_to_async(SiteSetting.load)(); interval = f"هر {store.backup_interval_minutes} دقیقه" if store.backup_interval_minutes else "غیرفعال"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⏱ تنظیم زمان‌بندی", callback_data="backup_interval"), InlineKeyboardButton("📤 بکاپ همین حالا", callback_data="backup_now")],
            [InlineKeyboardButton("♻️ بازگردانی بکاپ", callback_data="backup_restore")], back_button(),
        ])
        await q.edit_message_text(f"🔐 بخش بکاپ\nزمان‌بندی فعلی: <b>{interval}</b>\nبکاپ شامل کاربران، سفارش‌ها، محصولات، تنظیمات و تصاویر است.", parse_mode="HTML", reply_markup=kb)
    elif data == "backup_interval":
        context.user_data.clear(); context.user_data["flow"] = "backup_interval"
        await q.edit_message_text("فاصله بکاپ را به دقیقه بفرستید؛ مثال 60. برای غیرفعال‌کردن 0 بفرستید:")
    elif data == "backup_now":
        await q.edit_message_text("⏳ در حال ساخت بکاپ کامل…")
        try:
            await send_backup(context.bot, update.effective_chat.id, "manual"); await q.message.reply_text("✅ بکاپ ساخته شد.", reply_markup=main_keyboard())
        except Exception as exc:
            await q.message.reply_text(f"❌ ساخت بکاپ ناموفق بود: {exc}", reply_markup=main_keyboard())
    elif data == "backup_restore":
        context.user_data.clear(); context.user_data["flow"] = "restore_upload"
        await q.edit_message_text("فایل با پسوند .sanabackup را بفرستید. پس از بررسی، تایید نهایی از شما گرفته می‌شود.")
    elif data == "restore_confirm":
        path = context.user_data.get("restore_path")
        if not path or not Path(path).exists():
            await q.edit_message_text("فایل موقت پیدا نشد؛ دوباره از بخش بکاپ ارسال کنید.", reply_markup=main_keyboard()); return
        await q.edit_message_text("⏳ بازگردانی در حال انجام است؛ سایت موقتاً در حالت نگهداری قرار می‌گیرد…")
        try:
            emergency = await asyncio.to_thread(restore_backup_archive, path); context.user_data.clear()
            await q.message.reply_text(f"✅ همه اطلاعات بازگردانی شد.\nبکاپ اضطراری قبل از بازیابی: {emergency.name}", reply_markup=main_keyboard())
        except Exception as exc:
            await q.message.reply_text(f"❌ بازگردانی انجام نشد و اطلاعات قبلی حفظ شد: {exc}", reply_markup=main_keyboard())
        finally:
            Path(path).unlink(missing_ok=True)
    elif data == "restore_cancel":
        path = context.user_data.get("restore_path")
        if path: Path(path).unlink(missing_ok=True)
        context.user_data.clear(); await q.edit_message_text("بازگردانی لغو شد.", reply_markup=main_keyboard())


async def message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update): return
    flow = context.user_data.get("flow"); text = (update.message.text or "").strip()
    if flow == "new_category" and text:
        await Category.objects.acreate(name=text, parent_id=context.user_data.get("parent_id")); context.user_data.clear(); await update.message.reply_text("✅ دسته ساخته شد.", reply_markup=main_keyboard())
    elif flow == "rename_category" and text:
        cat = await Category.objects.aget(pk=context.user_data["category_id"]); cat.name, cat.slug = text, ""; await cat.asave()
        context.user_data.clear(); await update.message.reply_text("✅ نام دسته تغییر کرد.", reply_markup=main_keyboard())
    elif flow == "search_user" and text:
        users = await sync_to_async(list)(User.objects.filter(is_staff=False).filter(Q(email__icontains=text) | Q(username__icontains=text) | Q(first_name__icontains=text) | Q(last_name__icontains=text)).order_by("-date_joined")[:20])
        if users:
            context.user_data.clear()
            keys = [[InlineKeyboardButton((u.get_full_name() or u.first_name or u.email or u.username)[:40], callback_data=f"user:{u.id}")] for u in users]
            keys.append([InlineKeyboardButton("⬅️ کاربران", callback_data="users")])
            await update.message.reply_text(f"✅ {len(users)} کاربر پیدا شد:", reply_markup=InlineKeyboardMarkup(keys))
        else:
            await update.message.reply_text("کاربری با این نام یا ایمیل پیدا نشد. دوباره جست‌وجو کنید یا /start بزنید.")
    elif flow == "user_name" and text:
        user = await User.objects.aget(pk=context.user_data["user_id"], is_staff=False)
        user.first_name = text[:150]; user.last_name = ""
        await user.asave(update_fields=["first_name", "last_name"])
        context.user_data.clear(); await update.message.reply_text("✅ نام کاربر تغییر کرد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("باز کردن کاربر", callback_data=f"user:{user.id}")]]))
    elif flow == "user_email" and text:
        email_value = text.strip().lower()
        if "@" not in email_value or "." not in email_value.split("@")[-1]:
            await update.message.reply_text("ایمیل معتبر نیست؛ دوباره بفرستید."); return
        user = await User.objects.aget(pk=context.user_data["user_id"], is_staff=False)
        duplicate = await User.objects.filter(Q(email__iexact=email_value) | Q(username__iexact=email_value)).exclude(pk=user.pk).aexists()
        if duplicate:
            await update.message.reply_text("این ایمیل قبلاً برای کاربر دیگری ثبت شده است."); return
        old_email = (user.email or "").lower()
        user.email = email_value
        if not user.username or user.username.lower() == old_email:
            user.username = email_value
            await user.asave(update_fields=["email", "username"])
        else:
            await user.asave(update_fields=["email"])
        context.user_data.clear(); await update.message.reply_text("✅ ایمیل کاربر تغییر کرد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("باز کردن کاربر", callback_data=f"user:{user.id}")]]))
    elif flow == "search_product" and text:
        product = await Product.objects.filter(Q(sku__iexact=text) | Q(sku__icontains=text)).afirst()
        if product:
            context.user_data.clear(); await update.message.reply_text(f"✅ {product.name}\nکد: {product.sku}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("باز کردن محصول", callback_data=f"product:{product.id}")]]))
        else: await update.message.reply_text("محصولی با این کد پیدا نشد؛ دوباره امتحان کنید یا /start بزنید.")
    elif flow == "search_receipt" and text:
        order = await Order.objects.filter(code__iexact=text, receipt__isnull=False).afirst()
        if order:
            context.user_data.clear(); await update.message.reply_text(f"✅ سفارش {order.code} پیدا شد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("باز کردن سفارش", callback_data=f"order:{order.id}")]]))
        else: await update.message.reply_text("سفارشی با این کد پیدا نشد.")
    elif flow == "new_product":
        step = context.user_data.get("step")
        if step == "name" and text:
            context.user_data.update(step="price", name=text); await update.message.reply_text("قیمت به تومان (فقط عدد):")
        elif step == "price" and text.replace(",", "").isdigit():
            context.user_data.update(step="stock", price=int(text.replace(",", ""))); await update.message.reply_text("موجودی اولیه:")
        elif step == "stock" and text.isdigit():
            context.user_data.update(step="description", stock=int(text)); await update.message.reply_text("توضیح محصول را بفرستید (یا -):")
        elif step == "description":
            context.user_data.update(step="assurance_1", description="" if text == "-" else text); await update.message.reply_text("مزیت یا تضمین اول محصول را بنویسید؛ مثال: تضمین سلامت فیزیکی. برای خالی - بفرستید:")
        elif step == "assurance_1":
            context.user_data.update(step="assurance_2", assurance_1="" if text == "-" else text); await update.message.reply_text("مزیت یا تضمین دوم را بفرستید؛ برای خالی - بفرستید:")
        elif step == "assurance_2":
            context.user_data.update(step="assurance_3", assurance_2="" if text == "-" else text); await update.message.reply_text("مزیت یا تضمین سوم را بفرستید؛ برای خالی - بفرستید:")
        elif step == "assurance_3":
            product = await Product.objects.acreate(
                category_id=context.user_data["category_id"], name=context.user_data["name"], price=context.user_data["price"], stock=context.user_data["stock"],
                description=context.user_data["description"], assurance_1=context.user_data["assurance_1"], assurance_2=context.user_data["assurance_2"], assurance_3="" if text == "-" else text,
            )
            context.user_data.update(step="photo", product_id=product.id); await update.message.reply_text(f"✅ کد محصول: {product.sku}\nعکس محصول را بفرستید (یا /skip):")
    elif flow == "edit_assurances" and text:
        step = context.user_data.get("step")
        if step == "assurance_1":
            context.user_data.update(step="assurance_2", assurance_1="" if text == "-" else text); await update.message.reply_text("مزیت دوم را بفرستید؛ برای خالی - بفرستید:")
        elif step == "assurance_2":
            context.user_data.update(step="assurance_3", assurance_2="" if text == "-" else text); await update.message.reply_text("مزیت سوم را بفرستید؛ برای خالی - بفرستید:")
        elif step == "assurance_3":
            await Product.objects.filter(pk=context.user_data["product_id"]).aupdate(assurance_1=context.user_data["assurance_1"], assurance_2=context.user_data["assurance_2"], assurance_3="" if text == "-" else text, updated_at=timezone.now())
            context.user_data.clear(); await update.message.reply_text("✅ مزایای محصول ذخیره شد.", reply_markup=main_keyboard())
    elif flow in ("edit_price", "edit_compare_price", "edit_stock") and text.replace(",", "").isdigit():
        value = int(text.replace(",", "")); field = "price" if flow == "edit_price" else ("compare_at_price" if flow == "edit_compare_price" else "stock")
        if field == "compare_at_price" and value == 0: value = None
        await Product.objects.filter(pk=context.user_data["product_id"]).aupdate(**{field: value, "updated_at": timezone.now()})
        context.user_data.clear(); await update.message.reply_text("✅ ذخیره شد.", reply_markup=main_keyboard())
    elif flow in ("setting_name", "setting_announcement") and text:
        store = await sync_to_async(SiteSetting.load)(); field = "site_name" if flow == "setting_name" else "announcement"; setattr(store, field, text)
        await store.asave(update_fields=[field, "updated_at"]); context.user_data.clear(); await update.message.reply_text("✅ همان لحظه روی سایت اعمال شد.", reply_markup=main_keyboard())
    elif flow == "setting_enamad":
        store = await sync_to_async(SiteSetting.load)()
        store.enamad_html = "" if text == "-" else text
        await store.asave(update_fields=["enamad_html", "updated_at"])
        context.user_data.clear()
        await update.message.reply_text("✅ اطلاعات اینماد ذخیره شد و در فوتر سایت نمایش داده می‌شود." if text != "-" else "✅ اینماد از سایت حذف شد.", reply_markup=main_keyboard())
    elif flow in ("setting_shipping", "setting_free_shipping") and text.replace(",", "").isdigit():
        store = await sync_to_async(SiteSetting.load)(); field = "shipping_fee" if flow == "setting_shipping" else "free_shipping_threshold"; setattr(store, field, int(text.replace(",", "")))
        await store.asave(update_fields=[field, "updated_at"]); context.user_data.clear(); await update.message.reply_text("✅ تنظیم هزینه ارسال روی سایت اعمال شد.", reply_markup=main_keyboard())
    elif flow == "setting_card" and "|" in text:
        card, owner = [x.strip() for x in text.split("|", 1)]; store = await sync_to_async(SiteSetting.load)(); store.card_number, store.card_owner = card, owner
        await store.asave(update_fields=["card_number", "card_owner", "updated_at"]); context.user_data.clear(); await update.message.reply_text("✅ اطلاعات کارت ذخیره شد.", reply_markup=main_keyboard())
    elif flow == "social_add" and text:
        step = context.user_data.get("step")
        if step == "title": context.user_data.update(step="url", title=text); await update.message.reply_text("لینک مستقیم را بفرستید؛ مثال لینک پی‌وی تلگرام/اینستاگرام/ایتا/روبیکا:")
        elif step == "url": context.user_data.update(step="photo", url=text); await update.message.reply_text("حالا عکس یا آیکن این شبکه اجتماعی را بفرستید:")
    elif flow in ("social_title", "social_url") and text:
        item = await SocialLink.objects.aget(pk=context.user_data["social_id"]); field = "title" if flow == "social_title" else "url"; setattr(item, field, text)
        await item.asave(update_fields=[field, "updated_at"]); context.user_data.clear(); await update.message.reply_text("✅ اطلاعات شبکه اجتماعی ویرایش شد.", reply_markup=main_keyboard())
    elif flow == "page_add" and text:
        step = context.user_data.get("step")
        if step == "title": context.user_data.update(step="body", title=text); await update.message.reply_text("متن صفحه را بفرستید:")
        elif step == "body": context.user_data.update(step="group", body=text); await update.message.reply_text("گروه فوتر را بفرستید: guide یا contact یا other")
        elif step == "group" and text in ("guide", "contact", "other"):
            page = await ContentPage.objects.acreate(title=context.user_data["title"], body=context.user_data["body"], footer_group=text); context.user_data.clear(); await update.message.reply_text(f"✅ صفحه {page.title} ساخته شد و روی سایت قرار گرفت.", reply_markup=main_keyboard())
    elif flow in ("page_title", "page_body") and text:
        page = await ContentPage.objects.aget(pk=context.user_data["page_id"]); field = "title" if flow == "page_title" else "body"; setattr(page, field, text)
        await page.asave(); context.user_data.clear(); await update.message.reply_text("✅ صفحه ویرایش شد.", reply_markup=main_keyboard())
    elif flow == "banner_add" and text:
        step = context.user_data.get("step")
        if step == "title": context.user_data.update(step="subtitle", title="" if text == "-" else text); await update.message.reply_text("متن کوتاه بنر را بفرستید (یا -):")
        elif step == "subtitle": context.user_data.update(step="link", subtitle="" if text == "-" else text); await update.message.reply_text("لینک دکمه را بفرستید؛ مثال /products/")
        elif step == "link": context.user_data.update(step="photo", link=text); await update.message.reply_text("حالا عکس بنر را بفرستید:")
    elif flow == "discount_add" and text:
        step = context.user_data.get("step")
        if step == "code": context.user_data.update(step="percent", code=text.strip().upper()); await update.message.reply_text("درصد تخفیف را بفرستید؛ مثال 20")
        elif step == "percent" and text.isdigit() and 1 <= int(text) <= 99: context.user_data.update(step="min", percent=int(text)); await update.message.reply_text("حداقل مبلغ سفارش به تومان؛ برای بدون حداقل 0:")
        elif step == "min" and text.replace(",", "").isdigit():
            try: item = await DiscountCode.objects.acreate(code=context.user_data["code"], percent=context.user_data["percent"], min_order_amount=int(text.replace(",", "")))
            except Exception: await update.message.reply_text("این کد قبلاً وجود دارد یا معتبر نیست."); return
            context.user_data.clear(); await update.message.reply_text(f"✅ کد {item.code} با {item.percent}% تخفیف ساخته شد.", reply_markup=main_keyboard())
    elif flow == "tracking_code" and text:
        order = await Order.objects.aget(pk=context.user_data["order_id"]); await sync_to_async(set_order_status)(order, "shipped", "مرسوله تحویل پست شد", tracking_code=text)
        context.user_data.clear(); await update.message.reply_text(f"✅ کد رهگیری {text} ثبت شد و در سفارش مشتری نمایش داده می‌شود.", reply_markup=main_keyboard())
    elif flow == "backup_interval" and text.isdigit():
        minutes = int(text)
        if minutes != 0 and minutes < 5:
            await update.message.reply_text("حداقل فاصله امن ۵ دقیقه است؛ عدد ۵ یا بیشتر، یا ۰ بفرستید."); return
        store = await sync_to_async(SiteSetting.load)(); store.backup_interval_minutes = minutes
        await store.asave(update_fields=["backup_interval_minutes", "updated_at"]); context.user_data.clear()
        await update.message.reply_text("✅ زمان‌بندی بکاپ ذخیره شد." if minutes else "✅ بکاپ خودکار غیرفعال شد.", reply_markup=main_keyboard())
    else: await update.message.reply_text("ورودی نامعتبر است. از /start شروع کنید.")


async def photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update) or context.user_data.get("flow") not in ("new_product", "edit_photo", "setting_logo", "banner_add", "social_add", "social_photo", "category_photo"): return
    file = await update.message.photo[-1].get_file(); data = await file.download_as_bytearray()
    if context.user_data.get("flow") == "setting_logo":
        store = await sync_to_async(SiteSetting.load)(); await sync_to_async(store.logo.save)("telegram-logo.jpg", ContentFile(bytes(data)), save=True); text = "✅ لوگوی سایت همان لحظه تغییر کرد."
    elif context.user_data.get("flow") == "category_photo":
        cat = await Category.objects.aget(pk=context.user_data["category_id"]); await sync_to_async(cat.image.save)(f"category-{cat.id}-{timezone.now().timestamp():.0f}.jpg", ContentFile(bytes(data)), save=True); text = f"✅ عکس دسته {cat.name} ذخیره شد و روی سایت نمایش داده می‌شود."
    elif context.user_data.get("flow") == "banner_add":
        banner = HeroSlide(title=context.user_data.get("title", ""), subtitle=context.user_data.get("subtitle", ""), link=context.user_data.get("link", "/products/"))
        await sync_to_async(banner.image.save)(f"telegram-banner-{timezone.now().timestamp():.0f}.jpg", ContentFile(bytes(data)), save=True); text = "✅ بنر جدید ساخته شد و در اسلایدر سایت قرار گرفت."
    elif context.user_data.get("flow") == "social_add":
        item = SocialLink(title=context.user_data["title"], url=context.user_data["url"])
        await sync_to_async(item.image.save)(f"social-{timezone.now().timestamp():.0f}.jpg", ContentFile(bytes(data)), save=True); text = f"✅ {item.title} به فوتر سایت اضافه شد."
    elif context.user_data.get("flow") == "social_photo":
        item = await SocialLink.objects.aget(pk=context.user_data["social_id"]); await sync_to_async(item.image.save)(f"social-{item.id}-{timezone.now().timestamp():.0f}.jpg", ContentFile(bytes(data)), save=True); text = f"✅ عکس {item.title} تغییر کرد."
    else:
        product = await Product.objects.aget(pk=context.user_data["product_id"]); await sync_to_async(product.image.save)(f"telegram-{product.id}.jpg", ContentFile(bytes(data)), save=True); text = f"✅ عکس ذخیره شد. کد محصول: {product.sku}"
    context.user_data.clear(); await update.message.reply_text(text, reply_markup=main_keyboard())


async def document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update) or context.user_data.get("flow") != "restore_upload": return
    doc = update.message.document
    if doc.file_size and doc.file_size > MAX_TELEGRAM_BYTES:
        await update.message.reply_text("فایل برای دریافت از ربات بزرگ‌تر از ۴۸ مگابایت است."); return
    suffix = Path(doc.file_name or "backup.sanabackup").suffix
    if suffix != ".sanabackup":
        await update.message.reply_text("فقط فایل معتبر با پسوند .sanabackup پذیرفته می‌شود."); return
    handle = tempfile.NamedTemporaryFile(prefix="sanashop-restore-", suffix=suffix, delete=False); handle.close()
    try:
        telegram_file = await doc.get_file(); await telegram_file.download_to_drive(custom_path=handle.name)
        manifest = await asyncio.to_thread(validate_backup_archive, handle.name)
    except Exception as exc:
        Path(handle.name).unlink(missing_ok=True); await update.message.reply_text(f"❌ فایل بکاپ معتبر نیست: {exc}"); return
    context.user_data.update(flow="restore_confirm", restore_path=handle.name)
    await update.message.reply_text(f"بکاپ معتبر است. تاریخ ساخت: {manifest.get('created_at', '-')}\n⚠️ با تایید، دیتابیس و تصاویر فعلی با محتوای این فایل جایگزین می‌شوند. قبل از آن یک بکاپ اضطراری خودکار ساخته می‌شود.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ تایید بازگردانی", callback_data="restore_confirm")], [InlineKeyboardButton("لغو", callback_data="restore_cancel")]]))


async def skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if allowed(update) and context.user_data.get("flow") == "new_product" and context.user_data.get("step") == "photo":
        product = await Product.objects.aget(pk=context.user_data["product_id"]); context.user_data.clear()
        await update.message.reply_text(f"✅ محصول ساخته شد. کد محصول: {product.sku}", reply_markup=main_keyboard())


def run():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token: raise SystemExit("TELEGRAM_BOT_TOKEN is required")
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start)); app.add_handler(CommandHandler("skip", skip)); app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.PHOTO, photo)); app.add_handler(MessageHandler(filters.Document.ALL, document)); app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message))
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__": run()
