import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .forms import CheckoutForm
from .backup import create_backup_archive, validate_backup_archive
from .models import Category, EmailVerificationToken, Order, Product, SiteSetting
from .services import set_order_status

User = get_user_model()


class StoreModelTests(TestCase):
    def test_singleton_settings_and_dynamic_name(self):
        first = SiteSetting.load()
        first.site_name = "پاندا"
        first.save()
        self.assertEqual(SiteSetting.load().site_name, "پاندا")
        self.assertEqual(SiteSetting.objects.count(), 1)

    def test_unicode_slugs_are_unique(self):
        one = Category.objects.create(name="گردنبند")
        two = Category.objects.create(name="گردنبند")
        self.assertNotEqual(one.slug, two.slug)


class StorefrontTests(TestCase):
    def setUp(self):
        self.store = SiteSetting.load()
        self.category = Category.objects.create(name="دستبند")
        self.product = Product.objects.create(category=self.category, name="دستبند تست", price=250000, stock=3, is_featured=True)
        self.client = Client()

    def test_cart_and_home(self):
        self.assertContains(self.client.get(reverse("home")), "دستبند تست")
        response = self.client.post(reverse("cart_add", args=[self.product.id]), {"quantity": 2})
        self.assertRedirects(response, reverse("cart"))
        self.assertContains(self.client.get(reverse("cart")), "دستبند تست")

    def test_checkout_payment_choices_follow_setting(self):
        self.store.payment_mode = "card"
        self.store.save()
        form = CheckoutForm(store_settings=self.store)
        self.assertEqual(list(form.fields["payment_method"].choices), [("card", "کارت به کارت و آپلود رسید")])

    def test_order_page_is_not_public_without_session(self):
        order = Order.objects.create(code="PRIVATE123", full_name="تست", mobile="09120000000", province="تهران", city="تهران", address="آدرس", postal_code="1234567890", subtotal=1, total=1, payment_method="card")
        self.assertEqual(self.client.get(reverse("order_status", args=[order.code])).status_code, 404)

    def test_catalog_searches_sku(self):
        response = self.client.get(reverse("catalog"), {"q": self.product.sku})
        self.assertContains(response, self.product.name)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class AccountTests(TestCase):
    def setUp(self):
        self.client = Client()

    def test_registration_requires_email_verification(self):
        response = self.client.post(reverse("register"), {
            "full_name": "مشتری تست",
            "email": "buyer@example.com",
            "password1": "SafePassword-12345",
            "password2": "SafePassword-12345",
        })
        self.assertEqual(response.status_code, 200)
        user = User.objects.get(email="buyer@example.com")
        self.assertFalse(user.is_active)
        self.assertTrue(EmailVerificationToken.objects.filter(user=user).exists())
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/account/verify/", mail.outbox[0].body)

    def test_order_is_visible_only_to_its_customer(self):
        owner = User.objects.create_user(username="owner@example.com", email="owner@example.com", password="test-pass", is_active=True)
        stranger = User.objects.create_user(username="other@example.com", email="other@example.com", password="test-pass", is_active=True)
        order = Order.objects.create(customer=owner, full_name="مالک", mobile="09120000000", province="تهران", city="تهران", address="آدرس", postal_code="1234567890", subtotal=1, total=1, payment_method="card")
        self.client.force_login(stranger)
        self.assertEqual(self.client.get(reverse("order_status", args=[order.code])).status_code, 404)
        self.client.force_login(owner)
        self.assertEqual(self.client.get(reverse("order_status", args=[order.code])).status_code, 200)

    def test_tracking_status_creates_timeline_event(self):
        order = Order.objects.create(full_name="تست", mobile="09120000000", province="تهران", city="تهران", address="آدرس", postal_code="1234567890", subtotal=1, total=1, payment_method="card")
        set_order_status(order, "shipped", "تحویل پست", tracking_code="123456789012345678901234")
        order.refresh_from_db()
        self.assertEqual(order.status, "shipped")
        self.assertEqual(order.tracking_code, "123456789012345678901234")
        self.assertTrue(order.status_events.filter(status="shipped").exists())


class BackupTests(TestCase):
    def test_backup_archive_has_database_and_media(self):
        SiteSetting.load()
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            media = root_path / "media"
            media.mkdir()
            (media / "example.txt").write_text("media", encoding="utf-8")
            with override_settings(MEDIA_ROOT=media), patch("shop.backup.BACKUP_DIR", root_path / "backups"):
                archive = create_backup_archive("test")
                manifest = validate_backup_archive(archive)
            self.assertEqual(manifest["format"], "sanashop-backup")
            self.assertTrue(archive.exists())
