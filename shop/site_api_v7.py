import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .models import SiteSetting
from .extra_models import FooterSetting
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
    phone = (FooterSetting.load().phone or "").strip() or (store.phone or "").strip()
    data["contact_phone"] = phone
    data["has_contact_phone"] = bool(phone)
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

    if action == "settings_update" and ("contact_phone" in payload or "phone" in payload):
        # v4 stores "phone" in FooterSetting while v7 stores "contact_phone"
        # in SiteSetting; sync both after the existing handler succeeds.
        response = v6_bot_api(request)
        if response.status_code >= 400:
            return response
        phone = str(payload.get("contact_phone") if "contact_phone" in payload else payload.get("phone") or "").strip()[:30]
        store = SiteSetting.load()
        footer = FooterSetting.load()
        store.phone = phone
        footer.phone = phone
        store.save(update_fields=["phone", "updated_at"])
        footer.save(update_fields=["phone", "updated_at"])
        return JsonResponse({"ok": True, "data": _settings_data()})

    return v6_bot_api(request)
