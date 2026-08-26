import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .backup import create_backup_archive, validate_backup_archive
from .extra_models import CustomerProfile, EmailVerificationCode
from .forms import CheckoutForm
from .models import Category, ContentPage, Order, PaymentReceipt, Product, SiteSetting
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

    def test_customer_codes_start_at_v1001(self):
        one = User.objects.create_user(username="one@example.com", email="one@example.com")
        two = User.objects.create_user(username="two@example.com", email="two@example.com")
        p1 = CustomerProfile.ensure(one, "09120000001")
        p2 = CustomerProfile.ensure(two, "09120000002")
        self.assertEqual(p1.customer_code, "V1001")
        self.assertEqual(p2.customer_code, "V1002")


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

    def test_checkout_terms_are_linked(self):
        user = User.objects.create_user(username="buyer@example.com", email="buyer@example.com", password="test-pass", is_active=True)
        CustomerProfile.ensure(user, "09120000000")
        self.client.force_login(user)
        self.client.post(reverse("cart_add", args=[self.product.id]), {"quantity": 1})
        response = self.client.get(reverse("checkout"))
        self.assertContains(response, reverse("content_page", args=["terms"]))


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class AccountTests(TestCase):
    def setUp(self):
        self.client = Client()

    def test_registration_uses_six_digit_code_not_link(self):
        response = self.client.post(reverse("login"), {"email": "buyer@example.com"})
        self.assertRedirects(response, reverse("register"))
        response = self.client.post(reverse("register"), {
            "first_name": "مشتری",
            "last_name": "تست",
            "phone": "09123456789",
            "email": "buyer@example.com",
            "password1": "SafePassword-12345",
            "password2": "SafePassword-12345",
            "accept_terms": "on",
        })
        self.assertRedirects(response, reverse("verify_email_code"))
        user = User.objects.get(email="buyer@example.com")
        self.assertFalse(user.is_active)
        profile = CustomerProfile.objects.get(user=user)
        self.assertEqual(profile.customer_code, "V1001")
        self.assertEqual(profile.phone, "09123456789")
        otp = EmailVerificationCode.objects.get(user=user)
        self.assertEqual(len(otp.code), 6)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(otp.code, mail.outbox[0].body)
        self.assertNotIn("/account/verify/", mail.outbox[0].body)

        response = self.client.post(reverse("verify_email_code"), {"code": otp.code})
        self.assertRedirects(response, reverse("account_home"))
        user.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertFalse(EmailVerificationCode.objects.filter(user=user).exists())

    def test_existing_email_goes_to_password_step(self):
        User.objects.create_user(username="buyer@example.com", email="buyer@example.com", password="test-pass", is_active=True)
        response = self.client.post(reverse("login"), {"email": "buyer@example.com"})
        self.assertRedirects(response, reverse("account_password"))
        response = self.client.post(reverse("account_password"), {"password": "test-pass"})
        self.assertRedirects(response, reverse("account_home"))

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


class BotApiRegressionTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.headers = {"HTTP_AUTHORIZATION": "Bearer test-api-key"}
        self.env = patch.dict(os.environ, {"SANASHOP_BOT_API_KEY": "test-api-key"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def api(self, action, payload=None):
        return self.client.post(
            reverse("bot_api_v1"),
            data=json.dumps({"action": action, "payload": payload or {}}),
            content_type="application/json",
            **self.headers,
        )

    def test_order_detail_contains_id_used_by_telegram_callbacks(self):
        order = Order.objects.create(full_name="تست", mobile="09120000000", province="تهران", city="تهران", address="آدرس", postal_code="1234567890", subtotal=100, total=100, payment_method="card")
        response = self.api("order_detail", {"id": order.id})
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["id"], order.id)
        self.assertEqual(data["order_id"], order.id)

    def test_receipt_approval_changes_order_status(self):
        order = Order.objects.create(full_name="تست", mobile="09120000000", province="تهران", city="تهران", address="آدرس", postal_code="1234567890", subtotal=100, total=100, payment_method="card")
        receipt = PaymentReceipt.objects.create(
            order=order,
            image=SimpleUploadedFile("receipt.jpg", b"fake-image-data", content_type="image/jpeg"),
        )
        response = self.api("receipt_update", {"id": receipt.id, "status": "approved"})
        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        receipt.refresh_from_db()
        self.assertEqual(receipt.status, "approved")
        self.assertEqual(order.status, "paid")

    def test_user_search_by_customer_code_and_full_detail(self):
        user = User.objects.create_user(username="buyer@example.com", email="buyer@example.com", first_name="سارا", last_name="احمدی", is_active=True)
        profile = CustomerProfile.ensure(user, "09121234567")
        Order.objects.create(customer=user, full_name="سارا احمدی", mobile=profile.phone, province="تهران", city="تهران", address="آدرس", postal_code="1234567890", subtotal=500, total=500, payment_method="card", status="paid", stock_committed=True, reservation_released=True)
        response = self.api("user_search", {"query": profile.customer_code})
        self.assertEqual(response.status_code, 200)
        rows = response.json()["data"]
        self.assertEqual(rows[0]["email"], user.email)
        response = self.api("user_detail", {"id": user.id})
        detail = response.json()["data"]
        self.assertEqual(detail["customer_code"], profile.customer_code)
        self.assertEqual(detail["phone"], profile.phone)
        self.assertEqual(detail["order_count"], 1)
        self.assertEqual(detail["total_spent"], 500)

    def test_terms_update_syncs_linked_terms_page(self):
        response = self.api("settings_update", {"terms_text": "قوانین تست فروشگاه که از طریق ربات تنظیم شده است."})
        self.assertEqual(response.status_code, 200)
        store = SiteSetting.load()
        self.assertIn("قوانین تست", store.terms_text)
        page = ContentPage.objects.get(slug="terms")
        self.assertEqual(page.body, store.terms_text)
        self.assertFalse(page.show_in_footer)


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
