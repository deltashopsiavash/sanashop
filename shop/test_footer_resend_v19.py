import io
import json
import os
from unittest.mock import patch
from urllib.error import HTTPError

from django.contrib.auth import get_user_model
from django.core.mail import EmailMultiAlternatives, get_connection
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .emailing import send_otp_email
from .extra_models import EmailVerificationCode, FooterSetting
from .models import ContentPage, SiteSetting
from .resend_backend import ResendDeliveryError


class FooterContactNavigationTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.env = patch.dict(os.environ, {"SANASHOP_BOT_API_KEY": "test-store-key"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def api(self, payload):
        return self.client.post(
            reverse("bot_api_v1"),
            data=json.dumps({"action": "settings_update", "payload": payload}),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer test-store-key",
        )

    def test_footer_phone_is_same_as_header_modal_and_contact_page(self):
        result = self.api({"phone": "02155551122"})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(SiteSetting.load().phone, "02155551122")
        self.assertEqual(FooterSetting.load().phone, "02155551122")
        home = self.client.get(reverse("home"))
        self.assertContains(home, 'tel:02155551122', count=3)
        contact = self.client.get(reverse("content_page", args=["contact"]))
        self.assertEqual(contact.status_code, 200)
        self.assertContains(contact, "tel:02155551122")

    def test_contact_phone_updates_legacy_footer_and_public_view(self):
        first = self.api({"phone": "02133330000"})
        self.assertEqual(first.status_code, 200)
        second = self.api({"contact_phone": "09121112233"})
        self.assertEqual(second.status_code, 200)
        self.assertEqual(FooterSetting.load().phone, "09121112233")
        self.assertEqual(SiteSetting.load().phone, "09121112233")
        home = self.client.get(reverse("home"))
        self.assertContains(home, "tel:09121112233")
        self.assertNotContains(home, "tel:02133330000")

    def test_header_falls_back_to_old_contact_number(self):
        SiteSetting.load().phone = "02170001234"
        SiteSetting.load().save()
        self.assertContains(self.client.get(reverse("home")), "tel:02170001234")

    def test_all_footer_help_links_have_editable_pages(self):
        home = self.client.get(reverse("home"))
        for slug in ("terms", "contact", "faq"):
            path = reverse("content_page", args=[slug])
            self.assertContains(home, f'href="{path}"')
            self.assertEqual(self.client.get(path).status_code, 200)
            self.assertTrue(ContentPage.objects.filter(slug=slug, is_active=True).exists())
        self.assertContains(home, "<details", html=False)
        self.assertContains(home, "footer-nav-dropdown")


class FakeResponse:
    def __init__(self, payload=None):
        self.payload = payload if payload is not None else {"id": "test-accepted"}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


@override_settings(
    EMAIL_PROVIDER="resend_api",
    EMAIL_BACKEND="shop.resend_backend.ResendAPIEmailBackend",
    RESEND_API_KEY="re_test-secret-never-log",
    DEFAULT_FROM_EMAIL="Velora <support@mail.shop.example.com>",
)
class ResendHttpsBackendTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="test@example.com", email="test@example.com", password="test-password"
        )

    @patch("shop.resend_backend.urlopen", return_value=FakeResponse())
    def test_otp_html_email_uses_verified_sender_and_https_port(self, sender):
        otp = EmailVerificationCode.issue(self.user)
        send_otp_email(self.user, otp)
        request = sender.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(request.full_url, "https://api.resend.com/emails")
        self.assertEqual(payload["to"], [self.user.email])
        self.assertIn(otp.code, payload["html"])
        self.assertIn("کد تأیید", payload["subject"])
        self.assertEqual(payload["from"], "Velora <support@mail.shop.example.com>")
        self.assertEqual(request.get_header("Authorization"), "Bearer re_test-secret-never-log")

    @patch("shop.resend_backend.urlopen", return_value=FakeResponse({"data": [{"id": "1"}, {"id": "2"}]}))
    def test_bcc_only_broadcast_sends_individual_private_batch(self, sender):
        message = EmailMultiAlternatives(
            "خبرنامه", "متن", None, [], bcc=["one@example.com", "two@example.com"]
        )
        self.assertEqual(get_connection().send_messages([message]), 1)
        request = sender.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.resend.com/emails/batch")
        batch = json.loads(request.data)
        self.assertEqual([item["to"] for item in batch], [["one@example.com"], ["two@example.com"]])
        self.assertTrue(all("bcc" not in item for item in batch))

    @patch("shop.resend_backend.urlopen")
    def test_api_forbidden_error_is_explicit_and_does_not_show_key(self, sender):
        sender.side_effect = HTTPError(
            "https://api.resend.com/emails", 403, "Forbidden", {},
            io.BytesIO(b'{"name":"restricted_access"}')
        )
        msg = EmailMultiAlternatives("تست", "متن تست", None, ["recipient@example.com"])
        with self.assertRaises(ResendDeliveryError) as exc:
            get_connection().send_messages([msg])
        self.assertIn("HTTP 403", str(exc.exception))
        self.assertIn("restricted_access", str(exc.exception))
        self.assertNotIn("re_test-secret-never-log", str(exc.exception))
