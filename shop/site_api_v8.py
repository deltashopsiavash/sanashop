import base64
import json
import tempfile
from datetime import timedelta
from pathlib import Path

from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from .backup import create_backup_archive, restore_backup_archive, validate_backup_archive
from .models import SiteSetting
from .site_api import api_auth
from .site_api_v7 import bot_api as v7_bot_api

MAX_BOT_BACKUP_BYTES = 35 * 1024 * 1024


def _body(request):
    try:
        return json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        return {}


def _status_data():
    store = SiteSetting.load()
    interval = int(store.backup_interval_minutes or 0)
    last = store.last_backup_at
    due = False
    next_at = None
    if interval:
        if last:
            next_at = last + timedelta(minutes=interval)
            due = timezone.now() >= next_at
        else:
            due = True
    return {
        "interval_minutes": interval,
        "last_backup_at": last.isoformat() if last else None,
        "next_backup_at": next_at.isoformat() if next_at else None,
        "due": due,
        "max_bot_bytes": MAX_BOT_BACKUP_BYTES,
    }


def _make_backup(label):
    path = create_backup_archive(label)
    try:
        size = path.stat().st_size
        if size > MAX_BOT_BACKUP_BYTES:
            return None, {
                "filename": path.name,
                "size": size,
                "too_large": True,
                "message": "حجم بکاپ برای انتقال از ربات زیاد است؛ از بکاپ سروری استفاده کنید.",
            }
        raw = path.read_bytes()
        return raw, {
            "filename": path.name,
            "size": size,
            "too_large": False,
            "backup_b64": base64.b64encode(raw).decode("ascii"),
        }
    finally:
        path.unlink(missing_ok=True)


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
        return JsonResponse({"ok": True, "site": {"name": store.site_name, "version": 8}})

    if action == "backup_status":
        return JsonResponse({"ok": True, "data": _status_data()})

    if action == "backup_interval_set":
        try:
            minutes = int(payload.get("minutes") or 0)
        except (TypeError, ValueError):
            return JsonResponse({"ok": False, "error": "invalid_interval"}, status=400)
        if minutes != 0 and minutes < 5:
            return JsonResponse({"ok": False, "error": "minimum_interval_is_5"}, status=400)
        if minutes > 43200:
            return JsonResponse({"ok": False, "error": "interval_too_large"}, status=400)
        store = SiteSetting.load()
        store.backup_interval_minutes = minutes
        store.save(update_fields=["backup_interval_minutes", "updated_at"])
        return JsonResponse({"ok": True, "data": _status_data()})

    if action == "backup_create":
        label = str(payload.get("label") or "manual").strip()[:24]
        try:
            _, info = _make_backup(label)
        except Exception as exc:
            return JsonResponse({"ok": False, "error": "backup_failed", "detail": str(exc)}, status=500)
        if info.get("too_large"):
            return JsonResponse({"ok": False, "error": "backup_too_large", "data": info}, status=413)
        return JsonResponse({"ok": True, "data": info})

    if action == "backup_touch":
        store = SiteSetting.load()
        store.last_backup_at = timezone.now()
        store.save(update_fields=["last_backup_at", "updated_at"])
        return JsonResponse({"ok": True, "data": _status_data()})

    if action == "backup_restore":
        encoded = str(payload.get("backup_b64") or "")
        filename = str(payload.get("filename") or "restore.sanabackup")
        if not filename.lower().endswith(".sanabackup"):
            return JsonResponse({"ok": False, "error": "invalid_backup_filename"}, status=400)
        try:
            raw = base64.b64decode(encoded, validate=True)
        except Exception:
            return JsonResponse({"ok": False, "error": "invalid_backup_base64"}, status=400)
        if not raw or len(raw) > MAX_BOT_BACKUP_BYTES:
            return JsonResponse({"ok": False, "error": "invalid_backup_size"}, status=413)

        handle = tempfile.NamedTemporaryFile(suffix=".sanabackup", delete=False)
        path = Path(handle.name)
        try:
            handle.write(raw)
            handle.close()
            manifest = validate_backup_archive(path)
            emergency = restore_backup_archive(path)
            emergency_name = emergency.name if emergency else None
            if emergency:
                emergency.unlink(missing_ok=True)
            return JsonResponse({
                "ok": True,
                "data": {
                    "created_at": manifest.get("created_at"),
                    "emergency_backup": emergency_name,
                },
            })
        except Exception as exc:
            return JsonResponse({"ok": False, "error": "restore_failed", "detail": str(exc)}, status=400)
        finally:
            try:
                handle.close()
            except Exception:
                pass
            path.unlink(missing_ok=True)

    return v7_bot_api(request)
