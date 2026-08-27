from django import template

from shop.pricing import effective_price as get_effective_price, promotion_label as get_promotion_label

register = template.Library()


@register.filter
def money(value):
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return value


@register.filter
def effective_price(product):
    try:
        return get_effective_price(product)
    except Exception:
        return getattr(product, "price", 0)


@register.filter
def promotion_label(product):
    try:
        return get_promotion_label(product)
    except Exception:
        return ""
