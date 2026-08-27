from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone

from .extra_models import ProductPromotion


def promotion_for(product, create=False):
    try:
        return product.promotion
    except ObjectDoesNotExist:
        if create:
            return ProductPromotion.objects.create(product=product)
        return None


def _valid_special(value, base_price):
    try:
        value = int(value or 0)
        base_price = int(base_price or 0)
    except (TypeError, ValueError):
        return False
    return 0 < value < base_price


def amazing_active(product, promo=None, now=None):
    promo = promo if promo is not None else promotion_for(product)
    if not promo or not product.is_amazing or not _valid_special(promo.amazing_price, product.price):
        return False
    now = now or timezone.now()
    return not product.amazing_until or product.amazing_until > now


def discount_active(product, promo=None):
    promo = promo if promo is not None else promotion_for(product)
    return bool(promo and _valid_special(promo.discount_price, product.price))


def effective_price(product):
    promo = promotion_for(product)
    if amazing_active(product, promo=promo):
        return int(promo.amazing_price)
    if discount_active(product, promo=promo):
        return int(promo.discount_price)
    return int(product.price)


def promotion_label(product):
    promo = promotion_for(product)
    if amazing_active(product, promo=promo):
        return "شگفت‌انگیز"
    if discount_active(product, promo=promo):
        return "تخفیف"
    return ""


def promotion_data(product):
    promo = promotion_for(product)
    amazing = amazing_active(product, promo=promo)
    discount = discount_active(product, promo=promo)
    return {
        "base_price": int(product.price),
        "discount_price": int(promo.discount_price) if promo and promo.discount_price else None,
        "amazing_price": int(promo.amazing_price) if promo and promo.amazing_price else None,
        "discount_active": discount,
        "amazing_active": amazing,
        "effective_price": int(promo.amazing_price) if amazing else (int(promo.discount_price) if discount else int(product.price)),
        "promotion_label": "شگفت‌انگیز" if amazing else ("تخفیف" if discount else ""),
    }


def set_discount_price(product, value):
    promo = promotion_for(product, create=True)
    value = int(value or 0)
    if value == 0:
        promo.discount_price = None
    elif value >= int(product.price):
        raise ValueError("قیمت تخفیف باید از قیمت اصلی کمتر باشد.")
    else:
        promo.discount_price = value
    promo.save(update_fields=["discount_price", "updated_at"])
    return promo


def set_amazing_price(product, value):
    promo = promotion_for(product, create=True)
    value = int(value or 0)
    if value == 0:
        promo.amazing_price = None
        product.is_amazing = False
        product.save(update_fields=["is_amazing", "updated_at"])
    elif value >= int(product.price):
        raise ValueError("قیمت شگفت‌انگیز باید از قیمت اصلی کمتر باشد.")
    else:
        promo.amazing_price = value
        product.is_amazing = True
        product.save(update_fields=["is_amazing", "updated_at"])
    promo.save(update_fields=["amazing_price", "updated_at"])
    return promo


def normalize_promotions(product):
    promo = promotion_for(product)
    if not promo:
        return
    changed = []
    if promo.discount_price and not _valid_special(promo.discount_price, product.price):
        promo.discount_price = None
        changed.append("discount_price")
    if promo.amazing_price and not _valid_special(promo.amazing_price, product.price):
        promo.amazing_price = None
        changed.append("amazing_price")
        if product.is_amazing:
            product.is_amazing = False
            product.save(update_fields=["is_amazing", "updated_at"])
    if changed:
        promo.save(update_fields=[*changed, "updated_at"])
