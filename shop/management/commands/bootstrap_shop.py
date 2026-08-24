import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from shop.models import Category, SiteSetting


class Command(BaseCommand):
    help = "Create initial shop settings, categories, and optional administrator."

    def handle(self, *args, **options):
        store = SiteSetting.load()
        changed = False
        merchant = os.environ.get("ZARINPAL_MERCHANT_ID", "").strip()
        if merchant and not store.zarinpal_merchant_id:
            store.zarinpal_merchant_id = merchant
            changed = True
        if changed:
            store.save()
        if not Category.objects.exists():
            for order, name in enumerate(("گردنبند", "گوشواره", "دستبند", "انگشتر", "اکسسوری مو"), 1):
                Category.objects.create(name=name, sort_order=order)
        username = os.environ.get("DJANGO_SUPERUSER_USERNAME", "").strip()
        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD", "")
        email = os.environ.get("DJANGO_SUPERUSER_EMAIL", "")
        if username and password:
            User = get_user_model()
            if not User.objects.filter(username=username).exists():
                User.objects.create_superuser(username=username, email=email, password=password)
                self.stdout.write(self.style.SUCCESS("Administrator created."))
