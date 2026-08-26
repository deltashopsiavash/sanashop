import base64
import json
import os
from datetime import timedelta

from django.core.files.base import ContentFile
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from .extra_models import FooterSetting, FooterSocial, ProductStory, TrustBadge
from .models import HeroSlide, SiteSetting
from .site_api import api_auth, bot_api as legacy_bot_api

MAX_IMAGE_BYTES = 15 * 1024 * 1024
MAX_STORY_BYTES = 48 * 1024 * 1024


def _body(request):
    try:
        return json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        return {}


def _decode_file(payload, key="image_b64", max_bytes=MAX_IMAGE_BYTES, default_name="upload.jpg"):
    raw = payload.get(key) or ""
    if not raw:
        raise ValueError(f"{key}_required")
    try:
        decoded = base64.b64decode(raw, validate=True)
    except Exception as exc:
        raise ValueError("invalid_base64") from exc
    if not decoded or len(decoded) > max_bytes:
        raise ValueError("invalid_file_size")
    filename_key = key.replace("_b64", "_filename")
    name = str(payload.get(filename_key) or payload.get("filename") or default_name)
    name = os.path.basename(name).replace("/", "_")[-140:]
    return name, ContentFile(decoded)


def _settings_payload():
    store = SiteSetting.load()
    footer = FooterSetting.load()
    badge = TrustBadge.load()
    return {
        "site_name": store.site_name,
        "announcement": store.announcement,
        "shipping_fee": store.shipping_fee,
        "free_shipping_threshold": store.free_shipping_threshold,
        "card_number": store.card_number,
        "card_owner": store.card_owner,
        "payment_mode": store.payment_mode,
        "has_logo": bool(store.logo),
        "address": footer.address,
        "phone": footer.phone,
        "contact_email": footer.email,
        "footer_description": footer.description,
        "support_text": footer.support_text,
        "has_enamad_image": bool(badge.image),
        "enamad_url": badge.target_url,
    }


def _banner_data(item):
    return {
        "id": item.id,
        "title": item.title,
        "subtitle": item.subtitle,
        "link": item.link,
        "is_active": item.is_active,
        "sort_order": item.sort_order,
        "has_desktop_image": bool(item.image),
        "has_mobile_image": bool(item.mobile_image),
    }


def _social_data(item):
    return {
        "id": item.id,
        "platform": item.platform,
        "platform_label": item.get_platform_display(),
        "title": item.label,
        "url": item.url,
        "is_active": item.is_active,
        "sort_order": item.sort_order,
    }


def _story_data(item):
    return {
        "id": item.id,
        "title": item.title,
        "media_type": item.media_type,
        "target_url": item.target_url,
        "is_active": item.is_active,
        "active_now": item.active_now,
        "remaining_seconds": item.remaining_seconds,
        "expires_at": item.expires_at.isoformat(),
        "created_at": item.created_at.isoformat(),
    }


@csrf_exempt
@api_auth
def bot_api(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "POST required"}, status=405)

    data = _body(request)
    action = data.get("action")
    payload = data.get("payload") or {}

    try:
        if action == "settings_get":
            return JsonResponse({"ok": True, "data": _settings_payload()})

        if action == "settings_update":
            store = SiteSetting.load()
            footer = FooterSetting.load()
            store_allowed = {
                "site_name", "announcement", "shipping_fee", "free_shipping_threshold",
                "card_number", "card_owner", "payment_mode",
            }
            footer_map = {
                "address": "address",
                "phone": "phone",
                "contact_email": "email",
                "footer_description": "description",
                "support_text": "support_text",
            }
            store_changed = []
            footer_changed = []
            for key, value in payload.items():
                if key in store_allowed:
                    if key in ("shipping_fee", "free_shipping_threshold"):
                        value = max(0, int(value or 0))
                    setattr(store, key, value)
                    store_changed.append(key)
                elif key in footer_map:
                    field = footer_map[key]
                    setattr(footer, field, str(value or "").strip())
                    footer_changed.append(field)
            if store_changed:
                store.save(update_fields=list(dict.fromkeys(store_changed + ["updated_at"])))
            if footer_changed:
                footer.save(update_fields=list(dict.fromkeys(footer_changed + ["updated_at"])))
            return JsonResponse({"ok": True, "data": _settings_payload()})

        if action == "logo_set":
            store = SiteSetting.load()
            name, content = _decode_file(payload, "image_b64", MAX_IMAGE_BYTES, "logo.jpg")
            if store.logo:
                store.logo.delete(save=False)
            store.logo.save(name, content, save=True)
            return JsonResponse({"ok": True})

        if action == "logo_remove":
            store = SiteSetting.load()
            if store.logo:
                store.logo.delete(save=False)
                store.logo = ""
                store.save(update_fields=["logo", "updated_at"])
            return JsonResponse({"ok": True})

        if action == "banners":
            rows = [_banner_data(x) for x in HeroSlide.objects.order_by("sort_order", "id")[:100]]
            return JsonResponse({"ok": True, "data": rows})

        if action == "banner_detail":
            item = HeroSlide.objects.filter(pk=payload.get("id")).first()
            if not item:
                return JsonResponse({"ok": False, "error": "banner_not_found"}, status=404)
            return JsonResponse({"ok": True, "data": _banner_data(item)})

        if action == "banner_create":
            desktop_name, desktop = _decode_file(payload, "desktop_image_b64", MAX_IMAGE_BYTES, "banner-desktop.jpg")
            mobile_name, mobile = _decode_file(payload, "mobile_image_b64", MAX_IMAGE_BYTES, "banner-mobile.jpg")
            item = HeroSlide(
                title=str(payload.get("title") or "")[:150],
                subtitle=str(payload.get("subtitle") or "")[:240],
                link=str(payload.get("link") or "/products/")[:300],
            )
            item.image.save(desktop_name, desktop, save=False)
            item.mobile_image.save(mobile_name, mobile, save=False)
            item.save()
            return JsonResponse({"ok": True, "data": _banner_data(item)})

        if action == "banner_update":
            item = HeroSlide.objects.filter(pk=payload.get("id")).first()
            if not item:
                return JsonResponse({"ok": False, "error": "banner_not_found"}, status=404)
            for key in ("title", "subtitle", "link", "is_active", "sort_order"):
                if key in payload:
                    setattr(item, key, payload[key])
            item.save()
            return JsonResponse({"ok": True, "data": _banner_data(item)})

        if action == "banner_delete":
            item = HeroSlide.objects.filter(pk=payload.get("id")).first()
            if not item:
                return JsonResponse({"ok": False, "error": "banner_not_found"}, status=404)
            if item.image:
                item.image.delete(save=False)
            if item.mobile_image:
                item.mobile_image.delete(save=False)
            item.delete()
            return JsonResponse({"ok": True})

        if action == "socials":
            rows = [_social_data(x) for x in FooterSocial.objects.order_by("sort_order", "id")[:100]]
            return JsonResponse({"ok": True, "data": rows})

        if action == "social_detail":
            item = FooterSocial.objects.filter(pk=payload.get("id")).first()
            if not item:
                return JsonResponse({"ok": False, "error": "social_not_found"}, status=404)
            return JsonResponse({"ok": True, "data": _social_data(item)})

        if action == "social_create":
            platform = str(payload.get("platform") or "other")
            if platform not in dict(FooterSocial.PLATFORM_CHOICES):
                platform = "other"
            label = str(payload.get("title") or dict(FooterSocial.PLATFORM_CHOICES).get(platform) or "شبکه اجتماعی").strip()[:80]
            url = str(payload.get("url") or "").strip()
            if not url:
                return JsonResponse({"ok": False, "error": "url_required"}, status=400)
            item = FooterSocial.objects.create(platform=platform, label=label, url=url)
            return JsonResponse({"ok": True, "data": _social_data(item)})

        if action == "social_update":
            item = FooterSocial.objects.filter(pk=payload.get("id")).first()
            if not item:
                return JsonResponse({"ok": False, "error": "social_not_found"}, status=404)
            for key, field in (("platform", "platform"), ("title", "label"), ("url", "url"), ("is_active", "is_active"), ("sort_order", "sort_order")):
                if key in payload:
                    setattr(item, field, payload[key])
            item.save()
            return JsonResponse({"ok": True, "data": _social_data(item)})

        if action == "social_delete":
            deleted, _ = FooterSocial.objects.filter(pk=payload.get("id")).delete()
            if not deleted:
                return JsonResponse({"ok": False, "error": "social_not_found"}, status=404)
            return JsonResponse({"ok": True})

        if action == "enamad_set":
            badge = TrustBadge.load()
            name, content = _decode_file(payload, "image_b64", MAX_IMAGE_BYTES, "enamad.jpg")
            if badge.image:
                badge.image.delete(save=False)
            badge.image.save(name, content, save=False)
            badge.target_url = str(payload.get("target_url") or badge.target_url or "")[:500]
            badge.is_active = True
            badge.save()
            return JsonResponse({"ok": True})

        if action == "enamad_remove":
            badge = TrustBadge.load()
            if badge.image:
                badge.image.delete(save=False)
            badge.image = ""
            badge.save(update_fields=["image", "updated_at"])
            return JsonResponse({"ok": True})

        if action == "stories":
            rows = [_story_data(x) for x in ProductStory.objects.order_by("-created_at")[:100]]
            return JsonResponse({"ok": True, "data": rows})

        if action == "story_detail":
            item = ProductStory.objects.filter(pk=payload.get("id")).first()
            if not item:
                return JsonResponse({"ok": False, "error": "story_not_found"}, status=404)
            return JsonResponse({"ok": True, "data": _story_data(item)})

        if action == "story_create":
            title = str(payload.get("title") or "").strip()[:160]
            target_url = str(payload.get("target_url") or "").strip()[:500]
            hours = int(payload.get("duration_hours") or 0)
            media_type = str(payload.get("media_type") or "image")
            if not title or not target_url or hours <= 0 or media_type not in ("image", "video"):
                return JsonResponse({"ok": False, "error": "invalid_story"}, status=400)
            name, content = _decode_file(payload, "media_b64", MAX_STORY_BYTES, "story.mp4" if media_type == "video" else "story.jpg")
            item = ProductStory(
                title=title,
                media_type=media_type,
                target_url=target_url,
                expires_at=timezone.now() + timedelta(hours=min(hours, 24 * 30)),
                is_active=True,
            )
            item.media.save(name, content, save=False)
            item.save()
            return JsonResponse({"ok": True, "data": _story_data(item)})

        if action == "story_update":
            item = ProductStory.objects.filter(pk=payload.get("id")).first()
            if not item:
                return JsonResponse({"ok": False, "error": "story_not_found"}, status=404)
            if "title" in payload:
                item.title = str(payload.get("title") or "").strip()[:160]
            if "target_url" in payload:
                item.target_url = str(payload.get("target_url") or "").strip()[:500]
            if "is_active" in payload:
                item.is_active = bool(payload.get("is_active"))
            if "duration_hours" in payload:
                hours = max(1, min(int(payload.get("duration_hours") or 1), 24 * 30))
                item.expires_at = timezone.now() + timedelta(hours=hours)
            item.save()
            return JsonResponse({"ok": True, "data": _story_data(item)})

        if action == "story_media_set":
            item = ProductStory.objects.filter(pk=payload.get("id")).first()
            if not item:
                return JsonResponse({"ok": False, "error": "story_not_found"}, status=404)
            media_type = str(payload.get("media_type") or "image")
            if media_type not in ("image", "video"):
                return JsonResponse({"ok": False, "error": "invalid_media_type"}, status=400)
            name, content = _decode_file(payload, "media_b64", MAX_STORY_BYTES, "story.mp4" if media_type == "video" else "story.jpg")
            if item.media:
                item.media.delete(save=False)
            item.media_type = media_type
            item.media.save(name, content, save=False)
            item.save()
            return JsonResponse({"ok": True, "data": _story_data(item)})

        if action == "story_delete":
            item = ProductStory.objects.filter(pk=payload.get("id")).first()
            if not item:
                return JsonResponse({"ok": False, "error": "story_not_found"}, status=404)
            if item.media:
                item.media.delete(save=False)
            item.delete()
            return JsonResponse({"ok": True})

    except (ValueError, TypeError) as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)

    # All checkout/order/product/category/event actions remain on the proven v3 API.
    return legacy_bot_api(request)
