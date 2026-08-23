import logging
import os

import httpx
from django.conf import settings
from django.db import transaction

from .models import Order, OrderItem, Product, SiteSetting

logger = logging.getLogger(__name__)


def cart_rows(request):
    cart = request.session.get("cart", {})
    products = Product.objects.filter(pk__in=cart.keys(), is_active=True).select_related("category")
    rows, subtotal = [], 0
    for product in products:
        qty = min(max(int(cart.get(str(product.pk), 0)), 0), product.stock)
        if qty:
            line_total = product.price * qty
            rows.append({"product": product, "quantity": qty, "total": line_total})
            subtotal += line_total
    return rows, subtotal


@transaction.atomic
def create_order(form, rows, subtotal, store):
    shipping = 0 if subtotal >= store.free_shipping_threshold else store.shipping_fee
    order = form.save(commit=False)
    order.subtotal, order.shipping, order.total = subtotal, shipping, subtotal + shipping
    order.save()
    for row in rows:
        product = Product.objects.select_for_update().get(pk=row["product"].pk)
        qty = row["quantity"]
        if not product.is_active or product.stock < qty:
            raise ValueError(f"موجودی «{product.name}» کافی نیست.")
        OrderItem.objects.create(order=order, product=product, title=product.name, unit_price=product.price, quantity=qty)
        product.stock -= qty
        product.save(update_fields=["stock", "updated_at"])
    return order


def telegram_admin_ids():
    return [x.strip() for x in os.environ.get("TELEGRAM_ADMIN_IDS", "").split(",") if x.strip()]


def send_telegram_text(text):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        return
    for chat_id in telegram_admin_ids():
        try:
            httpx.post(f"https://api.telegram.org/bot{token}/sendMessage", data={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}, timeout=12)
        except Exception:
            logger.exception("Telegram notification failed")


def send_receipt_to_telegram(receipt):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        return
    caption = f"🧾 رسید جدید\nسفارش: <b>{receipt.order.code}</b>\nمبلغ: {receipt.order.total:,} تومان\nمشتری: {receipt.order.full_name}"
    for chat_id in telegram_admin_ids():
        try:
            with receipt.image.open("rb") as photo:
                httpx.post(f"https://api.telegram.org/bot{token}/sendPhoto", data={"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"}, files={"photo": photo}, timeout=25)
        except Exception:
            logger.exception("Telegram receipt notification failed")


def zarinpal_request(order, callback_url):
    store = SiteSetting.load()
    base = "https://sandbox.zarinpal.com" if store.zarinpal_sandbox else "https://payment.zarinpal.com"
    api = "https://sandbox.zarinpal.com/pg/v4/payment/request.json" if store.zarinpal_sandbox else "https://payment.zarinpal.com/pg/v4/payment/request.json"
    payload = {"merchant_id": store.zarinpal_merchant_id, "amount": order.total * 10, "callback_url": callback_url, "description": f"سفارش {order.code}", "metadata": {"mobile": order.mobile, "email": order.email or ""}}
    response = httpx.post(api, json=payload, timeout=20)
    response.raise_for_status()
    data = response.json().get("data") or {}
    if int(data.get("code", 0)) != 100:
        raise ValueError("ایجاد تراکنش زرین‌پال ناموفق بود.")
    order.authority = data["authority"]
    order.save(update_fields=["authority", "updated_at"])
    return f"{base}/pg/StartPay/{order.authority}"


def zarinpal_verify(order):
    store = SiteSetting.load()
    api = "https://sandbox.zarinpal.com/pg/v4/payment/verify.json" if store.zarinpal_sandbox else "https://payment.zarinpal.com/pg/v4/payment/verify.json"
    response = httpx.post(api, json={"merchant_id": store.zarinpal_merchant_id, "amount": order.total * 10, "authority": order.authority}, timeout=20)
    response.raise_for_status()
    data = response.json().get("data") or {}
    if int(data.get("code", 0)) in (100, 101):
        order.status = "paid"
        order.payment_ref_id = str(data.get("ref_id", ""))
        order.save(update_fields=["status", "payment_ref_id", "updated_at"])
        return True
    return False

