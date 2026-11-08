import io
import json
from unittest.mock import patch
from urllib.error import HTTPError

from django.contrib.auth import get_user_model
from django.core.mail import EmailMultiAlternatives, get_connection
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .extra_models import EmailVerificationCode
from .resend_backend import ResendDeliveryError


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return b'{"id":"message-accepted"}'


@override_settings(
    EMAIL_BACKEND="shop.resend_backend.ResendAPIEmailBackend",
    EMAIL_PROVIDER="resend_api",
    RESEND_API_KEY="re-test-secret-never-output",
    DEFAULT_FROM_EMAIL="Shop <support@mail.example.com>",
)
class ResendReliabilityTests(TestCase):
    @patch("shop.resend_backend.urlopen", return_value=FakeResponse())
    def test_user_agent_and_real_resend_message_id(self, call):
        message = EmailMultiAlternatives("Code", "123456", None, ["user@example.com"])
        self.assertEqual(get_connection().send_messages([message]), 1)
        sent = call.call_args.args[0]
        self.assertEqual(sent.get_header("User-agent"), "SanaShop-Store/1.0")
        self.assertEqual(sent.full_url, "https://api.resend.com/emails")
        self.assertEqual(json.loads(sent.data)["from"], "Shop <support@mail.example.com>")

    @patch("shop.resend_backend.urlopen")
    def test_sanitize_403_authorization_error(self, call):
        call.side_effect = HTTPError(
            "https://api.resend.com/emails", 403, "Forbidden", {},
            io.BytesIO(b'{"name":"authorization_error","message":"Authorization required"}'),
        )
        with self.assertRaises(ResendDeliveryError) as ex:
            get_connection().send_messages([
                EmailMultiAlternatives("Code", "hello", None, ["user@example.com"])
            ])
        self.assertIn("HTTP 403", str(ex.exception))
        self.assertNotIn("re-test-secret-never-output", str(ex.exception))

    @patch("shop.resend_backend.urlopen")
    def test_reject_false_success_without_message_id(self, call):
        class EmptyResponse:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self):
                return b'{}'
        call.return_value = EmptyResponse()
        with self.assertRaises(ResendDeliveryError):
            get_connection().send_messages([
                EmailMultiAlternatives("Code", "hello", None, ["user@example.com"])
            ])


class OTPFailureRecoveryTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="inactive@example.com", email="inactive@example.com",
            password="pass-secure-123", is_active=False,
        )
        self.otp = EmailVerificationCode.issue(self.user)

    @patch("shop.account_views._send_otp", side_effect=RuntimeError("provider offline"))
    def test_failed_resend_does_not_lock_customer_out_for_sixty_seconds(self, sending):
        self.otp.last_sent_at = timezone.now() - __import__("datetime").timedelta(seconds=65)
        self.otp.save(update_fields=["last_sent_at", "updated_at"])
        session = self.client.session
        session["pending_verification_user_id"] = self.user.pk
        session["account_email"] = self.user.email
        session.save()
        response = self.client.post(reverse("verify_email_code"), {"action": "resend"})
        self.assertRedirects(response, reverse("verify_email_code"))
        self.otp.refresh_from_db()
        self.assertGreaterEqual((timezone.now() - self.otp.last_sent_at).total_seconds(), 60)
        self.assertTrue(get_user_model().objects.filter(pk=self.user.pk).exists())
        self.assertEqual(sending.call_count, 1)
