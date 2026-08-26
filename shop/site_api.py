import base64
import json
import os
import secrets
from functools import wraps

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.db import IntegrityError
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from .models import (
    BotEvent,
    Category,
    ContentPage,
    DiscountCode,
    HeroSlide,
    Order,
    OrderStatusEvent,
    PaymentReceipt,
    Product,
    SiteSetting,
    SocialLink,
)
from .services import expire_reservations, notify_customer, order_event_payload, queue_bot_event, set_order_status

User = get_user_model()
MAX_IMAGE_BYTES = 10 * 1024 * 1024


def _json(request):
    try:
        return json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        return {}


def _image(payload):
    raw = payload.get("image_b64") or ""
    if not raw:
        raise ValueError("image_required")
    try:
        decoded = base64.b64decode(raw, validate=True)
    except Exception as exc:
        raise ValueError("invalid_image") from exc
    if not decoded or len(decoded) > MAX_IMAGE_BYTES:
        raise ValueError("invalid_image_size")
    name = str(payload.get("filename") or "image.jpg").replace("/", "_")[-120:]
    return name, ContentFile(decoded)


def _field_b64(field):
    if not field:
        raise ValueError("image_not_found")
    with field.open("rb") as handle:
        raw = handle.read(MAX_IMAGE_BYTES + 1)
    if len(raw) > MAX_IMAGE_BYTES:
        raise ValueError("image_too_large")
    return base64.b64encode(raw).decode("ascii")


def api_auth(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        expected = (os.environ.get("SANASHOP_BOT_API_KEY") or "").strip()
        supplied = request.headers.get("Authorization", "")
        if not expected or not supplied.startswith("Bearer "):
            return JsonResponse({"ok": False, "error": "unauthorized"}, status=401)
        if not secrets.compare_digest(supplied[7:].strip(), expected):
            return JsonResponse({"ok": False, "error": "unauthorized"}, status=401)
        return view(request, *args, **kwargs)

    return wrapped


def _not_found(name):
    return JsonResponse({"ok": False, "error": f"{name}_not_found"}, status=404)


def _order_data(item):
    receipt = PaymentReceipt.objects.filter(order=item).first()
    return {
        **order_event_payload(item),
        "receipt_id": receipt.id if receipt else None,
        "receipt_status": receipt.status if receipt else None,
        "receipt_rejection_reason": item.receipt_rejection_reason,
        "reservation_active": item.reservation_active,
        "stock_committed": item.stock_committed,
    }


@csrf_exempt
@api_auth
def bot_api(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "POST required"}, status=405)

    data = _json(request)
    action = data.get("action")
    payload = data.get("payload") or {}
    store = SiteSetting.load()

    try:
        if action == "ping":
            return JsonResponse({"ok": True, "site": {"name": store.site_name, "domain": os.environ.get("DOMAIN", ""), "version": 3}})

        if action == "dashboard":
            expire_reservations(limit=30)
            return JsonResponse({"ok": True, "data": {
                "site_name": store.site_name,
                "products": Product.objects.filter(is_active=True).count(),
                "orders": Order.objects.count(),
                "pending_orders": Order.objects.filter(status__in=["pending", "review", "rejected"]).count(),
                "users": User.objects.filter(is_staff=False).count(),
            }})

        if action == "categories":
            rows = []
            for item in Category.objects.order_by("sort_order", "name")[:100]:
                rows.append({
                    "id": item.id,
                    "name": item.name,
                    "is_active": item.is_active,
                    "parent_id": item.parent_id,
                    "has_image": bool(item.image),
                    "product_count": item.products.filter(is_active=True).count(),
                })
            return JsonResponse({"ok": True, "data": rows})

        if action == "category_detail":
            item = Category.objects.filter(pk=payload.get("id")).first()
            if not item:
                return _not_found("category")
            return JsonResponse({"ok": True, "data": {
                "id": item.id,
                "name": item.name,
                "is_active": item.is_active,
                "parent_id": item.parent_id,
                "product_count": item.products.filter(is_active=True).count(),
                "has_image": bool(item.image),
            }})

        if action == "category_create":
            name = str(payload.get("name") or "").strip()
            if not name:
                return JsonResponse({"ok": False, "error": "name_required"}, status=400)
            item = Category.objects.create(name=name, parent_id=payload.get("parent_id") or None)
            return JsonResponse({"ok": True, "data": {"id": item.id, "name": item.name}})

        if action == "category_update":
            item = Category.objects.filter(pk=payload.get("id")).first()
            if not item:
                return _not_found("category")
            changed = []
            if "name" in payload:
                item.name = str(payload["name"]).strip()[:100]
                item.slug = ""
                changed += ["name", "slug"]
            if "is_active" in payload:
                item.is_active = bool(payload["is_active"])
                changed.append("is_active")
            if "sort_order" in payload:
                item.sort_order = max(0, int(payload["sort_order"]))
                changed.append("sort_order")
            item.save()
            return JsonResponse({"ok": True})

        if action == "category_image_set":
            item = Category.objects.filter(pk=payload.get("id")).first()
            if not item:
                return _not_found("category")
            name, content = _image(payload)
            item.image.save(name, content, save=True)
            return JsonResponse({"ok": True})

        if action == "category_image_remove":
            item = Category.objects.filter(pk=payload.get("id")).first()
            if not item:
                return _not_found("category")
            if item.image:
                item.image.delete(save=False)
                item.image = ""
                item.save(update_fields=["image"])
            return JsonResponse({"ok": True})

        if action == "products":
            rows = list(
                Product.objects.select_related("category").order_by("-created_at").values(
                    "id", "name", "sku", "price", "compare_at_price", "stock", "reserved_stock",
                    "is_active", "is_amazing", "category__name"
                )[:100]
            )
            return JsonResponse({"ok": True, "data": rows})

        if action == "product_detail":
            item = Product.objects.select_related("category").filter(pk=payload.get("id")).first()
            if not item:
                return _not_found("product")
            return JsonResponse({"ok": True, "data": {
                "id": item.id,
                "name": item.name,
                "sku": item.sku,
                "price": item.price,
                "compare_at_price": item.compare_at_price,
                "stock": item.stock,
                "reserved_stock": item.reserved_stock,
                "available_stock": item.available_stock,
                "is_active": item.is_active,
                "is_amazing": item.is_amazing,
                "category_id": item.category_id,
                "category": item.category.name,
                "description": item.description,
                "has_image": bool(item.image),
            }})

        if action == "product_create":
            category = Category.objects.filter(pk=payload.get("category_id"), is_active=True).first()
            if not category:
                return _not_found("category")
            name = str(payload.get("name") or "").strip()
            price = int(payload.get("price") or 0)
            stock = int(payload.get("stock") or 0)
            if not name or price <= 0 or stock < 0:
                return JsonResponse({"ok": False, "error": "invalid_product"}, status=400)
            item = Product.objects.create(category=category, name=name, price=price, stock=stock, description=str(payload.get("description") or ""))
            return JsonResponse({"ok": True, "data": {"id": item.id, "name": item.name, "sku": item.sku}})

        if action == "product_update":
            item = Product.objects.filter(pk=payload.get("id")).first()
            if not item:
                return _not_found("product")
            allowed = {"price", "compare_at_price", "stock", "is_active", "is_amazing", "name", "description"}
            for key, value in payload.items():
                if key not in allowed:
                    continue
                if key in ("price", "stock"):
                    value = max(0, int(value))
                if key == "compare_at_price":
                    value = int(value or 0) or None
                setattr(item, key, value)
            if "name" in payload:
                item.slug = ""
            item.save()
            return JsonResponse({"ok": True})

        if action == "product_image_set":
            item = Product.objects.filter(pk=payload.get("id")).first()
            if not item:
                return _not_found("product")
            name, content = _image(payload)
            item.image.save(name, content, save=True)
            return JsonResponse({"ok": True})

        if action == "orders":
            expire_reservations(limit=50)
            rows = []
            for item in Order.objects.order_by("-created_at")[:100]:
                rows.append({
                    "id": item.id,
                    "code": item.code,
                    "full_name": item.full_name,
                    "mobile": item.mobile,
                    "total": item.total,
                    "status": item.status,
                    "status_label": item.get_status_display(),
                    "tracking_code": item.tracking_code,
                    "reservation_remaining_seconds": item.reservation_remaining_seconds,
                    "created_at": item.created_at.isoformat(),
                })
            return JsonResponse({"ok": True, "data": rows})

        if action == "order_detail":
            item = Order.objects.prefetch_related("items__product").filter(pk=payload.get("id")).first()
            if not item:
                return _not_found("order")
            return JsonResponse({"ok": True, "data": _order_data(item)})

        if action == "order_update":
            item = Order.objects.filter(pk=payload.get("id")).first()
            if not item:
                return _not_found("order")
            status = str(payload.get("status") or "")
            if status not in dict(Order.STATUS):
                return JsonResponse({"ok": False, "error": "invalid_status"}, status=400)
            tracking = str(payload.get("tracking_code") or "").strip()
            set_order_status(item, status, str(payload.get("note") or "Updated from Telegram manager"), tracking_code=tracking or None)
            return JsonResponse({"ok": True})

        if action == "receipts":
            rows = []
            for receipt in PaymentReceipt.objects.select_related("order").order_by("-created_at")[:100]:
                rows.append({
                    "id": receipt.id,
                    "order_id": receipt.order_id,
                    "order_code": receipt.order.code,
                    "total": receipt.order.total,
                    "status": receipt.status,
                    "full_name": receipt.order.full_name,
                    "created_at": receipt.created_at.isoformat(),
                })
            return JsonResponse({"ok": True, "data": rows})

        if action == "receipt_detail":
            receipt = PaymentReceipt.objects.select_related("order").filter(pk=payload.get("id")).first()
            if not receipt:
                return _not_found("receipt")
            return JsonResponse({"ok": True, "data": {
                "id": receipt.id,
                "order_id": receipt.order_id,
                "order_code": receipt.order.code,
                "total": receipt.order.total,
                "status": receipt.status,
                "full_name": receipt.order.full_name,
                "rejection_reason": receipt.order.receipt_rejection_reason,
            }})

        if action == "receipt_image":
            receipt = PaymentReceipt.objects.filter(pk=payload.get("id")).first()
            if not receipt:
                return _not_found("receipt")
            return JsonResponse({"ok": True, "data": {"image_b64": _field_b64(receipt.image), "filename": os.path.basename(receipt.image.name) or "receipt.jpg"}})

        if action == "receipt_update":
            receipt = PaymentReceipt.objects.select_related("order").filter(pk=payload.get("id")).first()
            if not receipt:
                return _not_found("receipt")
            status = str(payload.get("status") or "")
            if status not in ("approved", "rejected"):
                return JsonResponse({"ok": False, "error": "invalid_receipt_status"}, status=400)
            receipt.status = status
            receipt.reviewed_at = timezone.now()
            receipt.save(update_fields=["status", "reviewed_at"])
            if status == "approved":
                receipt.order.receipt_rejection_reason = ""
                receipt.order.save(update_fields=["receipt_rejection_reason", "updated_at"])
                set_order_status(receipt.order, "paid", "رسید کارت‌به‌کارت توسط مدیر تأیید شد")
                queue_bot_event("payment_success", order_event_payload(receipt.order))
            else:
                reason = str(payload.get("reason") or "رسید پرداخت توسط مدیر رد شد.").strip()[:500]
                receipt.order.status = "rejected"
                receipt.order.receipt_rejection_reason = reason
                receipt.order.save(update_fields=["status", "receipt_rejection_reason", "updated_at"])
                OrderStatusEvent.objects.create(order=receipt.order, status="rejected", note=reason[:250])
                queue_bot_event("order_status", order_event_payload(receipt.order))
                notify_customer(receipt.order, f"رسید سفارش {receipt.order.code} رد شد", f"رسید پرداخت شما تأیید نشد. دلیل: {reason}\nدر صورت باقی‌بودن زمان رزرو می‌توانید رسید جدید ارسال کنید.")
            return JsonResponse({"ok": True})

        if action == "users":
            rows = list(User.objects.filter(is_staff=False).order_by("-date_joined").values("id", "email", "first_name", "last_name", "is_active", "date_joined")[:100])
            for row in rows:
                if row.get("date_joined"):
                    row["date_joined"] = row["date_joined"].isoformat()
            return JsonResponse({"ok": True, "data": rows})

        if action == "user_detail":
            item = User.objects.filter(pk=payload.get("id"), is_staff=False).first()
            if not item:
                return _not_found("user")
            return JsonResponse({"ok": True, "data": {"id": item.id, "email": item.email, "first_name": item.first_name, "last_name": item.last_name, "is_active": item.is_active}})

        if action == "user_update":
            item = User.objects.filter(pk=payload.get("id"), is_staff=False).first()
            if not item:
                return _not_found("user")
            changed = []
            for key in ("first_name", "last_name", "is_active"):
                if key in payload:
                    setattr(item, key, payload[key])
                    changed.append(key)
            if changed:
                item.save(update_fields=changed)
            return JsonResponse({"ok": True})

        if action == "banners":
            rows = list(HeroSlide.objects.order_by("sort_order", "id").values("id", "title", "subtitle", "link", "is_active", "sort_order")[:100])
            return JsonResponse({"ok": True, "data": rows})

        if action == "banner_detail":
            item = HeroSlide.objects.filter(pk=payload.get("id")).first()
            if not item:
                return _not_found("banner")
            return JsonResponse({"ok": True, "data": {"id": item.id, "title": item.title, "subtitle": item.subtitle, "link": item.link, "is_active": item.is_active, "sort_order": item.sort_order}})

        if action == "banner_create":
            name, content = _image(payload)
            item = HeroSlide(title=str(payload.get("title") or "")[:150], subtitle=str(payload.get("subtitle") or "")[:240], link=str(payload.get("link") or "/products/")[:300])
            item.image.save(name, content, save=False)
            item.save()
            return JsonResponse({"ok": True, "data": {"id": item.id}})

        if action == "banner_update":
            item = HeroSlide.objects.filter(pk=payload.get("id")).first()
            if not item:
                return _not_found("banner")
            changed = []
            for key in ("title", "subtitle", "link", "is_active", "sort_order"):
                if key in payload:
                    setattr(item, key, payload[key])
                    changed.append(key)
            if changed:
                item.save(update_fields=changed)
            return JsonResponse({"ok": True})

        if action == "pages":
            rows = list(ContentPage.objects.order_by("footer_group", "sort_order", "id").values("id", "title", "footer_group", "is_active", "show_in_footer")[:100])
            return JsonResponse({"ok": True, "data": rows})

        if action == "page_detail":
            item = ContentPage.objects.filter(pk=payload.get("id")).first()
            if not item:
                return _not_found("page")
            return JsonResponse({"ok": True, "data": {"id": item.id, "title": item.title, "body": item.body, "footer_group": item.footer_group, "is_active": item.is_active, "show_in_footer": item.show_in_footer}})

        if action == "page_create":
            title = str(payload.get("title") or "").strip()
            if not title:
                return JsonResponse({"ok": False, "error": "title_required"}, status=400)
            group = str(payload.get("footer_group") or "guide")
            if group not in ("guide", "contact", "other"):
                group = "other"
            item = ContentPage.objects.create(title=title, body=str(payload.get("body") or ""), footer_group=group)
            return JsonResponse({"ok": True, "data": {"id": item.id}})

        if action == "page_update":
            item = ContentPage.objects.filter(pk=payload.get("id")).first()
            if not item:
                return _not_found("page")
            for key in ("title", "body", "footer_group", "is_active", "show_in_footer"):
                if key in payload:
                    setattr(item, key, payload[key])
            if "title" in payload:
                item.slug = ""
            item.save()
            return JsonResponse({"ok": True})

        if action == "socials":
            rows = list(SocialLink.objects.order_by("sort_order", "id").values("id", "title", "url", "is_active", "sort_order")[:100])
            return JsonResponse({"ok": True, "data": rows})

        if action == "social_detail":
            item = SocialLink.objects.filter(pk=payload.get("id")).first()
            if not item:
                return _not_found("social")
            return JsonResponse({"ok": True, "data": {"id": item.id, "title": item.title, "url": item.url, "is_active": item.is_active}})

        if action == "social_create":
            name, content = _image(payload)
            title = str(payload.get("title") or "").strip()
            url = str(payload.get("url") or "").strip()
            if not title or not url:
                return JsonResponse({"ok": False, "error": "title_and_url_required"}, status=400)
            item = SocialLink(title=title[:80], url=url[:500])
            item.image.save(name, content, save=False)
            item.save()
            return JsonResponse({"ok": True, "data": {"id": item.id}})

        if action == "social_update":
            item = SocialLink.objects.filter(pk=payload.get("id")).first()
            if not item:
                return _not_found("social")
            changed = []
            for key in ("title", "url", "is_active", "sort_order"):
                if key in payload:
                    setattr(item, key, payload[key])
                    changed.append(key)
            if changed:
                item.save(update_fields=changed)
            return JsonResponse({"ok": True})

        if action == "discounts":
            rows = list(DiscountCode.objects.order_by("-created_at").values("id", "code", "percent", "min_order_amount", "used_count", "max_uses", "is_active")[:100])
            return JsonResponse({"ok": True, "data": rows})

        if action == "discount_detail":
            item = DiscountCode.objects.filter(pk=payload.get("id")).first()
            if not item:
                return _not_found("discount")
            return JsonResponse({"ok": True, "data": {"id": item.id, "code": item.code, "percent": item.percent, "min_order_amount": item.min_order_amount, "used_count": item.used_count, "max_uses": item.max_uses, "is_active": item.is_active}})

        if action == "discount_create":
            code = str(payload.get("code") or "").strip().upper()
            percent = int(payload.get("percent") or 0)
            minimum = int(payload.get("min_order_amount") or 0)
            if not code or not 1 <= percent <= 99:
                return JsonResponse({"ok": False, "error": "invalid_discount"}, status=400)
            try:
                item = DiscountCode.objects.create(code=code, percent=percent, min_order_amount=max(0, minimum))
            except IntegrityError:
                return JsonResponse({"ok": False, "error": "discount_exists"}, status=409)
            return JsonResponse({"ok": True, "data": {"id": item.id}})

        if action == "discount_update":
            item = DiscountCode.objects.filter(pk=payload.get("id")).first()
            if not item:
                return _not_found("discount")
            changed = []
            for key in ("percent", "min_order_amount", "max_uses", "is_active"):
                if key in payload:
                    setattr(item, key, payload[key])
                    changed.append(key)
            if changed:
                item.save(update_fields=changed)
            return JsonResponse({"ok": True})

        if action == "settings_get":
            return JsonResponse({"ok": True, "data": {
                "site_name": store.site_name,
                "announcement": store.announcement,
                "shipping_fee": store.shipping_fee,
                "free_shipping_threshold": store.free_shipping_threshold,
                "card_number": store.card_number,
                "card_owner": store.card_owner,
                "payment_mode": store.payment_mode,
            }})

        if action == "settings_update":
            allowed = {"site_name", "announcement", "shipping_fee", "free_shipping_threshold", "card_number", "card_owner", "payment_mode"}
            changed = []
            for key, value in payload.items():
                if key in allowed:
                    setattr(store, key, value)
                    changed.append(key)
            if changed:
                store.save(update_fields=changed + ["updated_at"])
            return JsonResponse({"ok": True})

        if action == "events_poll":
            expire_reservations(limit=50)
            limit = min(max(int(payload.get("limit") or 20), 1), 50)
            rows = []
            for event in BotEvent.objects.filter(delivered_at__isnull=True).order_by("id")[:limit]:
                rows.append({"id": event.id, "kind": event.kind, "payload": event.payload, "created_at": event.created_at.isoformat()})
            return JsonResponse({"ok": True, "data": rows})

        if action == "events_ack":
            ids = payload.get("ids") or []
            ids = [int(x) for x in ids[:100] if str(x).isdigit()]
            if ids:
                BotEvent.objects.filter(id__in=ids, delivered_at__isnull=True).update(delivered_at=timezone.now())
            return JsonResponse({"ok": True})

        return JsonResponse({"ok": False, "error": "unknown_action"}, status=400)

    except (ValueError, TypeError) as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
