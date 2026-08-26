from django.apps import AppConfig


class ShopConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "shop"
    verbose_name = "فروشگاه"

    def ready(self):
        # These models live in a separate module to keep the original store models stable.
        from . import extra_models  # noqa: F401
