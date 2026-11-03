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
    # Footer phone is managed from Telegram; SiteSetting.phone was used by
    # the header/contact modal. Use one consistent visible number everywhere.
    contact_phone = (
        (footer_settings.phone or "").strip() if footer_settings else ""
    ) or ((settings.phone or "").strip() if settings else "")
    cart = request.session.get("cart", {}) if hasattr(request, "session") else {}
    return {
        "store_settings": settings,
        "nav_categories": categories,
        "footer_settings": footer_settings,
        "contact_phone": contact_phone,
        "footer_socials": footer_socials,
        "trust_badge": trust_badge,
        "active_stories": active_stories,
        "cart_count": sum(int(v) for v in cart.values()),
    }
