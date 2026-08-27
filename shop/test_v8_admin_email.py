import json
import os
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .emailing import send_otp_email
from .extra_models import CustomerProfile, EmailVerificationCode
from .models import SiteSetting

User = get_user_model()


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class V8CustomerAndEmailTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="buyer@example.com",
            email="buyer@example.com",
            first_name="سارا",
            last_name="احمدی",
            password="SafePassword-12345",
            is_active=True,
        )
        self.profile = CustomerProfile.ensure(self.user, "09121234567")
        self.env = patch.dict(os.environ, {"SANASHOP_BOT_API_KEY": "test-api-key", "DOMAIN": "example.com"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.api_headers = {"HTTP_AUTHORIZATION": "Bearer test-api-key"}

    def api(self, action, payload=None):
        return self.client.post(
            reverse("bot_api_v1"),
            data=json.dumps({"action": action, "payload": payload or {}}),
            content_type="application/json",
            **self.api_headers,
        )

    def test_customer_can_change_only_phone_from_profile(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("account_profile"), {"phone": "09123334455"})
        self.assertRedirects(response, reverse("account_profile"))
        self.profile.refresh_from_db()
        self.user.refresh_from_db()
        self.assertEqual(self.profile.phone, "09123334455")
        self.assertEqual(self.user.email, "buyer@example.com")

    def test_manager_api_can_change_customer_email_and_phone(self):
        response = self.api("user_update", {
            "id": self.user.id,
            "email": "newbuyer@example.com",
            "phone": "09125556677",
        })
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.profile.refresh_from_db()
        self.assertEqual(self.user.email, "newbuyer@example.com")
        self.assertEqual(self.user.username, "newbuyer@example.com")
        self.assertEqual(self.profile.phone, "09125556677")

    def test_manager_password_reset_sends_html_button(self):
        response = self.api("user_password_reset", {"id": self.user.id})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, [self.user.email])
        html_parts = [body for body, mimetype in message.alternatives if mimetype == "text/html"]
        self.assertTrue(html_parts)
        html = html_parts[0]
        self.assertIn("تغییر رمز عبور", html)
        self.assertIn("account/password-reset/", html)

    def test_otp_email_has_large_centered_code(self):
        store = SiteSetting.load()
        store.site_name = "VELORA"
        store.save()
        otp = EmailVerificationCode.issue(self.user)
        send_otp_email(self.user, otp)
        self.assertEqual(len(mail.outbox), 1)
        html_parts = [body for body, mimetype in mail.outbox[0].alternatives if mimetype == "text/html"]
        self.assertTrue(html_parts)
        html = html_parts[0]
        self.assertIn(otp.code, html)
        self.assertIn("font-size:36px", html)
        self.assertIn("font-weight:900", html)
        self.assertIn("text-align:center", html)

    def test_broadcast_email_uses_bcc_for_customer_privacy(self):
        second = User.objects.create_user(
            username="second@example.com",
            email="second@example.com",
            password="SafePassword-12345",
            is_active=True,
        )
        CustomerProfile.ensure(second, "09129998877")
        response = self.api("broadcast_email", {"subject": "خبر جدید", "body": "پیام تست فروشگاه"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["recipients"], 2)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [])
        self.assertCountEqual(mail.outbox[0].bcc, ["buyer@example.com", "second@example.com"])
