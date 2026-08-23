from pathlib import Path

from django.conf import settings
from django.http import HttpResponse


class RestoreMaintenanceMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.marker = Path(settings.MEDIA_ROOT) / ".restore-in-progress"

    def __call__(self, request):
        if self.marker.exists() and request.path != "/health/":
            return HttpResponse("سامانه در حال بازگردانی نسخه پشتیبان است؛ چند دقیقه دیگر تلاش کنید.", status=503, content_type="text/plain; charset=utf-8")
        return self.get_response(request)
