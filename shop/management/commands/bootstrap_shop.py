import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from shop.models import SiteSetting


class Command(BaseCommand):
    help = "Initialize shop settings and optional administrator without recreating deleted catalog data."

    def handle(self, *args, **options):
        store = SiteSetting.load()
        changed_fields = []

        site_name = os.environ.get("DEFAULT_SITE_NAME", "").strip()
        if site_name and (not store.site_name or store.site_name == "سنا"):
            store.site_name = site_name
            changed_fields.append("site_name")

        merchant = os.environ.get("ZARINPAL_MERCHANT_ID", "").strip()
        if merchant and not store.zarinpal_merchant_id:
            store.zarinpal_merchant_id = merchant
            changed_fields.append("zarinpal_merchant_id")

        sandbox = os.environ.get("ZARINPAL_SANDBOX", "").strip()
        if sandbox in ("0", "1"):
            value = sandbox == "1"
            if store.zarinpal_sandbox != value:
                store.zarinpal_sandbox = value
                changed_fields.append("zarinpal_sandbox")

        card_number = os.environ.get("DEFAULT_CARD_NUMBER", "").strip()
        if card_number and not store.card_number:
            store.card_number = card_number
            changed_fields.append("card_number")

        card_owner = os.environ.get("DEFAULT_CARD_OWNER", "").strip()
        if card_owner and not store.card_owner:
            store.card_owner = card_owner
            changed_fields.append("card_owner")

        if changed_fields:
            store.save(update_fields=list(dict.fromkeys(changed_fields + ["updated_at"])))

        username = os.environ.get("DJANGO_SUPERUSER_USERNAME", "").strip()
        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD", "")
        email = os.environ.get("DJANGO_SUPERUSER_EMAIL", "")
        if username and password:
            User = get_user_model()
            if not User.objects.filter(username=username).exists():
                User.objects.create_superuser(username=username, email=email, password=password)
                self.stdout.write(self.style.SUCCESS("Administrator created."))
