import logging
import os

import httpx
from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .models import DiscountCode, Order, OrderItem, OrderStatusEvent, Product, SiteSetting

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


def discount_from_session(request, subtotal):
    code = (request.session.get("discount_code") or "").strip().upper()
    if not code:
        return None, 0
    discount = DiscountCode.objects.filter(code__iexact=code).first()
    if not discount or not discount.is_valid_for(subtotal):
        request.session.pop("discount_code", None)
        return None, 0
    return discount, discount.discount_for(subtotal)


@transaction.atomic
def create_order(form, rows, subtotal, store, customer=None, discount=None, discount_amount=0):
    shipping = 0 if subtotal >= store.free_shipping_threshold else store.shipping_fee
    order = form.save(commit=False)
    order.customer = customer
    order.subtotal, order.shipping = subtotal, shipping
    order.discount_amount = min(max(int(discount_amount or 0), 0), subtotal)
    order.discount_code = discount.code if discount else ""
    order.total = max(0, subtotal + shipping - order.discount_amount)
    order.save()
    for row in rows:
        product = Product.objects.select_for_update().get(pk=row["product"].pk)
        qty = row["quantity"]
        if not product.is_active or product.stock < qty:
            raise ValueError(f"موجودی «{product.name}» کافی نیست.")
        OrderItem.objects.create(order=order, product=product, title=product.name, unit_price=product.price, quantity=qty)
        product.stock -= qty
        product.save(update_fields=["stock", "updated_at"])
    OrderStatusEvent.objects.create(order=order, status=order.status, note="سفارش ثبت شد")
    if discount:
        DiscountCode.objects.filter(pk=discount.pk).update(used_count=F("used_count") + 1)
    return order


def set_order_status(order, status, note="", tracking_code=""):
    order.status = status
    fields = ["status", "updated_at"]
    if tracking_code:
        order.tracking_code = tracking_code.strip()
        order.tracking_url = f"https://tracking.post.ir/?id={order.tracking_code}"
        fields += ["tracking_code", "tracking_url"]
    if status == "shipped":
        order.shipped_at = timezone.now()
        fields.append("shipped_at")
    order.save(update_fields=fields)
    OrderStatusEvent.objects.create(order=order, status=status, note=note)
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
        order.payment_ref_id = str(data.get("ref_id", ""))
        order.save(update_fields=["payment_ref_id", "updated_at"])
        set_order_status(order, "paid", "پرداخت آنلاین تأیید شد")
        return True
    return False
