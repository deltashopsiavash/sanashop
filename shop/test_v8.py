import json
import os
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .extra_models import CustomerProfile, EmailVerificationCode

User = get_user_model()


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class V8AccountEmailTests(TestCase):
    def setUp(self):
        self.client = Client()

    def test_otp_email_has_centered_html_code(self):
        self.client.post(reverse("login"), {"email": "buyer@example.com"})
        response = self.client.post(reverse("register"), {
            "first_name": "سارا",
            "last_name": "احمدی",
            "phone": "09123456789",
            "email": "buyer@example.com",
            "password1": "SafePassword-12345",
            "password2": "SafePassword-12345",
            "accept_terms": "on",
        })
        self.assertRedirects(response, reverse("verify_email_code"))
        user = User.objects.get(email="buyer@example.com")
        otp = EmailVerificationCode.objects.get(user=user)
        self.assertEqual(len(mail.outbox), 1)
        self.assertTrue(mail.outbox[0].alternatives)
        html = mail.outbox[0].alternatives[0].content
        self.assertIn(otp.code, html)
        self.assertIn("font-size:36px", html)
        self.assertIn("font-weight:900", html)

    def test_customer_can_change_phone_but_email_stays_unchanged(self):
        user = User.objects.create_user(username="buyer@example.com", email="buyer@example.com", password="test-pass", is_active=True)
        profile = CustomerProfile.ensure(user, "09120000000")
        self.client.force_login(user)
        response = self.client.post(reverse("account_profile"), {"phone": "09121112222", "email": "changed@example.com"})
        self.assertRedirects(response, reverse("account_profile"))
        user.refresh_from_db()
        profile.refresh_from_db()
        self.assertEqual(profile.phone, "09121112222")
        self.assertEqual(user.email, "buyer@example.com")

    def test_normal_password_reset_contains_html_button(self):
        User.objects.create_user(username="buyer@example.com", email="buyer@example.com", password="test-pass", is_active=True)
        response = self.client.post(reverse("password_reset"), {"email": "buyer@example.com"})
        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertTrue(mail.outbox[0].alternatives)
        html = mail.outbox[0].alternatives[0].content
        self.assertIn("تغییر رمز عبور", html)
        self.assertIn("/account/password-reset/", html)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class V8BotAdminTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.headers = {"HTTP_AUTHORIZATION": "Bearer test-api-key"}
        self.env = patch.dict(os.environ, {"SANASHOP_BOT_API_KEY": "test-api-key"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.user = User.objects.create_user(
            username="buyer@example.com",
            email="buyer@example.com",
            first_name="سارا",
            last_name="احمدی",
            password="test-pass",
            is_active=True,
        )
        self.profile = CustomerProfile.ensure(self.user, "09120000000")

    def api(self, action, payload=None):
        return self.client.post(
            reverse("bot_api_v1"),
            data=json.dumps({"action": action, "payload": payload or {}}),
            content_type="application/json",
            **self.headers,
        )

    def test_manager_can_change_customer_email_and_phone(self):
        response = self.api("user_update", {"id": self.user.id, "email": "new@example.com", "phone": "09123334444"})
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.profile.refresh_from_db()
        self.assertEqual(self.user.email, "new@example.com")
        self.assertEqual(self.user.username, "new@example.com")
        self.assertEqual(self.profile.phone, "09123334444")

    def test_manager_reset_email_is_html_button(self):
        response = self.api("user_password_reset", {"id": self.user.id})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertTrue(mail.outbox[0].alternatives)
        html = mail.outbox[0].alternatives[0].content
        self.assertIn("تغییر رمز عبور", html)
        self.assertIn("/account/password-reset/", html)

    def test_manager_can_send_broadcast_email(self):
        User.objects.create_user(username="two@example.com", email="two@example.com", password="pass", is_active=True)
        response = self.api("broadcast_email", {"subject": "خبر فروشگاه", "body": "یک پیام آزمایشی برای همه کاربران"})
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["recipients"], 2)
        self.assertEqual(data["sent"], 2)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(len(mail.outbox[0].bcc), 2)
        self.assertTrue(mail.outbox[0].alternatives)
