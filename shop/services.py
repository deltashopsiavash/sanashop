import logging
from datetime import timedelta

import httpx
from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .models import BotEvent, DiscountCode, Order, OrderItem, OrderStatusEvent, Product, SiteSetting
from .pricing import effective_price

logger = logging.getLogger(__name__)
RESERVATION_MINUTES = 45


def money(value):
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


def reservation_deadline():
    return timezone.now() + timedelta(minutes=RESERVATION_MINUTES)


def queue_bot_event(kind, payload):
    try:
        return BotEvent.objects.create(kind=kind, payload=payload or {})
    except Exception:
        logger.exception("Could not queue bot event: %s", kind)
        return None


def order_event_payload(order):
    items = []
    for item in order.items.select_related("product").all():
        items.append({
            "id": item.id,
            "product_id": item.product_id,
            "sku": item.product.sku if item.product else "",
            "title": item.title,
            "quantity": item.quantity,
            "unit_price": item.unit_price,
            "total": item.total,
        })
    return {
        "order_id": order.id,
        "code": order.code,
        "full_name": order.full_name,
        "mobile": order.mobile,
        "email": order.email,
        "province": order.province,
        "city": order.city,
        "address": order.address,
        "postal_code": order.postal_code,
        "note": order.note,
        "subtotal": order.subtotal,
        "shipping": order.shipping,
        "discount_amount": order.discount_amount,
        "discount_code": order.discount_code,
        "total": order.total,
        "payment_method": order.payment_method,
        "payment_method_label": order.get_payment_method_display(),
        "status": order.status,
        "status_label": order.get_status_display(),
        "tracking_code": order.tracking_code,
        "payment_ref_id": order.payment_ref_id,
        "reservation_expires_at": order.reservation_expires_at.isoformat() if order.reservation_expires_at else None,
        "reservation_remaining_seconds": order.reservation_remaining_seconds,
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "items": items,
    }


def order_report_text(order, title="🧾 فاکتور جدید"):
    payload = order_event_payload(order)
    lines = [
        title,
        f"کد سفارش: {payload['code']}",
        f"مشتری: {payload['full_name']}",
        f"موبایل: {payload['mobile']}",
        f"آدرس: {payload['province']}، {payload['city']} — {payload['address']}",
        f"کد پستی: {payload['postal_code']}",
        f"روش پرداخت: {payload['payment_method_label']}",
        f"جمع کالاها: {money(payload['subtotal'])} تومان",
    ]
    if payload["discount_amount"]:
        label = f" ({payload['discount_code']})" if payload["discount_code"] else ""
        lines.append(f"تخفیف: {money(payload['discount_amount'])} تومان{label}")
    lines += [
        f"ارسال: {'رایگان' if not payload['shipping'] else money(payload['shipping']) + ' تومان'}",
        f"مبلغ نهایی: {money(payload['total'])} تومان",
        "",
        "📦 محصولات:",
    ]
    for item in payload["items"]:
        lines.append(f"• {item['title']} × {item['quantity']} — {money(item['total'])} تومان")
    if order.reservation_expires_at and not order.stock_committed:
        remaining = max(0, order.reservation_remaining_seconds // 60)
        lines += ["", f"⏳ رزرو موجودی: حدود {remaining} دقیقه باقی مانده"]
    if order.note:
        lines += ["", f"📝 یادداشت: {order.note}"]
    return "\n".join(lines)


def notify_customer(order, subject, body):
    email = order.email or getattr(order.customer, "email", "")
    if not email:
        return
    try:
        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [email], fail_silently=True)
    except Exception:
        logger.exception("Customer email notification failed")


def release_order_stock(order):
    with transaction.atomic():
        locked = Order.objects.select_for_update().prefetch_related("items__product").get(pk=order.pk)
        if locked.stock_committed or locked.reservation_released:
            return False
        for item in locked.items.all():
            if not item.product_id:
                continue
            product = Product.objects.select_for_update().filter(pk=item.product_id).first()
            if product:
                product.reserved_stock = max(0, product.reserved_stock - item.quantity)
                product.save(update_fields=["reserved_stock", "updated_at"])
        locked.reservation_released = True
        locked.save(update_fields=["reservation_released", "updated_at"])
        order.reservation_released = True
        return True


def commit_order_stock(order):
    with transaction.atomic():
        locked = Order.objects.select_for_update().prefetch_related("items__product").get(pk=order.pk)
        if locked.stock_committed:
            order.stock_committed = True
            order.reservation_released = True
            return False
        if locked.reservation_released:
            raise ValueError("رزرو موجودی این فاکتور قبلاً آزاد شده است.")
        if locked.reservation_expires_at and timezone.now() >= locked.reservation_expires_at:
            raise ValueError("مهلت رزرو فاکتور تمام شده است.")
        for item in locked.items.all():
            if not item.product_id:
                continue
            product = Product.objects.select_for_update().get(pk=item.product_id)
            if product.stock < item.quantity:
                raise ValueError(f"موجودی واقعی «{item.title}» برای نهایی‌کردن سفارش کافی نیست.")
            product.stock -= item.quantity
            product.reserved_stock = max(0, product.reserved_stock - item.quantity)
            product.save(update_fields=["stock", "reserved_stock", "updated_at"])
        locked.stock_committed = True
        locked.reservation_released = True
        locked.save(update_fields=["stock_committed", "reservation_released", "updated_at"])
        order.stock_committed = True
        order.reservation_released = True
        return True


def expire_reservations(limit=100):
    now = timezone.now()
    ids = list(
        Order.objects.filter(
            stock_committed=False,
            reservation_released=False,
            reservation_expires_at__isnull=False,
            reservation_expires_at__lte=now,
            status__in=["pending", "review", "rejected"],
        ).values_list("id", flat=True)[:limit]
    )
    expired = []
    for order_id in ids:
        order = Order.objects.filter(pk=order_id).select_related("customer").first()
        if not order:
            continue
        if not release_order_stock(order):
            continue
        order.status = "cancelled"
        order.admin_note = ((order.admin_note or "") + "\nمهلت ۴۵ دقیقه‌ای رزرو فاکتور تمام شد.").strip()
        order.save(update_fields=["status", "admin_note", "updated_at"])
        OrderStatusEvent.objects.create(order=order, status="cancelled", note="پایان مهلت رزرو فاکتور")
        queue_bot_event("reservation_expired", order_event_payload(order))
        notify_customer(order, f"لغو سفارش {order.code}", "مهلت رزرو سفارش شما به پایان رسید و سفارش لغو شد.")
        expired.append(order.id)
    return expired


def cart_rows(request):
    expire_reservations(limit=30)
    cart = request.session.get("cart", {})
    products = Product.objects.filter(pk__in=cart.keys(), is_active=True).select_related("category", "promotion")
    rows, subtotal = [], 0
    clean = {}
    for product in products:
        try:
            requested = int(cart.get(str(product.pk), 0))
        except (TypeError, ValueError):
            requested = 0
        qty = min(max(requested, 0), product.available_stock)
        if qty:
            unit_price = effective_price(product)
            line_total = unit_price * qty
            rows.append({"product": product, "quantity": qty, "unit_price": unit_price, "total": line_total})
            subtotal += line_total
            clean[str(product.pk)] = qty
    if clean != cart:
        request.session["cart"] = clean
        request.session.modified = True
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
    shipping = store.shipping_for(subtotal)
    locked_rows = []
    locked_subtotal = 0
    for row in rows:
        product = Product.objects.select_for_update().select_related("promotion").get(pk=row["product"].pk)
        qty = int(row["quantity"])
        if not product.is_active or product.available_stock < qty:
            raise ValueError(f"موجودی آزاد «{product.name}» کافی نیست.")
        unit_price = effective_price(product)
        locked_rows.append((product, qty, unit_price))
        locked_subtotal += unit_price * qty

    if locked_subtotal != subtotal:
        subtotal = locked_subtotal
        shipping = store.shipping_for(subtotal)
        if discount:
            discount_amount = discount.discount_for(subtotal)

    order = form.save(commit=False)
    order.customer = customer
    order.subtotal = subtotal
    order.shipping = shipping
    order.discount_amount = min(max(int(discount_amount or 0), 0), subtotal)
    order.discount_code = discount.code if discount else ""
    order.total = max(0, subtotal + shipping - order.discount_amount)
    order.status = "pending"
    order.reservation_expires_at = reservation_deadline()
    order.stock_committed = False
    order.reservation_released = False
    order.save()

    for product, qty, unit_price in locked_rows:
        OrderItem.objects.create(order=order, product=product, title=product.name, unit_price=unit_price, quantity=qty)
        Product.objects.filter(pk=product.pk).update(reserved_stock=F("reserved_stock") + qty, updated_at=timezone.now())

    OrderStatusEvent.objects.create(order=order, status="pending", note="فاکتور ساخته شد و موجودی موقتاً رزرو شد")
    if discount:
        DiscountCode.objects.filter(pk=discount.pk).update(used_count=F("used_count") + 1)
    order.refresh_from_db()
    queue_bot_event("order_created", order_event_payload(order))
    return order


def set_order_status(order, status, note="", tracking_code=""):
    if status not in dict(Order.STATUS):
        raise ValueError("وضعیت سفارش معتبر نیست.")
    if status in ("paid", "processing", "shipped", "delivered") and not order.stock_committed:
        commit_order_stock(order)
    elif status == "cancelled" and not order.stock_committed:
        release_order_stock(order)

    order.status = status
    fields = ["status", "updated_at"]
    if status in ("paid", "processing", "shipped", "delivered") and not order.paid_at:
        order.paid_at = timezone.now()
        fields.append("paid_at")
    if tracking_code:
        order.tracking_code = tracking_code.strip()
        order.tracking_url = f"https://tracking.post.ir/?id={order.tracking_code}"
        fields += ["tracking_code", "tracking_url"]
    if status == "shipped":
        order.shipped_at = timezone.now()
        fields.append("shipped_at")
    order.save(update_fields=list(dict.fromkeys(fields)))
    OrderStatusEvent.objects.create(order=order, status=status, note=note)
    queue_bot_event("order_status", order_event_payload(order))

    labels = {
        "paid": "پرداخت سفارش شما تأیید شد.",
        "processing": "سفارش شما در حال آماده‌سازی است.",
        "shipped": f"سفارش شما ارسال شد.{(' کد رهگیری: ' + order.tracking_code) if order.tracking_code else ''}",
        "delivered": "سفارش شما تحویل‌شده ثبت شد.",
        "cancelled": "سفارش شما لغو شد.",
    }
    if status in labels:
        notify_customer(order, f"وضعیت سفارش {order.code}", labels[status])
    return order


def send_telegram_text(text):
    logger.info("Legacy Telegram message suppressed: %s", text)


def send_receipt_to_telegram(receipt):
    queue_bot_event("receipt_uploaded", {**order_event_payload(receipt.order), "receipt_id": receipt.id})


def zarinpal_request(order, callback_url):
    store = SiteSetting.load()
    base = "https://sandbox.zarinpal.com" if store.zarinpal_sandbox else "https://payment.zarinpal.com"
    api = "https://sandbox.zarinpal.com/pg/v4/payment/request.json" if store.zarinpal_sandbox else "https://payment.zarinpal.com/pg/v4/payment/request.json"
    payload = {
        "merchant_id": store.zarinpal_merchant_id,
        "amount": order.total * 10,
        "callback_url": callback_url,
        "description": f"سفارش {order.code}",
        "metadata": {"mobile": order.mobile, "email": order.email or ""},
    }
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
    response = httpx.post(
        api,
        json={"merchant_id": store.zarinpal_merchant_id, "amount": order.total * 10, "authority": order.authority},
        timeout=20,
    )
    response.raise_for_status()
    data = response.json().get("data") or {}
    if int(data.get("code", 0)) in (100, 101):
        order.payment_ref_id = str(data.get("ref_id", ""))
        order.save(update_fields=["payment_ref_id", "updated_at"])
        set_order_status(order, "paid", "پرداخت آنلاین تأیید شد")
        queue_bot_event("payment_success", order_event_payload(order))
        return True
    queue_bot_event("payment_failed", order_event_payload(order))
    return False
