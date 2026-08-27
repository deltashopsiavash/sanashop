from html import escape

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from .models import SiteSetting


def _from_email():
    return getattr(settings, "DEFAULT_FROM_EMAIL", None) or None


def send_otp_email(user, otp):
    store = SiteSetting.load()
    subject = f"کد تأیید عضویت در {store.site_name}"
    text = (
        f"کد تأیید ایمیل شما: {otp.code}\n\n"
        "این کد ۱۰ دقیقه معتبر است.\n"
        "اگر شما درخواست ثبت‌نام نداده‌اید، این پیام را نادیده بگیرید."
    )
    html = render_to_string("emails/otp.html", {"store": store, "user": user, "code": otp.code})
    message = EmailMultiAlternatives(subject, text, _from_email(), [user.email])
    message.attach_alternative(html, "text/html")
    message.send(fail_silently=False)


def build_password_reset_url(request, user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    path = reverse("password_reset_confirm", kwargs={"uidb64": uid, "token": token})
    return request.build_absolute_uri(path)


def send_password_reset_email(request, user):
    store = SiteSetting.load()
    reset_url = build_password_reset_url(request, user)
    subject = f"بازیابی رمز عبور {store.site_name}"
    text = (
        f"برای ساخت رمز عبور جدید از لینک زیر استفاده کنید:\n\n{reset_url}\n\n"
        "اگر شما این درخواست را نداده‌اید، این ایمیل را نادیده بگیرید."
    )
    html = render_to_string(
        "emails/password_reset.html",
        {"store": store, "user": user, "reset_url": reset_url},
    )
    message = EmailMultiAlternatives(subject, text, _from_email(), [user.email])
    message.attach_alternative(html, "text/html")
    message.send(fail_silently=False)
    return reset_url


def send_broadcast_email(subject, body, recipients):
    addresses = []
    seen = set()
    for value in recipients:
        email = str(value or "").strip().lower()
        if email and email not in seen:
            seen.add(email)
            addresses.append(email)
    if not addresses:
        return 0

    store = SiteSetting.load()
    subject = str(subject or "").strip()[:180]
    body = str(body or "").strip()
    safe_body = escape(body).replace("\n", "<br>")
    html = render_to_string(
        "emails/broadcast.html",
        {"store": store, "body_html": safe_body},
    )
    text = body
    sent = 0
    # BCC batches protect customer privacy and avoid exposing the mailing list.
    for index in range(0, len(addresses), 60):
        batch = addresses[index:index + 60]
        message = EmailMultiAlternatives(subject, text, _from_email(), [], bcc=batch)
        message.attach_alternative(html, "text/html")
        sent += message.send(fail_silently=False) * len(batch)
    return sent
