from django.apps import AppConfig


class ShopConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "shop"
    verbose_name = "فروشگاه"

    def ready(self):
        # These models live in a separate module to keep the original store models stable.
        from . import extra_models  # noqa: F401

        # Some legacy fields used environment variables directly as model defaults.
        # That made `makemigrations` report fake model changes on every production
        # server because DEFAULT_SITE_NAME/card/Zarinpal values differ by install.
        # Keep migration state deterministic; bootstrap_shop applies env values.
        from .models import SiteSetting

        stable_defaults = {
            "site_name": "سنا",
            "zarinpal_merchant_id": "",
            "zarinpal_sandbox": False,
            "card_number": "",
            "card_owner": "",
        }
        for field_name, value in stable_defaults.items():
            SiteSetting._meta.get_field(field_name).default = value

        # Media URLs must never point at a freshly replaced file while the old bytes
        # are still cached. Centralized signals remove obsolete files only after the
        # database commit succeeds, and also clean files when rows are deleted.
        from .media_hygiene import register_media_hygiene

        register_media_hygiene()
