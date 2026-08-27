from pathlib import Path

from django.conf import settings
from django.test import TestCase

from .forms import CheckoutForm
from .iran_locations import province_city_map
from .models import Category, Product, SiteSetting
from .order_creation_v17 import create_order
from .pricing import set_discount_price


class PostgreSQLInvoiceLockRegressionTests(TestCase):
    def setUp(self):
        self.store = SiteSetting.load()
        self.store.payment_mode = "card"
        self.store.shipping_fee = 0
        self.store.save(update_fields=["payment_mode", "shipping_fee", "updated_at"])
        self.category = Category.objects.create(name="فاکتور PostgreSQL")
        self.product = Product.objects.create(
            category=self.category,
            name="محصول فاکتور",
            price=200000,
            stock=5,
        )
        set_discount_price(self.product, 150000)
        locations = province_city_map()
        self.province = next(iter(locations))
        self.city = locations[self.province][0]

    def _form(self):
        form = CheckoutForm(
            data={
                "full_name": "خریدار تست",
                "mobile": "09121234567",
                "email": "buyer@example.com",
                "province": self.province,
                "city": self.city,
                "postal_code": "1234567890",
                "address": "آدرس تست برای ساخت فاکتور",
                "note": "",
                "payment_method": "card",
                "accept_terms": "on",
            },
            store_settings=self.store,
        )
        self.assertTrue(form.is_valid(), form.errors.as_json())
        return form

    def test_invoice_with_optional_promotion_is_created_at_discount_price(self):
        order = create_order(
            self._form(),
            [{"product": self.product, "quantity": 1, "unit_price": 150000, "total": 150000}],
            150000,
            self.store,
        )
        item = order.items.get()
        self.assertEqual(item.unit_price, 150000)
        self.assertEqual(order.total, 150000)
        self.product.refresh_from_db()
        self.assertEqual(self.product.reserved_stock, 1)

    def test_lock_query_does_not_join_nullable_promotion_relation(self):
        source = (Path(settings.BASE_DIR) / "shop" / "order_creation_v17.py").read_text(encoding="utf-8")
        self.assertIn('Product.objects.select_for_update().get', source)
        self.assertNotIn('select_for_update().select_related("promotion")', source)
        self.assertNotIn("select_related('promotion').select_for_update()", source)

    def test_checkout_routes_use_v17_invoice_creator(self):
        wrapper = (Path(settings.BASE_DIR) / "shop" / "checkout_views_v17.py").read_text(encoding="utf-8")
        urls = (Path(settings.BASE_DIR) / "shop" / "urls.py").read_text(encoding="utf-8")
        self.assertIn("v16.create_order = postgres_safe_create_order", wrapper)
        self.assertIn("checkout_views_v17.checkout", urls)
        self.assertIn("checkout_views_v17.card_payment", urls)
