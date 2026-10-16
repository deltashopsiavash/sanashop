"""Regression tests for multi-photo storefront and remote-bot gallery operations."""
import base64
import io
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .models import Category, Product, ProductImage


class ProductGalleryApiTests(TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.media_root = Path(self.directory.name)
        override = override_settings(MEDIA_ROOT=self.media_root, MEDIA_URL="/media/")
        override.enable()
        self.addCleanup(override.disable)
        env = patch.dict(os.environ, {"SANASHOP_BOT_API_KEY": "gallery-test-key"})
        env.start()
        self.addCleanup(env.stop)
        self.client = Client()
        self.category = Category.objects.create(name="زیورآلات")
        self.product = Product.objects.create(
            category=self.category, name="دستبند", price=100000, stock=5)

    def api(self, action, payload=None, authorized=True):
        headers = {"HTTP_AUTHORIZATION": "Bearer gallery-test-key"} if authorized else {}
        return self.client.post(
            reverse("bot_api_v1"),
            data=json.dumps({"action": action, "payload": payload or {}}),
            content_type="application/json", **headers)

    @staticmethod
    def photo(color=(185, 60, 100)):
        out = io.BytesIO()
        Image.new("RGB", (48, 48), color).save(out, format="PNG")
        return out.getvalue()

    def upload(self, action="product_gallery_add", image_id=None, color=(185, 60, 100)):
        payload = {
            "id": self.product.pk, "image_b64": base64.b64encode(self.photo(color)).decode(),
            "filename": "image.png",
        }
        if image_id is not None:
            payload["image_id"] = image_id
        return self.api(action, payload)

    def test_bearer_auth_and_reject_invalid_files(self):
        self.assertEqual(self.api("product_gallery_list", {"id": self.product.pk}, False).status_code, 401)
        bad = self.api("product_gallery_add", {
            "id": self.product.pk,
            "image_b64": base64.b64encode(b"not-an-image").decode(),
            "filename": "fake.png",
        })
        self.assertEqual(bad.status_code, 400)
        self.assertFalse(self.product.gallery.exists())
        self.product.refresh_from_db()
        self.assertFalse(self.product.image)

    def test_create_primary_then_secondary_and_show_on_storefront(self):
        first = self.upload()
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["data"]["image_id"], 0)
        second = self.upload(color=(40, 80, 130))
        self.assertEqual(second.status_code, 200)
        image_id = second.json()["data"]["image_id"]
        self.assertGreater(image_id, 0)
        gallery = self.api("product_gallery_list", {"id": self.product.pk}).json()["data"]
        self.assertEqual(gallery["count"], 2)
        self.assertEqual([image["id"] for image in gallery["photos"]], [0, image_id])
        self.assertTrue(gallery["photos"][0]["is_primary"])
        preview = self.api("product_gallery_get", {"id": self.product.pk, "image_id": image_id})
        self.assertEqual(base64.b64decode(preview.json()["data"]["image_b64"]),
                         self.photo((40, 80, 130)))
        self.product.refresh_from_db()
        page = self.client.get(reverse("product_detail", args=[self.product.slug]))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'data-gallery-thumb', count=2)
        self.assertContains(page, 'product-gallery.js')
        self.assertContains(page, self.product.gallery.first().image.url)

    def test_replace_photo_deletes_previous_file_after_commit(self):
        self.upload()
        secondary = self.upload(color=(40, 80, 130)).json()["data"]["image_id"]
        row = ProductImage.objects.get(pk=secondary)
        before = row.image.name
        with self.captureOnCommitCallbacks(execute=True):
            result = self.upload("product_gallery_replace", secondary, color=(60, 180, 90))
        self.assertEqual(result.status_code, 200)
        row.refresh_from_db()
        self.assertNotEqual(before, row.image.name)
        self.assertFalse((self.media_root / before).exists())
        self.assertTrue((self.media_root / row.image.name).exists())

    def test_reorder_promote_to_primary_and_delete_preserve_correct_files(self):
        self.upload()
        a = self.upload(color=(40, 80, 130)).json()["data"]["image_id"]
        b = self.upload(color=(10, 180, 90)).json()["data"]["image_id"]
        moved = self.api("product_gallery_move", {
            "id": self.product.pk, "image_id": b, "direction": "up"})
        self.assertEqual(moved.status_code, 200)
        photos = moved.json()["data"]["photos"]
        self.assertEqual([p["id"] for p in photos], [0, b, a])
        original = self.product
        original.refresh_from_db()
        original_name = original.image.name
        b_name = ProductImage.objects.get(pk=b).image.name
        with self.captureOnCommitCallbacks(execute=True):
            promoted = self.api("product_gallery_primary", {
                "id": self.product.pk, "image_id": b})
        self.assertEqual(promoted.status_code, 200)
        original.refresh_from_db()
        self.assertEqual(original.image.name, b_name)
        self.assertEqual(ProductImage.objects.get(pk=b).image.name, original_name)
        self.assertTrue((self.media_root / b_name).exists())
        self.assertTrue((self.media_root / original_name).exists())

        with self.captureOnCommitCallbacks(execute=True):
            removed = self.api("product_gallery_delete", {
                "id": self.product.pk, "image_id": 0})
        self.assertEqual(removed.status_code, 200)
        original.refresh_from_db()
        self.assertEqual(original.image.name, original_name)
        self.assertFalse(ProductImage.objects.filter(pk=b).exists())
        self.assertFalse((self.media_root / b_name).exists())
        self.assertTrue((self.media_root / original_name).exists())
        self.assertEqual(removed.json()["data"]["count"], 2)

    def test_alt_text_and_only_allow_images_of_own_product(self):
        self.upload()
        extra = self.upload().json()["data"]["image_id"]
        updated = self.api("product_gallery_alt", {
            "id": self.product.pk, "image_id": extra, "alt": "نمای نزدیک دستبند"})
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(ProductImage.objects.get(pk=extra).alt, "نمای نزدیک دستبند")
        other = Product.objects.create(category=self.category, name="دیگر", price=1000)
        self.assertEqual(self.api("product_gallery_delete", {
            "id": other.pk, "image_id": extra}).status_code, 404)
        self.assertTrue(ProductImage.objects.filter(pk=extra).exists())
        self.assertEqual(self.api("product_gallery_move", {
            "id": self.product.pk, "image_id": 0, "direction": "up"}).status_code, 400)

    def test_delete_last_primary_yields_empty_gallery(self):
        self.upload()
        old = Product.objects.get(pk=self.product.pk).image.name
        with self.captureOnCommitCallbacks(execute=True):
            result = self.api("product_gallery_delete", {
                "id": self.product.pk, "image_id": 0})
        self.assertEqual(result.status_code, 200)
        self.product.refresh_from_db()
        self.assertFalse(self.product.image)
        self.assertFalse((self.media_root / old).exists())
        self.assertEqual(result.json()["data"]["photos"], [])
