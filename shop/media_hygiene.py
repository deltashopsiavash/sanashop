import logging

from django.db import transaction
from django.db.models.fields.files import FileField
from django.db.models.signals import post_delete, pre_save

logger = logging.getLogger(__name__)


def _file_fields(sender):
    return [field for field in sender._meta.concrete_fields if isinstance(field, FileField)]


def _safe_delete(storage, name):
    if not name:
        return
    try:
        storage.delete(name)
    except Exception:
        logger.exception("Could not delete obsolete media file: %s", name)


def cleanup_replaced_files(sender, instance, **kwargs):
    """Delete an old file only after the DB successfully points at the new file."""
    if not instance.pk:
        return
    try:
        old = sender._default_manager.get(pk=instance.pk)
    except sender.DoesNotExist:
        return

    for field in _file_fields(sender):
        old_file = getattr(old, field.name, None)
        new_file = getattr(instance, field.name, None)
        old_name = getattr(old_file, "name", "") or ""
        new_name = getattr(new_file, "name", "") or ""
        if old_name and old_name != new_name:
            storage = old_file.storage
            transaction.on_commit(lambda s=storage, n=old_name: _safe_delete(s, n))


def cleanup_deleted_files(sender, instance, **kwargs):
    """Remove media belonging to rows that were actually deleted."""
    for field in _file_fields(sender):
        value = getattr(instance, field.name, None)
        name = getattr(value, "name", "") or ""
        if name:
            storage = value.storage
            transaction.on_commit(lambda s=storage, n=name: _safe_delete(s, n))


def register_media_hygiene():
    # Import lazily so AppConfig.ready() can register every media-bearing model,
    # including models intentionally kept in extra_models.py for compatibility.
    from .extra_models import ProductStory, TrustBadge
    from .models import Category, HeroSlide, PaymentReceipt, Product, ProductImage, SiteSetting, SocialLink

    models = (
        SiteSetting,
        Category,
        Product,
        ProductImage,
        PaymentReceipt,
        HeroSlide,
        SocialLink,
        TrustBadge,
        ProductStory,
    )
    for model in models:
        pre_save.connect(
            cleanup_replaced_files,
            sender=model,
            weak=False,
            dispatch_uid=f"sanashop.media.pre_save.{model._meta.label_lower}",
        )
        post_delete.connect(
            cleanup_deleted_files,
            sender=model,
            weak=False,
            dispatch_uid=f"sanashop.media.post_delete.{model._meta.label_lower}",
        )
