import json
import os
import uuid

from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .models import Category, Product, SiteSetting
from .site_api import _image, api_auth
from .site_api_v9 import bot_api as v9_bot_api


def _body(request):
    try:
        return json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        return {}


def _fresh_image_name(prefix, requested):
    ext = os.path.splitext(os.path.basename(str(requested or "image.jpg")))[1].lower()
    if ext not in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}:
        ext = ".jpg"
    return f"{prefix}-{uuid.uuid4().hex}{ext}"


def _category_subtree_ids(root_id):
    found = []
    pending = [int(root_id)]
    while pending:
        batch = pending[:100]
        pending = pending[100:]
        for category_id in batch:
            if category_id not in found:
                found.append(category_id)
        children = list(Category.objects.filter(parent_id__in=batch).values_list("id", flat=True))
        pending.extend(category_id for category_id in children if category_id not in found)
    return found


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
        return JsonResponse({"ok": True, "site": {"name": store.site_name, "version": 10}})

    if action in {"category_image_set", "product_image_set"}:
        model = Category if action == "category_image_set" else Product
        item = model.objects.filter(pk=payload.get("id")).first()
        if not item:
            return JsonResponse({"ok": False, "error": "category_not_found" if model is Category else "product_not_found"}, status=404)
        try:
            requested, content = _image(payload)
        except (TypeError, ValueError) as exc:
            return JsonResponse({"ok": False, "error": str(exc)}, status=400)
        prefix = "category" if model is Category else "product"
        # Always create a new URL. The old file is removed after commit by media_hygiene.
        item.image.save(_fresh_image_name(prefix, requested), content, save=True)
        return JsonResponse({
            "ok": True,
            "data": {
                "id": item.id,
                "image_name": item.image.name,
                "image_url": item.image.url,
            },
        })

    if action == "category_delete":
        item = Category.objects.filter(pk=payload.get("id")).first()
        if not item:
            return JsonResponse({"ok": False, "error": "category_not_found"}, status=404)
        subtree_ids = _category_subtree_ids(item.id)
        product_count = Product.objects.filter(category_id__in=subtree_ids).count()
        preview = {
            "id": item.id,
            "name": item.name,
            "category_count": len(subtree_ids),
            "child_category_count": max(0, len(subtree_ids) - 1),
            "product_count": product_count,
        }
        if not bool(payload.get("confirm")):
            return JsonResponse({"ok": True, "data": {**preview, "requires_confirmation": True}})

        with transaction.atomic():
            locked_categories = list(
                Category.objects.select_for_update().filter(pk__in=subtree_ids).values_list("id", flat=True)
            )
            if item.id not in locked_categories:
                return JsonResponse({"ok": False, "error": "category_not_found"}, status=404)
            locked_products = list(
                Product.objects.select_for_update().filter(category_id__in=locked_categories).values_list("id", flat=True)
            )
            if locked_products:
                Product.objects.filter(pk__in=locked_products).delete()
            # Products are gone, so Category's PROTECT relation can no longer block deletion.
            Category.objects.filter(pk__in=locked_categories).delete()

        return JsonResponse({"ok": True, "data": {**preview, "deleted": True}})

    return v9_bot_api(request)
