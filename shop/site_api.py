import json
import os
import secrets
from functools import wraps

from django.contrib.auth import get_user_model
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .models import Category, Order, Product, SiteSetting
from .services import set_order_status

User = get_user_model()


def _json(request):
    try:
        return json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        return {}


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


@csrf_exempt
@api_auth
def bot_api(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "POST required"}, status=405)
    data = _json(request)
    action = data.get("action")
    payload = data.get("payload") or {}
    store = SiteSetting.load()

    if action == "ping":
        return JsonResponse({"ok": True, "site": {"name": store.site_name, "domain": os.environ.get("DOMAIN", "")}})

    if action == "dashboard":
        return JsonResponse({"ok": True, "data": {
            "site_name": store.site_name,
            "products": Product.objects.filter(is_active=True).count(),
            "orders": Order.objects.count(),
            "pending_orders": Order.objects.filter(status__in=["pending", "review"]).count(),
            "users": User.objects.filter(is_staff=False).count(),
        }})

    if action == "categories":
        rows = list(Category.objects.order_by("sort_order", "name").values("id", "name", "is_active", "parent_id")[:100])
        return JsonResponse({"ok": True, "data": rows})

    if action == "products":
        rows = list(Product.objects.select_related("category").order_by("-created_at").values("id", "name", "sku", "price", "stock", "is_active", "is_amazing", "category__name")[:100])
        return JsonResponse({"ok": True, "data": rows})

    if action == "product_update":
        p = Product.objects.filter(pk=payload.get("id")).first()
        if not p:
            return JsonResponse({"ok": False, "error": "product_not_found"}, status=404)
        allowed = {"price", "compare_at_price", "stock", "is_active", "is_amazing", "name"}
        changed = []
        for key, value in payload.items():
            if key in allowed:
                setattr(p, key, value)
                changed.append(key)
        if changed:
            p.save()
        return JsonResponse({"ok": True})

    if action == "orders":
        rows = list(Order.objects.order_by("-created_at").values("id", "code", "full_name", "mobile", "total", "status", "tracking_code", "created_at")[:100])
        for row in rows:
            if row.get("created_at"):
                row["created_at"] = row["created_at"].isoformat()
        return JsonResponse({"ok": True, "data": rows})

    if action == "order_update":
        order = Order.objects.filter(pk=payload.get("id")).first()
        if not order:
            return JsonResponse({"ok": False, "error": "order_not_found"}, status=404)
        status = payload.get("status")
        tracking = str(payload.get("tracking_code") or "").strip()
        if status not in dict(Order.STATUS):
            return JsonResponse({"ok": False, "error": "invalid_status"}, status=400)
        set_order_status(order, status, payload.get("note", "Updated from Telegram manager"), tracking_code=tracking or None)
        return JsonResponse({"ok": True})

    if action == "users":
        rows = list(User.objects.filter(is_staff=False).order_by("-date_joined").values("id", "email", "first_name", "last_name", "is_active", "date_joined")[:100])
        for row in rows:
            if row.get("date_joined"):
                row["date_joined"] = row["date_joined"].isoformat()
        return JsonResponse({"ok": True, "data": rows})

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

    return JsonResponse({"ok": False, "error": "unknown_action"}, status=400)
