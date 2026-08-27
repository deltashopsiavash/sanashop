import os
from html import escape
from urllib.parse import urljoin

from django.conf import settings
from django.contrib.auth.forms import PasswordResetForm
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from .models import SiteSetting


def _from_email():
    return getattr(settings, "DEFAULT_FROM_EMAIL", None) or None


def _public_base_url(request=None):
    if request is not None:
        return request.build_absolute_uri("/")

    domain = str(os.environ.get("DOMAIN") or "").strip().strip("/")
    if domain:
        return f"https://{domain}/"

    for host in getattr(settings, "ALLOWED_HOSTS", []):
        host = str(host or "").strip()
        if host and host not in {"localhost", "127.0.0.1"} and "*" not in host:
            scheme = "http" if settings.DEBUG else "https"
            return f"{scheme}://{host}/"
    return ""


def email_brand_context(request=None):
    """Return a safe email-brand context with an absolute public logo URL."""
    store = SiteSetting.load()
    logo_url = ""
    if store.logo:
        try:
            path = store.logo.url
        except ValueError:
            path = ""
        if path:
            base = _public_base_url(request=request)
            if base:
                logo_url = urljoin(base, path)
    return {"store": store, "logo_url": logo_url}


def send_otp_email(user, otp):
    context = email_brand_context()
    store = context["store"]
    subject = f"کد تأیید عضویت در {store.site_name}"
    text = (
        f"کد تأیید ایمیل شما: {otp.code}\n\n"
        "این کد ۱۰ دقیقه معتبر است.\n"
        "اگر شما درخواست ثبت‌نام نداده‌اید، این پیام را نادیده بگیرید."
    )
    context.update(user=user, code=otp.code)
    html = render_to_string("emails/otp.html", context)
    message = EmailMultiAlternatives(subject, text, _from_email(), [user.email])
    message.attach_alternative(html, "text/html")
    message.send(fail_silently=False)


def send_password_reset_email(request, user):
    form = PasswordResetForm({"email": user.email})
    if not form.is_valid():
        raise ValueError("invalid_reset_email")
    form.save(
        request=request,
        use_https=request.is_secure(),
        from_email=_from_email(),
        email_template_name="registration/password_reset_email.txt",
        html_email_template_name="emails/password_reset.html",
        subject_template_name="registration/password_reset_subject.txt",
        extra_email_context=email_brand_context(request=request),
    )


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

    context = email_brand_context()
    store = context["store"]
    subject = str(subject or "").strip()[:180]
    body = str(body or "").strip()
    safe_body = escape(body).replace("\n", "<br>")
    context["body_html"] = safe_body
    html = render_to_string("emails/broadcast.html", context)
    text = body
    sent = 0
    # BCC batches protect customer privacy and avoid exposing the mailing list.
    for index in range(0, len(addresses), 60):
        batch = addresses[index:index + 60]
        message = EmailMultiAlternatives(subject, text, _from_email(), [], bcc=batch)
        message.attach_alternative(html, "text/html")
        if message.send(fail_silently=False):
            sent += len(batch)
    return sent
