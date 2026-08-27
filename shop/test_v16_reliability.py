import io
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .extra_models import CustomerProfile
from .iran_locations import province_city_map
from .models import Category, Order, PaymentReceipt, Product, ProductImage, SiteSetting

User = get_user_model()


class V16ApiMediaAndCategoryTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.headers = {"HTTP_AUTHORIZATION": "Bearer v16-test-key"}
        self.env = patch.dict(os.environ, {"SANASHOP_BOT_API_KEY": "v16-test-key"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.media = Path(self.temp.name) / "media"
        self.media.mkdir()
        self.override = override_settings(MEDIA_ROOT=self.media, MEDIA_URL="/media/")
        self.override.enable()
        self.addCleanup(self.override.disable)

    def api(self, action, payload=None):
        return self.client.post(
            reverse("bot_api_v1"),
            data=json.dumps({"action": action, "payload": payload or {}}),
            content_type="application/json",
            **self.headers,
        )

    @staticmethod
    def b64(raw):
        import base64
        return base64.b64encode(raw).decode("ascii")

    def test_ping_reports_v10(self):
        response = self.api("ping")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["site"]["version"], 10)

    def test_product_image_replacement_always_gets_new_url_and_removes_old_file(self):
        category = Category.objects.create(name="تصویر")
        product = Product.objects.create(category=category, name="محصول تصویر", price=100000, stock=2)
        product.image.save("product.jpg", SimpleUploadedFile("product.jpg", b"old-image", content_type="image/jpeg"), save=True)
        old_name = product.image.name
        old_path = self.media / old_name
        self.assertTrue(old_path.exists())

        with self.captureOnCommitCallbacks(execute=True):
            response = self.api("product_image_set", {
                "id": product.id,
                "image_b64": self.b64(b"new-image"),
                "filename": "product.jpg",
            })
        self.assertEqual(response.status_code, 200)
        product.refresh_from_db()
        self.assertNotEqual(product.image.name, old_name)
        self.assertIn("product-", product.image.name)
        self.assertTrue((self.media / product.image.name).exists())
        self.assertFalse(old_path.exists())

    def test_full_category_delete_removes_subtree_products_and_media(self):
        root = Category.objects.create(name="ریشه")
        child = Category.objects.create(name="فرزند", parent=root)
        root.image.save("root.jpg", SimpleUploadedFile("root.jpg", b"root", content_type="image/jpeg"), save=True)
        product = Product.objects.create(category=child, name="محصول حذف", price=200000, stock=1)
        product.image.save("main.jpg", SimpleUploadedFile("main.jpg", b"main", content_type="image/jpeg"), save=True)
        gallery = ProductImage.objects.create(product=product, image=SimpleUploadedFile("gallery.jpg", b"gallery", content_type="image/jpeg"))
        media_paths = [self.media / root.image.name, self.media / product.image.name, self.media / gallery.image.name]
        self.assertTrue(all(path.exists() for path in media_paths))

        preview = self.api("category_delete", {"id": root.id, "confirm": False}).json()["data"]
        self.assertEqual(preview["child_category_count"], 1)
        self.assertEqual(preview["product_count"], 1)
        self.assertTrue(Category.objects.filter(pk=root.pk).exists())

        with self.captureOnCommitCallbacks(execute=True):
            response = self.api("category_delete", {"id": root.id, "confirm": True})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Category.objects.filter(pk__in=[root.pk, child.pk]).exists())
        self.assertFalse(Product.objects.filter(pk=product.pk).exists())
        self.assertTrue(all(not path.exists() for path in media_paths))

    def test_caddy_revalidates_media_instead_of_week_long_cache(self):
        caddy = Path("docker/Caddyfile").read_text(encoding="utf-8")
        self.assertIn('Cache-Control "public, max-age=0, must-revalidate"', caddy)
        self.assertNotIn('Cache-Control "public, max-age=604800"', caddy)

    def test_fresh_installer_detects_stale_sanashop_volumes(self):
        installer = Path("install-site.sh").read_text(encoding="utf-8")
        self.assertIn("sanashop_postgres_data", installer)
        self.assertIn("sanashop_media_data", installer)
        self.assertIn("SANASHOP_FRESH_WIPE", installer)
        self.assertIn('confirm" != "DELETE', installer)


class V16CheckoutPaymentTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.store = SiteSetting.load()
        self.store.payment_mode = "card"
        self.store.card_number = "6037999999999999"
        self.store.card_owner = "فروشگاه تست"
        self.store.shipping_fee = 0
        self.store.save()
        self.user = User.objects.create_user(
            username="buyer-v16@example.com",
            email="buyer-v16@example.com",
            password="SafePassword-123",
            first_name="خریدار",
            last_name="تست",
            is_active=True,
        )
        CustomerProfile.ensure(self.user, "09121234567")
        self.client.force_login(self.user)
        self.category = Category.objects.create(name="خرید")
        self.product = Product.objects.create(category=self.category, name="کالای تست", price=150000, stock=5)
        locations = province_city_map()
        self.province = next(iter(locations))
        self.city = locations[self.province][0]

    def checkout_payload(self, payment_method="card"):
        return {
            "full_name": "خریدار تست",
            "mobile": "09121234567",
            "email": self.user.email,
            "province": self.province,
            "city": self.city,
            "postal_code": "1234567890",
            "address": "تهران، خیابان تست، پلاک ۱",
            "note": "",
            "payment_method": payment_method,
            "accept_terms": "on",
        }

    def add_to_cart(self):
        response = self.client.post(reverse("cart_add", args=[self.product.id]), {"quantity": 1})
        self.assertEqual(response.status_code, 302)

    def test_card_checkout_creates_invoice_and_reserves_stock(self):
        self.add_to_cart()
        response = self.client.post(reverse("checkout"), self.checkout_payload())
        order = Order.objects.get(customer=self.user)
        self.assertRedirects(response, reverse("card_payment", args=[order.code]))
        self.assertEqual(order.status, "pending")
        self.assertTrue(order.reservation_active)
        self.product.refresh_from_db()
        self.assertEqual(self.product.reserved_stock, 1)
        self.assertEqual(self.client.session.get("cart"), {})

    def test_card_checkout_without_card_number_returns_clear_error_and_keeps_cart(self):
        self.store.card_number = ""
        self.store.save(update_fields=["card_number", "updated_at"])
        self.add_to_cart()
        response = self.client.post(reverse("checkout"), self.checkout_payload())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "شماره کارت فروشگاه هنوز تنظیم نشده است")
        self.assertFalse(Order.objects.filter(customer=self.user).exists())
        self.assertIn(str(self.product.id), self.client.session.get("cart", {}))

    def test_receipt_upload_reaches_review_status(self):
        self.add_to_cart()
        response = self.client.post(reverse("checkout"), self.checkout_payload())
        order = Order.objects.get(customer=self.user)
        self.assertEqual(response.status_code, 302)
        image = io.BytesIO()
        Image.new("RGB", (2, 2), "white").save(image, format="PNG")
        receipt = SimpleUploadedFile("receipt.png", image.getvalue(), content_type="image/png")
        response = self.client.post(reverse("card_payment", args=[order.code]), {"image": receipt})
        self.assertRedirects(response, reverse("order_status", args=[order.code]))
        order.refresh_from_db()
        self.assertEqual(order.status, "review")
        self.assertTrue(PaymentReceipt.objects.filter(order=order, status="pending").exists())

    def test_zarinpal_start_failure_preserves_cart(self):
        self.store.payment_mode = "zarinpal"
        self.store.zarinpal_merchant_id = "00000000-0000-0000-0000-000000000000"
        self.store.save(update_fields=["payment_mode", "zarinpal_merchant_id", "updated_at"])
        self.add_to_cart()
        with patch("shop.checkout_views_v16.zarinpal_request", side_effect=RuntimeError("gateway offline")):
            response = self.client.post(reverse("checkout"), self.checkout_payload("zarinpal"))
        self.assertRedirects(response, reverse("checkout"))
        order = Order.objects.get(customer=self.user)
        self.assertEqual(order.status, "cancelled")
        self.product.refresh_from_db()
        self.assertEqual(self.product.reserved_stock, 0)
        self.assertIn(str(self.product.id), self.client.session.get("cart", {}))

    def test_transient_zarinpal_verify_error_does_not_cancel_order_or_release_stock(self):
        self.store.payment_mode = "zarinpal"
        self.store.zarinpal_merchant_id = "00000000-0000-0000-0000-000000000000"
        self.store.save(update_fields=["payment_mode", "zarinpal_merchant_id", "updated_at"])
        order = Order.objects.create(
            customer=self.user,
            full_name="خریدار تست",
            mobile="09121234567",
            email=self.user.email,
            province=self.province,
            city=self.city,
            postal_code="1234567890",
            address="آدرس",
            subtotal=150000,
            total=150000,
            payment_method="zarinpal",
            authority="A000000000000000000000000000000001",
            status="pending",
        )
        session = self.client.session
        session["order_code"] = order.code
        session.save()
        with patch("shop.checkout_views_v16.zarinpal_verify", side_effect=RuntimeError("temporary verify failure")):
            response = self.client.get(reverse("zarinpal_callback"), {"Authority": order.authority, "Status": "OK"})
        self.assertRedirects(response, reverse("order_status", args=[order.code]))
        order.refresh_from_db()
        self.assertEqual(order.status, "pending")
        self.assertFalse(order.reservation_released)
        self.assertIn("نیازمند بررسی پرداخت زرین‌پال", order.admin_note)
