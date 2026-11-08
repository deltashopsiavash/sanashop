import json
import os
from types import SimpleNamespace
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from .models import Category, ContentPage, Order, Product, ProductColor, ProductOption, SiteSetting
from .order_creation_v17 import create_order
from .services import cart_rows, order_event_payload, order_report_text


class NumberedOptionStorefrontTests(TestCase):
    def setUp(self):
        category = Category.objects.create(name="نیم‌ست")
        self.product = Product.objects.create(
            category=category, name="کالکشن نیم‌ست", price=500000, stock=8,
        )
        self.first = ProductOption.objects.create(
            product=self.product, number=1, name="گردنبند", price=185000, is_available=True,
        )
        self.third = ProductOption.objects.create(
            product=self.product, number=3, name="انگشتر", price=120000, is_available=False,
        )
        self.other = Product.objects.create(
            category=category, name="محصول جدا", price=65000, stock=5,
        )

    def add(self, product, option_id=None, color_id=None, qty=1):
        data = {"quantity": qty}
        if option_id is not None:
            data["option_id"] = str(option_id)
        if color_id is not None:
            data["color_id"] = str(color_id)
        return self.client.post(reverse("cart_add", args=[product.pk]), data)

    def test_storefront_shows_all_options_including_sold_out(self):
        response = self.client.get(reverse("product_detail", args=[self.product.slug]))
        self.assertContains(response, "گردنبند")
        self.assertContains(response, "انگشتر")
        self.assertContains(response, "ناموجود")
        self.assertContains(response, 'name="option_id"', count=2)
        self.assertContains(response, str(self.third.price))
        self.assertContains(response, self.first.code)
        self.assertContains(response, 'value="' + str(self.third.id) + '" data-option-radio')

    def test_missing_option_and_wrong_product_option_rejected(self):
        self.add(self.product)
        self.add(self.product, self.third.pk)
        self.add(self.other, self.first.pk)
        self.assertFalse(self.client.session.get("cart", {}))

    def test_selected_price_and_option_identity_in_cart(self):
        self.add(self.product, self.first.pk, qty=2)
        cart = self.client.session["cart"]
        self.assertEqual(cart, {
            f"{self.product.pk}:0:{self.first.pk}": 2
        })
        response = self.client.get(reverse("cart"))
        self.assertContains(response, self.first.code)
        self.assertContains(response, "گردنبند")
        self.assertContains(response, "370,000")
        rows, subtotal = cart_rows(SimpleNamespace(session=self.client.session))
        self.assertEqual(rows[0]["unit_price"], 185000)
        self.assertEqual(subtotal, 370000)

    def test_legacy_product_and_color_keys_unaffected(self):
        self.add(self.other, qty=2)
        self.assertEqual(self.client.session["cart"], {str(self.other.pk): 2})
        color = ProductColor.objects.create(
            product=self.other, name="سفید", hex_code="#FFFFFF",
        )
        self.add(self.other, color_id=color.pk)
        self.assertEqual(self.client.session["cart"][f"{self.other.pk}:{color.pk}"], 1)

    def test_multiple_options_combined_with_colors_share_parent_stock(self):
        second = ProductOption.objects.create(
            product=self.product, number=2, name="دستبند", price=150000,
        )
        color = ProductColor.objects.create(
            product=self.product, name="طلایی", hex_code="#D4AF37",
        )
        self.add(self.product, self.first.pk, color_id=color.pk, qty=5)
        self.add(self.product, second.pk, color_id=color.pk, qty=5)
        rows, subtotal = cart_rows(SimpleNamespace(session=self.client.session))
        self.assertEqual(sum(row["quantity"] for row in rows), 8)
        self.assertEqual(sorted(row["unit_price"] for row in rows), [150000, 185000])

    def test_cart_lines_can_be_removed_independently(self):
        second = ProductOption.objects.create(
            product=self.product, number=2, price=155000,
        )
        self.add(self.product, self.first.pk)
        self.add(self.product, second.pk)
        self.client.post(reverse("cart_update", args=[self.product.pk]), {
            "option_id": self.first.pk, "quantity": 0,
        })
        self.assertEqual(self.client.session["cart"], {
            f"{self.product.pk}:0:{second.pk}": 1,
        })

    def test_option_price_and_code_snapshot_on_invoice_and_event(self):
        self.add(self.product, self.first.pk, qty=2)
        rows, subtotal = cart_rows(SimpleNamespace(session=self.client.session))
        class Form:
            def save(self, commit=False):
                return Order(
                    full_name="مشتری", mobile="09123456789", province="تهران",
                    city="تهران", address="تست", postal_code="1234567890",
                    payment_method="card",
                )
        order = create_order(Form(), rows, subtotal, SiteSetting.load())
        item = order.items.get()
        self.assertEqual(item.unit_price, 185000)
        self.assertEqual(item.option_number, 1)
        self.assertEqual(item.option_code, self.first.code)
        self.assertIn("گردنبند", item.option_title)
        payload = order_event_payload(order)
        self.assertEqual(payload["items"][0]["option_code"], self.first.code)
        self.assertIn(self.first.code, order_report_text(order))
        saved = item.option_code
        self.first.price = 999000
        self.first.name = "عنوان عوض شد"
        self.first.save()
        self.first.delete()
        item.refresh_from_db()
        self.assertEqual(item.unit_price, 185000)
        self.assertEqual(item.option_code, saved)
        self.assertIn("گردنبند", item.option_title)

    def test_option_unavailable_between_cart_and_checkout_blocks_invoice(self):
        self.add(self.product, self.first.pk)
        rows, subtotal = cart_rows(SimpleNamespace(session=self.client.session))
        self.first.is_available = False
        self.first.save(update_fields=["is_available"])
        class Form:
            def save(self, commit=False):
                raise AssertionError("Invoice must not be created")
        with self.assertRaises(ValueError):
            create_order(Form(), rows, subtotal, SiteSetting.load())
        self.assertFalse(Order.objects.exists())

    def test_option_price_changed_between_cart_and_checkout_recalculated(self):
        self.add(self.product, self.first.pk)
        rows, subtotal = cart_rows(SimpleNamespace(session=self.client.session))
        self.first.price = 220000
        self.first.save(update_fields=["price"])
        class Form:
            def save(self, commit=False):
                return Order(
                    full_name="مشتری", mobile="09123456789", province="تهران",
                    city="تهران", address="تست", postal_code="1234567890",
                    payment_method="card",
                )
        order = create_order(Form(), rows, subtotal, SiteSetting.load())
        self.assertEqual(order.subtotal, 220000)
        self.assertEqual(order.items.get().unit_price, 220000)


class OptionAndFAQApiTests(TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {"SANASHOP_BOT_API_KEY": "only-this-site"})
        environment.start()
        self.addCleanup(environment.stop)
        category = Category.objects.create(name="اکسسوری")
        self.one = Product.objects.create(category=category, name="اول", price=1000, stock=3)
        self.two = Product.objects.create(category=category, name="دوم", price=2000, stock=3)

    def api(self, action, payload=None, auth=True):
        return self.client.post(
            reverse("bot_api_v1"),
            data=json.dumps({"action": action, "payload": payload or {}}),
            content_type="application/json",
            **({"HTTP_AUTHORIZATION": "Bearer only-this-site"} if auth else {}),
        )

    def test_api_requires_private_site_key(self):
        response = self.api("product_options_add", {
            "id": self.one.pk, "number": 1, "price": 8000,
        }, auth=False)
        self.assertEqual(response.status_code, 401)
        self.assertFalse(ProductOption.objects.exists())
        self.assertEqual(self.api("faq_get", auth=False).status_code, 401)

    def test_add_edit_toggle_delete_isolated_to_selected_product(self):
        res = self.api("product_options_add", {
            "id": self.one.pk, "number": 4, "price": 99000, "name": "انگشتر"
        })
        self.assertEqual(res.status_code, 200)
        oid = res.json()["data"]["id"]
        self.assertEqual(res.json()["data"]["code"], f"{self.one.sku}-04")
        self.assertEqual(self.api("product_options_update", {
            "id": self.two.pk, "option_id": oid, "price": 1,
        }).status_code, 404)
        self.assertEqual(self.api("product_options_update", {
            "id": self.one.pk, "option_id": oid,
            "price": 150000, "is_available": False,
        }).status_code, 200)
        self.assertEqual(ProductOption.objects.get(pk=oid).price, 150000)
        self.assertFalse(ProductOption.objects.get(pk=oid).is_available)
        self.assertEqual(self.api("product_options_delete", {
            "id": self.one.pk, "option_id": oid,
        }).status_code, 200)
        self.assertFalse(ProductOption.objects.exists())

    def test_duplicate_number_and_invalid_price_refused(self):
        self.assertEqual(self.api("product_options_add", {
            "id": self.one.pk, "number": 1, "price": 900,
        }).status_code, 200)
        self.assertEqual(self.api("product_options_add", {
            "id": self.one.pk, "number": 1, "price": 900,
        }).status_code, 400)
        self.assertEqual(self.api("product_options_add", {
            "id": self.one.pk, "number": 2, "price": 0,
        }).status_code, 400)

    def test_faq_created_if_missing_and_editable_via_site_api(self):
        ContentPage.objects.filter(slug="faq").delete()
        response = self.client.get(reverse("content_page", args=["faq"]))
        self.assertEqual(response.status_code, 200)
        text = "سؤال: ارسال چطور است؟\nجواب: با پست."
        result = self.api("faq_set", {"body": text})
        self.assertEqual(result.status_code, 200)
        page = self.client.get(reverse("content_page", args=["faq"]))
        self.assertContains(page, "ارسال چطور است؟")
        self.assertContains(page, "با پست")
        self.assertEqual(self.api("faq_get").json()["data"]["body"], text)
