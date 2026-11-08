"""Authenticated per-site CRUD for numbered purchasable options."""
from django.db import transaction
from django.http import JsonResponse

from .models import Product, ProductOption

ACTIONS = {
    "product_options_list", "product_options_add",
    "product_options_update", "product_options_delete",
}
MAX_OPTIONS = 100


def _error(detail, status=400):
    return JsonResponse({"ok": False, "error": detail}, status=status)


def _row(option, parent_sku):
    return {
        "id": option.id, "number": option.number, "name": option.name,
        "label": option.label, "code": f"{parent_sku}-{option.number:02d}",
        "price": option.price, "is_available": option.is_available,
        "sort_order": option.sort_order,
    }


@transaction.atomic
def handle_product_options(action, payload):
    if action not in ACTIONS:
        return None
    try:
        product_id = int(payload.get("product_id") or payload.get("id") or 0)
    except (ValueError, TypeError):
        return _error("شناسه محصول نامعتبر است.")
    product = Product.objects.select_for_update().filter(pk=product_id).first()
    if not product:
        return _error("product_not_found", 404)

    if action == "product_options_list":
        return JsonResponse({"ok": True, "data": {
            "product_id": product.pk, "product_name": product.name,
            "product_sku": product.sku,
            "options": [_row(row, product.sku) for row in product.numbered_options.all()],
        }})

    try:
        option_id = int(payload.get("option_id") or 0)
    except (ValueError, TypeError):
        return _error("شناسه گزینه نامعتبر است.")
    option = ProductOption.objects.filter(product=product, pk=option_id).first() if option_id else None
    if action != "product_options_add" and option is None:
        return _error("option_not_found", 404)

    if action == "product_options_delete":
        option.delete()
        return JsonResponse({"ok": True, "data": {"deleted": option_id}})

    changes = {}
    if action == "product_options_add" or "number" in payload:
        try:
            number = int(payload.get("number") or 0)
        except (ValueError, TypeError):
            return _error("شماره گزینه معتبر نیست.")
        if number < 1 or number > 9999:
            return _error("شماره باید بین ۱ تا ۹۹۹۹ باشد.")
        others = ProductOption.objects.filter(product=product, number=number)
        if option:
            others = others.exclude(pk=option.pk)
        if others.exists():
            return _error("این شماره قبلاً برای همین محصول ثبت شده است.")
        changes["number"] = number

    if action == "product_options_add" or "price" in payload:
        try:
            price = int(payload.get("price") or 0)
        except (ValueError, TypeError):
            return _error("قیمت باید عدد باشد.")
        if price < 1:
            return _error("قیمت باید بیشتر از صفر تومان باشد.")
        changes["price"] = price

    if "name" in payload:
        name = str(payload.get("name") or "").strip()
        if len(name) > 120:
            return _error("عنوان بیش از ۱۲۰ حرف است.")
        changes["name"] = name

    if "is_available" in payload:
        value = payload["is_available"]
        if not isinstance(value, bool):
            return _error("وضعیت موجودی نامعتبر است.")
        changes["is_available"] = value

    if "sort_order" in payload:
        try:
            changes["sort_order"] = max(0, int(payload["sort_order"]))
        except (ValueError, TypeError):
            return _error("ترتیب باید عدد باشد.")

    if action == "product_options_add":
        if ProductOption.objects.filter(product=product).count() >= MAX_OPTIONS:
            return _error("حداکثر ۱۰۰ گزینه برای هر محصول مجاز است.")
        option = ProductOption.objects.create(product=product, **changes)
    else:
        for field, value in changes.items():
            setattr(option, field, value)
        if changes:
            option.save(update_fields=list(changes))
    return JsonResponse({"ok": True, "data": _row(option, product.sku)})
