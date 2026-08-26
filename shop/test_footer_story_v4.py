import base64
import json
import os
import tempfile
from datetime import timedelta
from unittest.mock import patch

from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .extra_models import FooterSetting, FooterSocial, ProductStory, TrustBadge
from .models import HeroSlide, SiteSetting


class FooterStoryApiTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.override = override_settings(MEDIA_ROOT=self.tmp.name)
        self.override.enable()
        self.client = Client()
        self.env = patch.dict(os.environ, {"SANASHOP_BOT_API_KEY": "test-key", "DOMAIN": "shop.example.com"})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.override.disable()
        self.tmp.cleanup()

    def api(self, action, payload=None):
        return self.client.post(
            reverse("bot_api_v1"),
            data=json.dumps({"action": action, "payload": payload or {}}),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer test-key",
        )

    def test_footer_settings_and_platform_social(self):
        response = self.api(
            "settings_update",
            {
                "address": "تهران، خیابان تست",
                "phone": "02112345678",
                "contact_email": "shop@example.com",
                "footer_description": "متن فوتر",
            },
        )
        self.assertEqual(response.status_code, 200)
        footer = FooterSetting.load()
        self.assertEqual(footer.address, "تهران، خیابان تست")
        self.assertEqual(footer.phone, "02112345678")
        self.assertEqual(footer.email, "shop@example.com")

        response = self.api(
            "social_create",
            {"platform": "instagram", "title": "اینستاگرام", "url": "https://instagram.com/example"},
        )
        self.assertEqual(response.status_code, 200)
        social = FooterSocial.objects.get()
        self.assertEqual(social.platform, "instagram")
        self.assertTrue(social.is_active)

    def test_logo_enamad_and_dual_banner_uploads(self):
        encoded = base64.b64encode(b"fake-image-bytes").decode("ascii")
        response = self.api("logo_set", {"image_b64": encoded, "image_filename": "logo.png"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(SiteSetting.load().logo)

        response = self.api("enamad_set", {"image_b64": encoded, "image_filename": "enamad.png"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(TrustBadge.load().image)

        response = self.api(
            "banner_create",
            {
                "link": "/products/",
                "mobile_image_b64": encoded,
                "mobile_image_filename": "mobile.jpg",
                "desktop_image_b64": encoded,
                "desktop_image_filename": "desktop.jpg",
            },
        )
        self.assertEqual(response.status_code, 200)
        banner = HeroSlide.objects.get()
        self.assertTrue(banner.image)
        self.assertTrue(banner.mobile_image)

    def test_story_creation_visibility_and_expiry(self):
        encoded = base64.b64encode(b"fake-story-image").decode("ascii")
        response = self.api(
            "story_create",
            {
                "title": "گردنبند طرح پروانه",
                "media_type": "image",
                "media_b64": encoded,
                "media_filename": "story.jpg",
                "target_url": "/products/",
                "duration_hours": 24,
            },
        )
        self.assertEqual(response.status_code, 200)
        story = ProductStory.objects.get()
        self.assertTrue(story.active_now)
        self.assertGreater(story.remaining_seconds, 23 * 3600)

        home = self.client.get(reverse("home"))
        self.assertEqual(home.status_code, 200)
        self.assertContains(home, "گردنبند طرح پروانه")
        self.assertContains(home, "data-story-open")

        story.expires_at = timezone.now() - timedelta(seconds=1)
        story.save(update_fields=["expires_at", "updated_at"])
        home = self.client.get(reverse("home"))
        self.assertNotContains(home, "گردنبند طرح پروانه")
