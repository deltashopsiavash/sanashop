"""Admin API for the existing public FAQ page.

The callback is already protected by the site's unique bearer API key.
Never write the bot FAQ into a global multi-site database.
"""
from django.http import JsonResponse

from .models import ContentPage


def faq_action(action, payload):
    if action not in ("faq_get", "faq_set"):
        return None
    page = ContentPage.objects.filter(slug="faq").first()
    if action == "faq_get":
        return JsonResponse({"ok": True, "data": {
            "title": page.title if page else "سؤالات متداول",
            "body": page.body if page else "",
            "is_active": page.is_active if page else False,
            "url": "/page/faq/",
        }})
    body = payload.get("body")
    if not isinstance(body, str) or not body.strip() or len(body) > 20000:
        return JsonResponse({"ok": False, "error": "متن سوالات متداول باید بین ۱ تا ۲۰۰۰۰ حرف باشد."}, status=400)
    title = str(payload.get("title") or "سؤالات متداول").strip()[:120]
    if not title:
        title = "سؤالات متداول"
    page, _ = ContentPage.objects.update_or_create(
        slug="faq",
        defaults={
            "title": title,
            "body": body.strip(),
            "footer_group": "guide",
            "show_in_footer": True,
            "is_active": True,
        },
    )
    return JsonResponse({"ok": True, "data": {
        "title": page.title, "body": page.body,
        "url": "/page/faq/", "is_active": page.is_active,
    }})
