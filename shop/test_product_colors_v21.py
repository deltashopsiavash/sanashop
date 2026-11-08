import json
import os
from types import SimpleNamespace
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse

from .models import Category, Order, Product, ProductColor, SiteSetting
from .order_creation_v17 import create_order
from .services import cart_rows, order_event_payload


class ProductColorCheckoutTests(TestCase):
    def setUp(self):
        category = Category.objects.create(name="اکسسوری")
        self.item = Product.objects.create(category=category, name="گردنبند", price=135000, stock=4)
        self.other = Product.objects.create(category=category, name="دستبند", price=80000, stock=5)
        self.black = ProductColor.objects.create(product=self.item, name="مشکی", hex_code="#000000")
        self.white = ProductColor.objects.create(product=self.item, name="سفید", hex_code="#FFFFFF")
        self.client = Client()

    def add(self, p, color=None, quantity=1):
        return self.client.post(reverse("cart_add", args=[p.id]), {
            "quantity": quantity, **({"color_id": str(color.id)} if color else {}),
        })

    def test_product_page_shows_color_swatches(self):
        response = self.client.get(reverse("product_detail", args=[self.item.slug]))
        self.assertContains(response, 'name="color_id"', count=2)
        self.assertContains(response, "#000000")
        self.assertContains(response, "product-options.css")

    def test_multi_color_cart_lines_share_total_stock(self):
        self.add(self.item, self.black, 2)
        self.add(self.item, self.white, 2)
        self.add(self.item, self.black, 3)
        self.assertEqual(self.client.session["cart"], {
            f"{self.item.id}:{self.black.id}": 2,
            f"{self.item.id}:{self.white.id}": 2,
        })
        page = self.client.get(reverse("cart"))
        self.assertContains(page, "رنگ: مشکی")
        self.assertContains(page, "رنگ: سفید")

    def test_color_required_and_cross_product_invalid(self):
        self.add(self.item)
        self.add(self.other, self.black)
        self.assertEqual(self.client.session.get("cart", {}), {})

    def test_cart_update_only_removes_chosen_color(self):
        self.add(self.item, self.black)
        self.add(self.item, self.white)
        self.client.post(reverse("cart_update", args=[self.item.id]), {
            "color_id": self.black.id, "quantity": "0",
        })
        self.assertEqual(self.client.session["cart"], {
            f"{self.item.id}:{self.white.id}": 1,
        })

    def test_old_cart_numeric_key_and_single_color_migration(self):
        self.add(self.other, quantity=2)
        self.assertEqual(self.client.session["cart"][str(self.other.id)], 2)
        self.white.is_active = False
        self.white.save(update_fields=["is_active"])
        session = self.client.session
        session["cart"] = {str(self.item.id): 1}
        session.save()
        self.client.get(reverse("cart"))
        self.assertEqual(self.client.session["cart"], {
            f"{self.item.id}:{self.black.id}": 1,
        })

    def test_invoice_remembers_color_after_merchant_edits_it(self):
        self.add(self.item, self.white, 2)
        rows, subtotal = cart_rows(SimpleNamespace(session=self.client.session))
        class Form:
            def save(self, commit=False):
                return Order(
                    full_name="مشتری تست", mobile="09121234567", province="تهران",
                    city="تهران", address="خیابان تست", postal_code="1234567890",
                    payment_method="card",
                )
        order = create_order(Form(), rows, subtotal, SiteSetting.load())
        item = order.items.get()
        self.assertEqual(item.selected_color, "سفید")
        self.assertEqual(item.color_hex, "#FFFFFF")
        self.assertEqual(order_event_payload(order)["items"][0]["selected_color"], "سفید")
        self.white.name = "سفید جدید"
        self.white.save(update_fields=["name"])
        item.refresh_from_db()
        self.assertEqual(item.selected_color, "سفید")

    def test_invalid_color_removed_before_checkout_is_rejected(self):
        self.add(self.item, self.black)
        rows, subtotal = cart_rows(SimpleNamespace(session=self.client.session))
        self.black.delete()
        class Form:
            def save(self, commit=False):
                return Order(full_name="خریدار", mobile="09121234567", province="تهران",
                             city="تهران", address="آدرس", postal_code="1234567890",
                             payment_method="card")
        with self.assertRaises(ValueError):
            create_order(Form(), rows, subtotal, SiteSetting.load())
        self.assertEqual(Order.objects.count(), 0)

    def test_invalid_hex_rejected_by_model(self):
        invalid = ProductColor(product=self.other, name="آبی", hex_code="blue")
        with self.assertRaises(ValidationError):
            invalid.full_clean()


class ColorSiteAPITests(TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {"SANASHOP_BOT_API_KEY": "site-key-test"})
        env.start()
        self.addCleanup(env.stop)
        category = Category.objects.create(name="هدایا")
        self.one = Product.objects.create(category=category, name="اول", price=10000, stock=5)
        self.two = Product.objects.create(category=category, name="دوم", price=10000, stock=5)

    def api(self, action, payload, authorized=True):
        return self.client.post(
            reverse("bot_api_v1"),
            data=json.dumps({"action": action, "payload": payload}),
            content_type="application/json",
            **({"HTTP_AUTHORIZATION": "Bearer site-key-test"} if authorized else {}),
        )

    def test_requires_site_token(self):
        res = self.api("product_colors_add", {
            "id": self.one.pk, "name": "طلایی", "hex_code": "#D4AF37",
        }, authorized=False)
        self.assertEqual(res.status_code, 401)
        self.assertFalse(ProductColor.objects.exists())

    def test_crud_is_limited_to_selected_product(self):
        create = self.api("product_colors_add", {
            "id": self.one.pk, "name": "قرمز", "hex_code": "#FF0000",
        })
        self.assertEqual(create.status_code, 200)
        cid = create.json()["data"]["id"]
        self.assertEqual(self.api("product_colors_update", {
            "id": self.two.pk, "color_id": cid, "name": "آبی",
        }).status_code, 404)
        self.assertEqual(self.api("product_colors_update", {
            "id": self.one.pk, "color_id": cid, "name": "صورتی",
            "hex_code": "#FF99CC",
        }).status_code, 200)
        self.assertEqual(ProductColor.objects.get(pk=cid).name, "صورتی")
        self.assertEqual(self.api("product_colors_delete", {
            "id": self.one.pk, "color_id": cid,
        }).status_code, 200)

    def test_bad_hex_and_duplicate_color_rejected(self):
        self.assertEqual(self.api("product_colors_add", {
            "id": self.one.pk, "name": "سبز", "hex_code": "green",
        }).status_code, 400)
        self.assertEqual(self.api("product_colors_add", {
            "id": self.one.pk, "name": "سبز", "hex_code": "#008000",
        }).status_code, 200)
        self.assertEqual(self.api("product_colors_add", {
            "id": self.one.pk, "name": "سبز", "hex_code": "#00FF00",
        }).status_code, 400)
