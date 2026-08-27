import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .emailing import send_otp_email
from .extra_models import EmailVerificationCode, FooterSetting
from .models import SiteSetting

User = get_user_model()


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", ALLOWED_HOSTS=["example.com", "testserver"])
class EmailBrandingV9Tests(TestCase):
    def setUp(self):
        self.client = Client()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.media_override = override_settings(MEDIA_ROOT=self.tmp.name)
        self.media_override.enable()
        self.addCleanup(self.media_override.disable)
        self.domain_env = patch.dict(os.environ, {"DOMAIN": "example.com"})
        self.domain_env.start()
        self.addCleanup(self.domain_env.stop)
        self.store = SiteSetting.load()
        self.store.site_name = "VELORA"
        self.store.logo.save(
            "velora-logo.png",
            SimpleUploadedFile("velora-logo.png", b"fake-image", content_type="image/png"),
            save=True,
        )

    def test_otp_email_contains_absolute_store_logo(self):
        user = User.objects.create_user(username="otp@example.com", email="otp@example.com", is_active=False)
        otp = EmailVerificationCode.issue(user)
        send_otp_email(user, otp)
        self.assertEqual(len(mail.outbox), 1)
        html = mail.outbox[0].alternatives[0][0]
        self.assertIn("https://example.com/media/branding/", html)
        self.assertIn("velora-logo", html)
        self.assertIn(otp.code, html)

    def test_normal_password_reset_email_has_logo_and_button(self):
        User.objects.create_user(
            username="buyer@example.com",
            email="buyer@example.com",
            password="SafePassword-12345",
            is_active=True,
        )
        response = self.client.post(reverse("password_reset"), {"email": "buyer@example.com"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        html = mail.outbox[0].alternatives[0][0]
        self.assertIn("https://example.com/media/branding/", html)
        self.assertIn("تغییر رمز عبور", html)
        self.assertIn("VELORA", html)


class ContactPhoneV9Tests(TestCase):
    def setUp(self):
        self.client = Client()
        self.headers = {"HTTP_AUTHORIZATION": "Bearer test-api-key"}
        self.env = patch.dict(os.environ, {"SANASHOP_BOT_API_KEY": "test-api-key"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.store = SiteSetting.load()
        self.footer = FooterSetting.load()

    def api(self, action, payload=None):
        return self.client.post(
            reverse("bot_api_v1"),
            data=json.dumps({"action": action, "payload": payload or {}}),
            content_type="application/json",
            **self.headers,
        )

    def test_contact_phone_is_independent_from_footer_phone(self):
        self.footer.phone = "02111111111"
        self.footer.save(update_fields=["phone", "updated_at"])
        response = self.api("settings_update", {"contact_phone": "09123456789"})
        self.assertEqual(response.status_code, 200)
        self.store.refresh_from_db()
        self.footer.refresh_from_db()
        self.assertEqual(self.store.phone, "09123456789")
        self.assertEqual(self.footer.phone, "02111111111")
        data = response.json()["data"]
        self.assertEqual(data["contact_phone"], "09123456789")
        self.assertEqual(data["phone"], "02111111111")
        self.assertTrue(data["has_contact_phone"])

    def test_contact_sheet_only_lists_dedicated_store_phone(self):
        self.footer.phone = "02111111111"
        self.footer.save(update_fields=["phone", "updated_at"])
        self.store.phone = ""
        self.store.save(update_fields=["phone", "updated_at"])
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "contact-phone-row")

        self.store.phone = "09123456789"
        self.store.save(update_fields=["phone", "updated_at"])
        response = self.client.get(reverse("home"))
        self.assertContains(response, "contact-phone-row")
        self.assertContains(response, "tel:09123456789")


class InstallerV9Tests(TestCase):
    def test_fresh_install_prompts_for_resend_not_gmail(self):
        script = (Path(settings.BASE_DIR) / "install-site.sh").read_text(encoding="utf-8")
        self.assertIn("smtp.resend.com", script)
        self.assertIn("RESEND_API_KEY", script)
        self.assertIn("RESEND_DOMAIN", script)
        self.assertNotIn("smtp.gmail.com", script)
