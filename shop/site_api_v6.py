import json
import re

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .emailing import send_broadcast_email, send_password_reset_email
from .extra_models import CustomerProfile
from .forms import normalize_mobile
from .models import SiteSetting
from .site_api import api_auth
from .site_api_v5 import bot_api as v5_bot_api

User = get_user_model()


def _body(request):
    try:
        return json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        return {}


def _user_payload(user):
    profile = CustomerProfile.ensure(user)
    return {
        "id": user.id,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "customer_code": profile.customer_code,
        "phone": profile.phone,
        "is_active": user.is_active,
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
        return JsonResponse({"ok": True, "site": {"name": store.site_name, "version": 6}})

    if action == "user_update":
        user = User.objects.filter(pk=payload.get("id"), is_staff=False).first()
        if not user:
            return JsonResponse({"ok": False, "error": "user_not_found"}, status=404)
        profile = CustomerProfile.ensure(user)
        changed = []

        if "email" in payload:
            email = str(payload.get("email") or "").strip().lower()
            try:
                validate_email(email)
            except ValidationError:
                return JsonResponse({"ok": False, "error": "invalid_email"}, status=400)
            duplicate = User.objects.filter(email__iexact=email).exclude(pk=user.pk).exists() or User.objects.filter(username__iexact=email).exclude(pk=user.pk).exists()
            if duplicate:
                return JsonResponse({"ok": False, "error": "email_exists"}, status=409)
            user.email = email
            user.username = email
            changed += ["email", "username"]

        if "first_name" in payload:
            user.first_name = str(payload.get("first_name") or "").strip()[:150]
            changed.append("first_name")
        if "last_name" in payload:
            user.last_name = str(payload.get("last_name") or "").strip()[:150]
            changed.append("last_name")
        if "is_active" in payload:
            user.is_active = bool(payload.get("is_active"))
            changed.append("is_active")
        if changed:
            user.save(update_fields=list(dict.fromkeys(changed)))

        if "phone" in payload:
            phone = normalize_mobile(payload.get("phone"))
            if not re.fullmatch(r"09\d{9}", phone):
                return JsonResponse({"ok": False, "error": "invalid_phone"}, status=400)
            if CustomerProfile.objects.filter(phone=phone).exclude(user=user).exists():
                return JsonResponse({"ok": False, "error": "phone_exists"}, status=409)
            profile.phone = phone
            profile.save(update_fields=["phone", "updated_at"])

        return JsonResponse({"ok": True, "data": _user_payload(user)})

    if action == "user_password_reset":
        user = User.objects.filter(pk=payload.get("id"), is_staff=False).first()
        if not user:
            return JsonResponse({"ok": False, "error": "user_not_found"}, status=404)
        if not user.email:
            return JsonResponse({"ok": False, "error": "email_missing"}, status=400)
        try:
            send_password_reset_email(request, user)
        except Exception:
            return JsonResponse({"ok": False, "error": "email_send_failed"}, status=502)
        return JsonResponse({"ok": True, "data": {"email": user.email}})

    if action == "broadcast_email":
        subject = str(payload.get("subject") or "").strip()
        body = str(payload.get("body") or "").strip()
        if len(subject) < 2 or len(subject) > 180:
            return JsonResponse({"ok": False, "error": "invalid_subject"}, status=400)
        if len(body) < 2 or len(body) > 20000:
            return JsonResponse({"ok": False, "error": "invalid_body"}, status=400)
        recipients = list(
            User.objects.filter(is_staff=False, is_active=True)
            .exclude(email="")
            .values_list("email", flat=True)
        )
        try:
            sent = send_broadcast_email(subject, body, recipients)
        except Exception:
            return JsonResponse({"ok": False, "error": "email_send_failed"}, status=502)
        return JsonResponse({"ok": True, "data": {"recipients": len(recipients), "sent": sent}})

    return v5_bot_api(request)
