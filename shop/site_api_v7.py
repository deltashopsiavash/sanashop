import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .models import SiteSetting
from .site_api import api_auth
from .site_api_v5 import _settings_data as v5_settings_data
from .site_api_v6 import bot_api as v6_bot_api


def _body(request):
    try:
        return json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        return {}


def _settings_data():
    data = v5_settings_data()
    store = SiteSetting.load()
    data["contact_phone"] = store.phone or ""
    data["has_contact_phone"] = bool((store.phone or "").strip())
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
        return JsonResponse({"ok": True, "site": {"name": store.site_name, "version": 7}})

    if action == "settings_get":
        return JsonResponse({"ok": True, "data": _settings_data()})

    if action == "settings_update" and "contact_phone" in payload:
        phone = str(payload.get("contact_phone") or "").strip()[:30]
        store = SiteSetting.load()
        store.phone = phone
        store.save(update_fields=["phone", "updated_at"])
        # Keep all older settings fields working in the same request.
        response = v6_bot_api(request)
        if response.status_code >= 400:
            return response
        return JsonResponse({"ok": True, "data": _settings_data()})

    return v6_bot_api(request)
