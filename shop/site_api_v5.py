import json

from django.contrib.auth import get_user_model
from django.db.models import Q, Sum
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .extra_models import CustomerProfile
from .models import ContentPage, Order, PaymentReceipt, Product, SiteSetting
from .services import expire_reservations, order_event_payload
from .site_api import _field_b64, api_auth
from .site_api_v4 import _settings_payload, bot_api as v4_bot_api

User = get_user_model()


def _body(request):
    try:
        return json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        return {}


def _sync_terms_page(text):
    ContentPage.objects.update_or_create(
        slug="terms",
        defaults={
            "title": "قوانین و مقررات",
            "body": text or "",
            "footer_group": "guide",
            "show_in_footer": False,
            "is_active": True,
            "sort_order": 0,
        },
    )


def _settings_data():
    store = SiteSetting.load()
    data = _settings_payload()
    data["terms_text"] = store.terms_text or ""
    data["has_terms"] = bool((store.terms_text or "").strip())
    return data


def _user_row(user):
    profile = CustomerProfile.ensure(user)
    return {
        "id": user.id,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "full_name": f"{user.first_name} {user.last_name}".strip(),
        "customer_code": profile.customer_code,
        "phone": profile.phone,
        "is_active": user.is_active,
        "date_joined": user.date_joined.isoformat() if user.date_joined else None,
        "order_count": user.orders.count(),
    }


def _user_detail(user):
    profile = CustomerProfile.ensure(user)
    orders = user.orders.prefetch_related("items").order_by("-created_at")
    paid_statuses = ["paid", "processing", "shipped", "delivered"]
    active_statuses = ["pending", "review", "rejected", "paid", "processing", "shipped"]
    recent = []
    for order in orders[:30]:
        recent.append({
            "id": order.id,
            "code": order.code,
            "status": order.status,
            "status_label": order.get_status_display(),
            "total": order.total,
            "payment_method": order.payment_method,
            "payment_method_label": order.get_payment_method_display(),
            "tracking_code": order.tracking_code,
            "created_at": order.created_at.isoformat() if order.created_at else None,
            "items_count": sum(item.quantity for item in order.items.all()),
        })
    return {
        "id": user.id,
        "email": user.email,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "full_name": f"{user.first_name} {user.last_name}".strip(),
        "customer_code": profile.customer_code,
        "phone": profile.phone,
        "is_active": user.is_active,
        "date_joined": user.date_joined.isoformat() if user.date_joined else None,
        "last_login": user.last_login.isoformat() if user.last_login else None,
        "order_count": orders.count(),
        "active_orders": orders.filter(status__in=active_statuses).count(),
        "completed_orders": orders.filter(status="delivered").count(),
        "cancelled_orders": orders.filter(status="cancelled").count(),
        "total_spent": orders.filter(status__in=paid_statuses).aggregate(total=Sum("total"))["total"] or 0,
        "orders": recent,
    }


def _order_detail(order):
    receipt = PaymentReceipt.objects.filter(order=order).first()
    data = order_event_payload(order)
    data["id"] = order.id
    data["receipt_id"] = receipt.id if receipt else None
    data["receipt_status"] = receipt.status if receipt else None
    data["receipt_rejection_reason"] = order.receipt_rejection_reason
    data["reservation_active"] = order.reservation_active
    data["stock_committed"] = order.stock_committed
    if order.customer_id:
        profile = CustomerProfile.ensure(order.customer)
        data["customer_code"] = profile.customer_code
        data["customer_phone"] = profile.phone
        data["customer_user_id"] = order.customer_id
    else:
        data["customer_code"] = ""
        data["customer_phone"] = ""
        data["customer_user_id"] = None
    return data


@csrf_exempt
@api_auth
def bot_api(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "POST required"}, status=405)

    data = _body(request)
    action = data.get("action")
    payload = data.get("payload") or {}

    if action == "ping":
        store = SiteSetting.load()
        return JsonResponse({"ok": True, "site": {"name": store.site_name, "version": 5}})

    if action == "settings_get":
        return JsonResponse({"ok": True, "data": _settings_data()})

    if action == "settings_update":
        if "terms_text" in payload:
            store = SiteSetting.load()
            store.terms_text = str(payload.get("terms_text") or "").strip()
            store.save(update_fields=["terms_text", "updated_at"])
            _sync_terms_page(store.terms_text)
        response = v4_bot_api(request)
        if response.status_code >= 400:
            return response
        return JsonResponse({"ok": True, "data": _settings_data()})

    if action == "order_detail":
        expire_reservations(limit=50)
        order = (
            Order.objects.select_related("customer")
            .prefetch_related("items__product")
            .filter(pk=payload.get("id"))
            .first()
        )
        if not order:
            return JsonResponse({"ok": False, "error": "order_not_found"}, status=404)
        return JsonResponse({"ok": True, "data": _order_detail(order)})

    if action == "product_image":
        product = Product.objects.filter(pk=payload.get("id")).first()
        if not product:
            return JsonResponse({"ok": False, "error": "product_not_found"}, status=404)
        if not product.image:
            return JsonResponse({"ok": False, "error": "image_not_found"}, status=404)
        try:
            encoded = _field_b64(product.image)
        except ValueError as exc:
            return JsonResponse({"ok": False, "error": str(exc)}, status=400)
        return JsonResponse({
            "ok": True,
            "data": {
                "image_b64": encoded,
                "filename": product.image.name.rsplit("/", 1)[-1] or "product.jpg",
                "name": product.name,
                "sku": product.sku,
            },
        })

    if action in ("users", "user_search"):
        query = str(payload.get("query") or "").strip()
        users = User.objects.filter(is_staff=False).order_by("-date_joined")
        if query:
            users = users.filter(
                Q(email__icontains=query)
                | Q(first_name__icontains=query)
                | Q(last_name__icontains=query)
                | Q(customer_profile__customer_code__iexact=query)
                | Q(customer_profile__phone__icontains=query)
            ).distinct()
        rows = [_user_row(user) for user in users[:50]]
        return JsonResponse({"ok": True, "data": rows, "query": query})

    if action == "user_detail":
        user = User.objects.filter(pk=payload.get("id"), is_staff=False).first()
        if not user:
            return JsonResponse({"ok": False, "error": "user_not_found"}, status=404)
        return JsonResponse({"ok": True, "data": _user_detail(user)})

    return v4_bot_api(request)
