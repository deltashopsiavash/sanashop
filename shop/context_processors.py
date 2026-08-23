from .models import Category, SiteSetting


def storefront(request):
    try:
        settings = SiteSetting.load()
        categories = Category.objects.filter(is_active=True, parent__isnull=True)[:8]
    except Exception:
        settings, categories = None, []
    cart = request.session.get("cart", {}) if hasattr(request, "session") else {}
    return {"store_settings": settings, "nav_categories": categories, "cart_count": sum(int(v) for v in cart.values())}

