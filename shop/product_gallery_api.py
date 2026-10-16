"""Authenticated gallery operations for the remote SanaShop Telegram bot.

Product.image is the primary storefront photo; ProductImage rows are additional
ordered photos. Keeping these existing models preserves older products/backups.
"""
import base64
import io
import uuid

from PIL import Image, UnidentifiedImageError
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Max
from django.http import JsonResponse
from django.utils import timezone

from .models import Product, ProductImage

MAX_PHOTOS = 20
MAX_IMAGE_BYTES = 10 * 1024 * 1024
ACCEPTED = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp", "GIF": ".gif"}
ACTIONS = {
    "product_gallery_list", "product_gallery_get", "product_gallery_add",
    "product_gallery_replace", "product_gallery_delete",
    "product_gallery_primary", "product_gallery_move", "product_gallery_alt",
}


def _error(message, status=400):
    return JsonResponse({"ok": False, "error": message}, status=status)


def _photos(product):
    rows = []
    if product.image:
        rows.append({
            "id": 0, "is_primary": True, "url": product.image.url,
            "alt": product.name, "position": 1,
        })
    for row in product.gallery.order_by("sort_order", "id"):
        if row.image:
            rows.append({
                "id": row.pk, "is_primary": False, "url": row.image.url,
                "alt": row.alt or product.name, "position": len(rows) + 1,
            })
    return rows


def _uploaded_image(payload):
    encoded = payload.get("image_b64")
    if not isinstance(encoded, str) or not encoded:
        raise ValueError("image_required")
    if len(encoded) > (MAX_IMAGE_BYTES * 4 // 3 + 16):
        raise ValueError("image_too_large")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise ValueError("invalid_base64") from exc
    if not raw or len(raw) > MAX_IMAGE_BYTES:
        raise ValueError("image_too_large")
    try:
        with Image.open(io.BytesIO(raw)) as image:
            kind = image.format
            width, height = image.size
            if kind not in ACCEPTED or not (0 < width <= 10000 and 0 < height <= 10000):
                raise ValueError("unsupported_image")
            if width * height > 30_000_000:
                raise ValueError("image_dimensions_too_large")
            image.verify()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("invalid_image_file") from exc
    return f"gallery-{uuid.uuid4().hex}{ACCEPTED[kind]}", ContentFile(raw)


def _select_image(product, image_id):
    try:
        image_id = int(image_id)
    except (ValueError, TypeError):
        raise ValueError("invalid_image_id")
    if image_id < 0:
        raise ValueError("invalid_image_id")
    if image_id == 0:
        if not product.image:
            raise ValueError("image_not_found")
        return product.image, None
    row = ProductImage.objects.filter(product_id=product.pk, pk=image_id).first()
    if not row or not row.image:
        raise ValueError("image_not_found")
    return row.image, row


def _reindex(product):
    rows = list(ProductImage.objects.filter(product_id=product.pk).order_by("sort_order", "id"))
    for index, row in enumerate(rows, 1):
        if row.sort_order != index:
            ProductImage.objects.filter(pk=row.pk).update(sort_order=index)


def handle_gallery_action(action, payload):
    if action not in ACTIONS:
        return None
    if not isinstance(payload, dict):
        return _error("invalid_payload")
    try:
        product_id = int(payload.get("id"))
    except (ValueError, TypeError):
        return _error("invalid_product_id")
    if product_id <= 0:
        return _error("invalid_product_id")
    if action in {"product_gallery_list", "product_gallery_get"}:
        product = Product.objects.filter(pk=product_id).first()
        if not product:
            return _error("product_not_found", 404)
        if action == "product_gallery_list":
            photos = _photos(product)
            return JsonResponse({"ok": True, "data": {
                "product_id": product.pk, "name": product.name,
                "max_photos": MAX_PHOTOS, "photos": photos, "count": len(photos),
            }})
        try:
            field, _ = _select_image(product, payload.get("image_id"))
            with field.open("rb") as handle:
                raw = handle.read(MAX_IMAGE_BYTES + 1)
            if len(raw) > MAX_IMAGE_BYTES:
                return _error("image_too_large")
        except ValueError as exc:
            return _error(str(exc), 404 if str(exc) == "image_not_found" else 400)
        return JsonResponse({"ok": True, "data": {
            "image_b64": base64.b64encode(raw).decode("ascii"),
            "filename": field.name.rsplit("/", 1)[-1],
        }})

    try:
        with transaction.atomic():
            product = Product.objects.select_for_update().filter(pk=product_id).first()
            if product is None:
                return _error("product_not_found", 404)

            if action == "product_gallery_add":
                count = ProductImage.objects.filter(product_id=product.pk).count() + bool(product.image)
                if count >= MAX_PHOTOS:
                    return _error("gallery_full")
                name, content = _uploaded_image(payload)
                if not product.image:
                    product.image.save(name, content, save=True)
                    image_id = 0
                else:
                    next_order = (ProductImage.objects.filter(product=product).aggregate(
                        highest=Max("sort_order"))["highest"] or 0) + 1
                    row = ProductImage(product=product, sort_order=next_order)
                    row.image.save(name, content, save=True)
                    image_id = row.pk
                return JsonResponse({"ok": True, "data": {
                    "image_id": image_id, "photos": _photos(product),
                }})

            field, row = _select_image(product, payload.get("image_id"))

            if action == "product_gallery_replace":
                name, content = _uploaded_image(payload)
                # A fresh unique name triggers post-commit media cleanup of the old file.
                field.save(name, content, save=True)
            elif action == "product_gallery_delete":
                if row is None:
                    # If the primary image is removed, the first secondary becomes primary.
                    promoted = ProductImage.objects.filter(product_id=product.pk).order_by(
                        "sort_order", "id").first()
                    if promoted:
                        new_name = promoted.image.name
                        # Bypass pre_save's file cleanup because this file is being moved.
                        ProductImage.objects.filter(pk=promoted.pk).update(image="")
                        promoted.delete()
                        product.image = new_name
                    else:
                        product.image = ""
                    product.save(update_fields=["image", "updated_at"])
                else:
                    row.delete()  # Signal deletes its actual file after commit.
                _reindex(product)
            elif action == "product_gallery_primary":
                if row is None:
                    return _error("already_primary")
                old_name = product.image.name if product.image else ""
                new_name = row.image.name
                # Swap references without deleting either existing file.
                Product.objects.filter(pk=product.pk).update(
                    image=new_name, updated_at=timezone.now())
                if old_name:
                    ProductImage.objects.filter(pk=row.pk).update(image=old_name)
                else:
                    ProductImage.objects.filter(pk=row.pk).update(image="")
                    row.delete()
                product.image.name = new_name
                _reindex(product)
            elif action == "product_gallery_move":
                if row is None:
                    return _error("primary_cannot_move")
                direction = str(payload.get("direction", ""))
                if direction not in {"up", "down"}:
                    return _error("invalid_direction")
                ordered = list(ProductImage.objects.filter(product_id=product.pk).order_by(
                    "sort_order", "id"))
                ids = [item.pk for item in ordered]
                current = ids.index(row.pk)
                target = current - 1 if direction == "up" else current + 1
                if target < 0 or target >= len(ids):
                    return _error("cannot_move")
                ids[current], ids[target] = ids[target], ids[current]
                for pos, pk in enumerate(ids, 1):
                    ProductImage.objects.filter(pk=pk).update(sort_order=pos)
            elif action == "product_gallery_alt":
                if row is None:
                    return _error("primary_alt_is_product_name")
                alt = str(payload.get("alt", "")).strip()
                if len(alt) > 180:
                    return _error("alt_too_long")
                row.alt = alt
                row.save(update_fields=["alt"])

            return JsonResponse({"ok": True, "data": {
                "photos": _photos(product), "count": len(_photos(product)),
            }})
    except ValueError as exc:
        return _error(str(exc), 404 if str(exc) == "image_not_found" else 400)
