"""Authenticated per-site color management API for the multi-site bot."""
import re

from django.db import IntegrityError, transaction
from django.http import JsonResponse

from .models import Product, ProductColor

COLOR_ACTIONS = {
    "product_colors_list", "product_colors_add",
    "product_colors_update", "product_colors_delete",
}
MAX_COLORS_PER_PRODUCT = 30


def _row(color):
    return {
        "id": color.pk, "name": color.name, "hex_code": color.hex_code,
        "is_active": color.is_active, "sort_order": color.sort_order,
    }


def _error(message, status=400):
    return JsonResponse({"ok": False, "error": message}, status=status)


@transaction.atomic
def handle_product_colors(action, payload):
    if action not in COLOR_ACTIONS:
        return None
    try:
        pid = int(payload.get("id") or payload.get("product_id") or 0)
    except (TypeError, ValueError):
        return _error("invalid_product_id")
    product = Product.objects.select_for_update().filter(pk=pid).first()
    if not product:
        return _error("product_not_found", 404)

    if action == "product_colors_list":
        return JsonResponse({"ok": True, "data": {
            "product_id": product.pk, "product_name": product.name,
            "colors": [_row(c) for c in product.colors.all()],
        }})

    try:
        color_id = int(payload.get("color_id") or 0)
    except (TypeError, ValueError):
        return _error("invalid_color_id")
    color = ProductColor.objects.filter(product=product, pk=color_id).first() if color_id else None
    if action in {"product_colors_update", "product_colors_delete"} and not color:
        return _error("color_not_found", 404)

    if action == "product_colors_delete":
        color.delete()
        return JsonResponse({"ok": True, "data": {"deleted": color_id}})

    name = str(payload.get("name") or "").strip()
    hex_value = str(payload.get("hex_code") or "").strip()
    if name and len(name) > 60:
        return _error("نام رنگ بیشتر از ۶۰ حرف است.")
    if hex_value and not re.fullmatch(r"#[0-9A-Fa-f]{6}", hex_value):
        return _error("کد رنگ باید مثل #000000 باشد.")

    if action == "product_colors_add":
        if ProductColor.objects.filter(product=product).count() >= MAX_COLORS_PER_PRODUCT:
            return _error("حداکثر ۳۰ رنگ برای هر محصول مجاز است.")
        if not name:
            return _error("نام رنگ اجباری است.")
        if ProductColor.objects.filter(product=product, name__iexact=name).exists():
            return _error("رنگی با همین نام قبلاً ثبت شده است.")
        try:
            color = ProductColor.objects.create(
                product=product, name=name, hex_code=hex_value or "#808080",
                sort_order=ProductColor.objects.filter(product=product).count(),
            )
        except IntegrityError:
            return _error("رنگی با همین نام قبلاً ثبت شده است.")
    else:
        changes = []
        if "name" in payload:
            if not name:
                return _error("نام رنگ اجباری است.")
            if ProductColor.objects.filter(product=product, name__iexact=name).exclude(pk=color.pk).exists():
                return _error("رنگی با همین نام قبلاً ثبت شده است.")
            color.name = name
            changes.append("name")
        if "hex_code" in payload:
            if not hex_value:
                return _error("کد رنگ نمی‌تواند خالی باشد.")
            color.hex_code = hex_value
            changes.append("hex_code")
        if "is_active" in payload:
            color.is_active = payload.get("is_active") is True
            changes.append("is_active")
        if "sort_order" in payload:
            try:
                color.sort_order = max(0, int(payload["sort_order"]))
            except (TypeError, ValueError):
                return _error("ترتیب رنگ باید عدد باشد.")
            changes.append("sort_order")
        if changes:
            try:
                color.save(update_fields=changes)
            except IntegrityError:
                return _error("رنگی با همین نام قبلاً ثبت شده است.")
    return JsonResponse({"ok": True, "data": _row(color)})
