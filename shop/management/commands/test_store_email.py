"""Send one explicit test email without printing provider credentials or OTPs."""
from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.core.exceptions import ValidationError


class Command(BaseCommand):
    help = "Test the configured email transport with one test message (requires --to)."

    def add_arguments(self, parser):
        parser.add_argument("--to", required=True, help="Recipient address for the test email")

    def handle(self, *args, **options):
        recipient = options["to"].strip()
        try:
            validate_email(recipient)
        except ValidationError as exc:
            raise CommandError("Invalid test email recipient") from exc
        provider = getattr(settings, "EMAIL_PROVIDER", "smtp")
        if provider == "resend_api" and not getattr(settings, "RESEND_API_KEY", ""):
            raise CommandError("Missing RESEND_API_KEY in site environment")
        self.stdout.write(f"Email transport: {provider}; trying one message...")
        try:
            count = send_mail(
                "SanaShop: email delivery test",
                "This test confirms the site requested email delivery. Check inbox and Resend Logs for final status.",
                settings.DEFAULT_FROM_EMAIL,
                [recipient],
                fail_silently=False,
            )
        except Exception as exc:
            raise CommandError(f"Email submission failed: {exc.__class__.__name__}: {exc}") from None
        if count != 1:
            raise CommandError("Email was not submitted")
        self.stdout.write(self.style.SUCCESS(
            "Message accepted for submission; confirm delivery status in Resend Logs and recipient inbox."
        ))
