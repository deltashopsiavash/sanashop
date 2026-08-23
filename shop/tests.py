from django.test import Client, TestCase
from django.urls import reverse

from .forms import CheckoutForm
from .models import Category, Order, Product, SiteSetting


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

