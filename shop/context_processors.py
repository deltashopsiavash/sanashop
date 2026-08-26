from django.utils import timezone

from .extra_models import FooterSetting, FooterSocial, ProductStory, TrustBadge
from .models import Category, SiteSetting


def storefront(request):
    try:
        settings = SiteSetting.load()
        categories = Category.objects.filter(is_active=True, parent__isnull=True)[:8]
        footer_settings = FooterSetting.load()
        footer_socials = FooterSocial.objects.filter(is_active=True)[:12]
        trust_badge = TrustBadge.load()
        active_stories = ProductStory.objects.filter(is_active=True, expires_at__gt=timezone.now()).order_by("sort_order", "-id")[:24]
    except Exception:
        settings, categories = None, []
        footer_settings, footer_socials, trust_badge, active_stories = None, [], None, []
    cart = request.session.get("cart", {}) if hasattr(request, "session") else {}
    return {
        "store_settings": settings,
        "nav_categories": categories,
        "footer_settings": footer_settings,
        "footer_socials": footer_socials,
        "trust_badge": trust_badge,
        "active_stories": active_stories,
        "cart_count": sum(int(v) for v in cart.values()),
    }
