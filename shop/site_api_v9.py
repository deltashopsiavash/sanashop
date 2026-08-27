import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .models import Product, SiteSetting
from .pricing import normalize_promotions, promotion_data, promotion_for, set_amazing_price, set_discount_price
from .site_api import api_auth
from .site_api_v8 import bot_api as v8_bot_api


def _body(request):
    try:
        return json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        return {}


def _product_data(item):
    pricing = promotion_data(item)
    return {
        "id": item.id,
        "name": item.name,
        "sku": item.sku,
        "price": item.price,
        "base_price": pricing["base_price"],
        "discount_price": pricing["discount_price"],
        "amazing_price": pricing["amazing_price"],
        "effective_price": pricing["effective_price"],
        "promotion_label": pricing["promotion_label"],
        "discount_active": pricing["discount_active"],
        "amazing_active": pricing["amazing_active"],
        "compare_at_price": item.compare_at_price,
        "stock": item.stock,
        "reserved_stock": item.reserved_stock,
        "available_stock": item.available_stock,
        "is_active": item.is_active,
        "is_amazing": item.is_amazing,
        "amazing_until": item.amazing_until.isoformat() if item.amazing_until else None,
        "category_id": item.category_id,
        "category": item.category.name,
        "description": item.description,
        "has_image": bool(item.image),
    }


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
        return JsonResponse({"ok": True, "site": {"name": store.site_name, "version": 9}})

    if action == "products":
        rows = []
        items = Product.objects.select_related("category", "promotion").order_by("-created_at")[:100]
        for item in items:
            p = _product_data(item)
            rows.append({
                "id": p["id"],
                "name": p["name"],
                "sku": p["sku"],
                "price": p["price"],
                "base_price": p["base_price"],
                "discount_price": p["discount_price"],
                "amazing_price": p["amazing_price"],
                "effective_price": p["effective_price"],
                "promotion_label": p["promotion_label"],
                "stock": p["stock"],
                "reserved_stock": p["reserved_stock"],
                "is_active": p["is_active"],
                "is_amazing": p["is_amazing"],
                "category__name": p["category"],
            })
        return JsonResponse({"ok": True, "data": rows})

    if action == "product_detail":
        item = Product.objects.select_related("category", "promotion").filter(pk=payload.get("id")).first()
        if not item:
            return JsonResponse({"ok": False, "error": "product_not_found"}, status=404)
        return JsonResponse({"ok": True, "data": _product_data(item)})

    if action == "product_update":
        item = Product.objects.select_related("category", "promotion").filter(pk=payload.get("id")).first()
        if not item:
            return JsonResponse({"ok": False, "error": "product_not_found"}, status=404)
        try:
            if "price" in payload:
                value = int(payload.get("price") or 0)
                if value <= 0:
                    raise ValueError("قیمت اصلی باید بیشتر از صفر باشد.")
                item.price = value

            if "stock" in payload:
                item.stock = max(0, int(payload.get("stock") or 0))
            if "is_active" in payload:
                item.is_active = bool(payload.get("is_active"))
            if "name" in payload:
                item.name = str(payload.get("name") or "").strip()[:180]
                item.slug = ""
            if "description" in payload:
                item.description = str(payload.get("description") or "")

            item.save()

            if "discount_price" in payload:
                set_discount_price(item, payload.get("discount_price"))
            if "amazing_price" in payload:
                set_amazing_price(item, payload.get("amazing_price"))
            elif "is_amazing" in payload:
                if bool(payload.get("is_amazing")):
                    promo = promotion_for(item)
                    if not promo or not promo.amazing_price or int(promo.amazing_price) >= int(item.price):
                        raise ValueError("اول قیمت مخصوص شگفت‌انگیز را ثبت کنید.")
                    item.is_amazing = True
                    item.save(update_fields=["is_amazing", "updated_at"])
                else:
                    set_amazing_price(item, 0)

            normalize_promotions(item)
            item = Product.objects.select_related("category", "promotion").get(pk=item.pk)
            return JsonResponse({"ok": True, "data": _product_data(item)})
        except (TypeError, ValueError) as exc:
            return JsonResponse({"ok": False, "error": str(exc)}, status=400)

    return v8_bot_api(request)
