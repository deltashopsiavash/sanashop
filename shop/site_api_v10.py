import json
import os
import uuid

from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .extra_models import ProductStory, TrustBadge
from .models import Category, Product, SiteSetting
from .site_api import _image, api_auth
from .site_api_v4 import MAX_IMAGE_BYTES, MAX_STORY_BYTES, _decode_file
from .site_api_v9 import bot_api as v9_bot_api


def _body(request):
    try:
        return json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        return {}


def _fresh_name(prefix, requested, allowed=None, default_ext=".jpg"):
    allowed = allowed or {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}
    ext = os.path.splitext(os.path.basename(str(requested or ("file" + default_ext))))[1].lower()
    if ext not in allowed:
        ext = default_ext
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
        # Always create a new URL. media_hygiene removes the previous file after commit.
        item.image.save(_fresh_name(prefix, requested), content, save=True)
        return JsonResponse({"ok": True, "data": {"id": item.id, "image_name": item.image.name, "image_url": item.image.url}})

    if action == "logo_set":
        store = SiteSetting.load()
        try:
            requested, content = _decode_file(payload, "image_b64", MAX_IMAGE_BYTES, "logo.jpg")
        except (TypeError, ValueError) as exc:
            return JsonResponse({"ok": False, "error": str(exc)}, status=400)
        store.logo.save(_fresh_name("logo", requested), content, save=True)
        return JsonResponse({"ok": True, "data": {"image_name": store.logo.name, "image_url": store.logo.url}})

    if action == "enamad_set":
        badge = TrustBadge.load()
        try:
            requested, content = _decode_file(payload, "image_b64", MAX_IMAGE_BYTES, "enamad.jpg")
        except (TypeError, ValueError) as exc:
            return JsonResponse({"ok": False, "error": str(exc)}, status=400)
        badge.image.save(_fresh_name("enamad", requested), content, save=False)
        badge.target_url = str(payload.get("target_url") or badge.target_url or "")[:500]
        badge.is_active = True
        badge.save()
        return JsonResponse({"ok": True, "data": {"image_name": badge.image.name, "image_url": badge.image.url}})

    if action == "story_media_set":
        item = ProductStory.objects.filter(pk=payload.get("id")).first()
        if not item:
            return JsonResponse({"ok": False, "error": "story_not_found"}, status=404)
        media_type = str(payload.get("media_type") or "image")
        if media_type not in ("image", "video"):
            return JsonResponse({"ok": False, "error": "invalid_media_type"}, status=400)
        try:
            requested, content = _decode_file(
                payload,
                "media_b64",
                MAX_STORY_BYTES,
                "story.mp4" if media_type == "video" else "story.jpg",
            )
        except (TypeError, ValueError) as exc:
            return JsonResponse({"ok": False, "error": str(exc)}, status=400)
        if media_type == "video":
            fresh = _fresh_name("story", requested, {".mp4", ".webm", ".mov", ".m4v"}, ".mp4")
        else:
            fresh = _fresh_name("story", requested)
        item.media_type = media_type
        item.media.save(fresh, content, save=False)
        item.save()
        return JsonResponse({"ok": True, "data": {"id": item.id, "media_name": item.media.name, "media_url": item.media.url}})

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
            locked_categories = list(Category.objects.select_for_update().filter(pk__in=subtree_ids).values_list("id", flat=True))
            if item.id not in locked_categories:
                return JsonResponse({"ok": False, "error": "category_not_found"}, status=404)
            locked_products = list(Product.objects.select_for_update().filter(category_id__in=locked_categories).values_list("id", flat=True))
            if locked_products:
                Product.objects.filter(pk__in=locked_products).delete()
            # Products are gone, so Category's PROTECT relation can no longer block deletion.
            Category.objects.filter(pk__in=locked_categories).delete()

        return JsonResponse({"ok": True, "data": {**preview, "deleted": True}})

    return v9_bot_api(request)
