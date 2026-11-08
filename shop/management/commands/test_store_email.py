"""Diagnose Resend HTTPS connectivity and optionally send one test email safely."""
import socket
import ssl
from email.utils import parseaddr

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email


class Command(BaseCommand):
    help = "Check mail settings/HTTPS and explicitly send one test email with --to."

    def add_arguments(self, parser):
        parser.add_argument("--to", default="", help="Recipient address for a real test")
        parser.add_argument(
            "--diagnose", action="store_true",
            help="Only check safe configuration/DNS/TLS without sending an email",
        )

    def handle(self, *args, **options):
        provider = getattr(settings, "EMAIL_PROVIDER", "smtp")
        sender = parseaddr(settings.DEFAULT_FROM_EMAIL)[1]
        expected = str(getattr(settings, "RESEND_SENDING_DOMAIN", "") or "").strip().lower()
        api_key_present = bool(str(getattr(settings, "RESEND_API_KEY", "") or "").strip())

        self.stdout.write(f"Email provider: {provider}")
        self.stdout.write(f"Sender: {sender or '(missing)'}")
        if expected:
            self.stdout.write(f"Configured Resend domain: {expected}")
            if sender and sender.rsplit("@", 1)[-1].lower() != expected:
                raise CommandError("Sender domain does not match configured verified Resend domain")
        self.stdout.write(f"Resend key configured: {'yes' if api_key_present else 'no'}")

        if provider == "resend_api" and not api_key_present:
            raise CommandError("Missing RESEND_API_KEY in site environment")

        if options["diagnose"]:
            if provider == "resend_api":
                try:
                    with socket.create_connection(("api.resend.com", 443), timeout=8) as raw:
                        with ssl.create_default_context().wrap_socket(
                            raw, server_hostname="api.resend.com"
                        ) as secure:
                            self.stdout.write("api.resend.com:443 DNS/TCP/TLS: OK")
                except (OSError, ssl.SSLError) as exc:
                    raise CommandError(
                        f"api.resend.com:443 connection failed: {type(exc).__name__}; "
                        "check Iranian VPS outbound HTTPS/DNS"
                    ) from None
            self.stdout.write("No email was sent (diagnostic mode).")
            return

        recipient = options["to"].strip()
        if not recipient:
            raise CommandError("Pass --to your-email@example.com for a real test, or --diagnose")
        try:
            validate_email(recipient)
        except ValidationError as exc:
            raise CommandError("Invalid test email recipient") from exc

        self.stdout.write("Sending exactly one test email...")
        try:
            count = send_mail(
                "SanaShop: email delivery test",
                "This message tests email submission. Check the recipient inbox and Resend Logs for delivery.",
                settings.DEFAULT_FROM_EMAIL,
                [recipient],
                fail_silently=False,
            )
        except Exception as exc:
            # Our HTTPS backend never includes the API key or user payload in
            # its error text. Other backends may do so; show only class for those.
            from shop.resend_backend import ResendDeliveryError
            detail = str(exc) if isinstance(exc, ResendDeliveryError) else type(exc).__name__
            raise CommandError(f"Email submission failed: {detail}") from None
        if count != 1:
            raise CommandError("Email was not accepted for submission")
        self.stdout.write(self.style.SUCCESS(
            "Submission accepted; now verify actual delivery in Resend Emails/Logs and recipient inbox."
        ))
