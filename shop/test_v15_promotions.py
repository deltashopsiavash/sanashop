import json
import os
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.test import Client, TestCase
from django.urls import reverse

from .extra_models import ProductPromotion
from .models import Category, Product
from .pricing import effective_price, promotion_label, set_amazing_price, set_discount_price


class ProductPromotionTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="اکسسوری")
        self.product = Product.objects.create(
            category=self.category,
            name="محصول تست",
            price=200000,
            stock=10,
        )

    def test_discount_keeps_base_price_and_changes_effective_price(self):
        set_discount_price(self.product, 150000)
        self.product.refresh_from_db()
        self.assertEqual(self.product.price, 200000)
        self.assertEqual(effective_price(self.product), 150000)
        self.assertEqual(promotion_label(self.product), "تخفیف")

    def test_amazing_price_overrides_discount_and_remove_returns_to_discount(self):
        set_discount_price(self.product, 150000)
        set_amazing_price(self.product, 120000)
        self.product.refresh_from_db()
        self.assertTrue(self.product.is_amazing)
        self.assertEqual(effective_price(self.product), 120000)
        self.assertEqual(promotion_label(self.product), "شگفت‌انگیز")

        set_amazing_price(self.product, 0)
        self.product.refresh_from_db()
        self.assertFalse(self.product.is_amazing)
        self.assertEqual(effective_price(self.product), 150000)
        self.assertEqual(promotion_label(self.product), "تخفیف")

    def test_remove_discount_returns_to_base_price(self):
        set_discount_price(self.product, 150000)
        set_discount_price(self.product, 0)
        self.product.refresh_from_db()
        self.assertEqual(effective_price(self.product), 200000)
        self.assertEqual(promotion_label(self.product), "")

    def test_special_price_must_be_lower_than_base(self):
        with self.assertRaises(ValueError):
            set_discount_price(self.product, 200000)
        with self.assertRaises(ValueError):
            set_amazing_price(self.product, 250000)

    def test_cart_uses_effective_price_not_base_price(self):
        set_discount_price(self.product, 150000)
        client = Client()
        response = client.post(reverse("cart_add", args=[self.product.id]), {"quantity": 2, "next": reverse("cart")})
        self.assertEqual(response.status_code, 302)
        response = client.get(reverse("cart"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "150,000")
        self.assertContains(response, "200,000")
        self.assertContains(response, "300,000")


class ProductPromotionApiTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.headers = {"HTTP_AUTHORIZATION": "Bearer test-api-key"}
        self.env = patch.dict(os.environ, {"SANASHOP_BOT_API_KEY": "test-api-key"})
        self.env.start()
        self.addCleanup(self.env.stop)
        category = Category.objects.create(name="اکسسوری")
        self.product = Product.objects.create(category=category, name="API test", price=200000, stock=3)

    def api(self, action, payload=None):
        return self.client.post(
            reverse("bot_api_v1"),
            data=json.dumps({"action": action, "payload": payload or {}}),
            content_type="application/json",
            **self.headers,
        )

    def test_bot_can_manage_discount_and_amazing_prices_independently(self):
        response = self.api("product_update", {"id": self.product.id, "discount_price": 150000})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["base_price"], 200000)
        self.assertEqual(response.json()["data"]["effective_price"], 150000)
        self.assertEqual(response.json()["data"]["promotion_label"], "تخفیف")

        response = self.api("product_update", {"id": self.product.id, "amazing_price": 120000})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["effective_price"], 120000)
        self.assertEqual(response.json()["data"]["promotion_label"], "شگفت‌انگیز")

        response = self.api("product_update", {"id": self.product.id, "amazing_price": 0})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["effective_price"], 150000)
        self.assertEqual(response.json()["data"]["promotion_label"], "تخفیف")

        response = self.api("product_update", {"id": self.product.id, "discount_price": 0})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["effective_price"], 200000)
        self.assertEqual(response.json()["data"]["promotion_label"], "")

    def test_bot_v15_and_installers_are_selected(self):
        root = Path(settings.BASE_DIR)
        bot = (root / "external_bot_v15.py").read_text(encoding="utf-8")
        self.assertIn("v15_discount_price", bot)
        self.assertIn("v15_amazing_price", bot)
        self.assertIn("قیمت اصلی", bot)
        self.assertIn("تخفیف", bot)
        for filename in ("install-bot.sh", "update-bot.sh"):
            self.assertIn("external_bot_v15.py", (root / filename).read_text(encoding="utf-8"))

    def test_promotion_model_is_registered(self):
        self.assertEqual(ProductPromotion._meta.app_label, "shop")
