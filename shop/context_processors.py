from .models import Category, ContentPage, SiteSetting


def storefront(request):
    try:
        settings = SiteSetting.load()
        categories = Category.objects.filter(is_active=True, parent__isnull=True)[:8]
        footer_pages = ContentPage.objects.filter(is_active=True, show_in_footer=True)
    except Exception:
        settings, categories, footer_pages = None, [], []
    cart = request.session.get("cart", {}) if hasattr(request, "session") else {}
    return {"store_settings": settings, "nav_categories": categories, "footer_pages": footer_pages, "cart_count": sum(int(v) for v in cart.values())}

