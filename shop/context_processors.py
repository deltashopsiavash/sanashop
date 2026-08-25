from .models import Category, ContentPage, SiteSetting, SocialLink


def storefront(request):
    try:
        settings = SiteSetting.load()
        categories = Category.objects.filter(is_active=True, parent__isnull=True)[:8]
        footer_pages = ContentPage.objects.filter(is_active=True, show_in_footer=True)
        social_links = SocialLink.objects.filter(is_active=True)[:12]
    except Exception:
        settings, categories, footer_pages, social_links = None, [], [], []
    cart = request.session.get("cart", {}) if hasattr(request, "session") else {}
    return {
        "store_settings": settings,
        "nav_categories": categories,
        "footer_pages": footer_pages,
        "social_links": social_links,
        "cart_count": sum(int(v) for v in cart.values()),
    }
