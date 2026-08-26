import re

from django.contrib import messages
from django.contrib.auth import authenticate, get_user_model, login
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.db.models import Q, Sum
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme

from .extra_models import CustomerProfile, EmailVerificationCode
from .forms import EmailLookupForm, PasswordOnlyForm, RegistrationForm
from .models import SiteSetting

User = get_user_model()


def _user_for_email(email):
    return User.objects.filter(Q(email__iexact=email) | Q(username__iexact=email)).first()


def _safe_account_target(request):
    target = request.session.pop("account_next", "")
    if target and url_has_allowed_host_and_scheme(
        target,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return target
    return "account_home"


def _normalize_code(value):
    value = str(value or "").strip()
    fa = "۰۱۲۳۴۵۶۷۸۹"
    ar = "٠١٢٣٤٥٦٧٨٩"
    value = value.translate(str.maketrans(fa + ar, "0123456789" * 2))
    return re.sub(r"\D", "", value)[:6]


def _send_otp(user, otp):
    store = SiteSetting.load()
    send_mail(
        f"کد تأیید عضویت در {store.site_name}",
        (
            f"کد تأیید ایمیل شما: {otp.code}\n\n"
            "این کد ۱۰ دقیقه معتبر است.\n"
            "اگر شما درخواست ثبت‌نام نداده‌اید، این پیام را نادیده بگیرید."
        ),
        None,
        [user.email],
        fail_silently=False,
    )


def account_entry(request):
    if request.user.is_authenticated:
        return redirect("account_home")
    next_url = request.GET.get("next") or request.POST.get("next") or request.session.get("account_next", "")
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        request.session["account_next"] = next_url
    form = EmailLookupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"]
        request.session["account_email"] = email
        user = _user_for_email(email)
        if user:
            if not user.is_active:
                request.session["pending_verification_user_id"] = user.id
                otp = EmailVerificationCode.objects.filter(user=user).first()
                if not otp or otp.is_expired:
                    otp = EmailVerificationCode.issue(user)
                    try:
                        _send_otp(user, otp)
                    except Exception:
                        messages.error(request, "ارسال کد تأیید ممکن نشد؛ چند دقیقه بعد دوباره تلاش کنید.")
                return redirect("verify_email_code")
            return redirect("account_password")
        return redirect("register")
    return render(request, "registration/login.html", {"form": form, "next": next_url})


def account_password(request):
    if request.user.is_authenticated:
        return redirect("account_home")
    email = (request.session.get("account_email") or "").strip().lower()
    if not email:
        return redirect("login")
    user_record = _user_for_email(email)
    if not user_record:
        return redirect("register")
    if not user_record.is_active:
        request.session["pending_verification_user_id"] = user_record.id
        return redirect("verify_email_code")
    form = PasswordOnlyForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = authenticate(request, username=user_record.username, password=form.cleaned_data["password"])
        if user is not None:
            login(request, user)
            request.session.pop("account_email", None)
            return redirect(_safe_account_target(request))
        form.add_error("password", "رمز عبور نادرست است.")
    return render(request, "registration/login_password.html", {"form": form, "email": email})


def register(request):
    if request.user.is_authenticated:
        return redirect("account_home")
    email = (request.session.get("account_email") or "").strip().lower()
    if not email:
        return redirect("login")
    existing = _user_for_email(email)
    if existing:
        if not existing.is_active:
            request.session["pending_verification_user_id"] = existing.id
            return redirect("verify_email_code")
        return redirect("account_password")

    form = RegistrationForm(request.POST or None, fixed_email=email)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        otp = EmailVerificationCode.issue(user)
        try:
            _send_otp(user, otp)
        except Exception:
            user.delete()
            form.add_error(None, "ارسال کد تأیید ممکن نشد؛ تنظیمات ایمیل فروشگاه را بررسی کنید.")
        else:
            request.session["pending_verification_user_id"] = user.id
            request.session["account_email"] = user.email
            return redirect("verify_email_code")
    return render(request, "registration/register.html", {"form": form, "registration_email": email})


def verify_email_code(request):
    if request.user.is_authenticated:
        return redirect("account_home")

    user_id = request.session.get("pending_verification_user_id")
    user = User.objects.filter(pk=user_id).first() if user_id else None
    if not user:
        email = (request.session.get("account_email") or "").strip().lower()
        user = _user_for_email(email) if email else None
    if not user:
        messages.error(request, "درخواست تأیید ایمیل پیدا نشد. دوباره وارد شوید.")
        return redirect("login")
    if user.is_active:
        request.session.pop("pending_verification_user_id", None)
        return redirect("account_password")

    otp = EmailVerificationCode.objects.filter(user=user).first()
    if not otp:
        otp = EmailVerificationCode.issue(user)
        try:
            _send_otp(user, otp)
        except Exception:
            messages.error(request, "ارسال کد تأیید ممکن نشد.")

    if request.method == "POST" and request.POST.get("action") == "resend":
        now = timezone.now()
        seconds = int((now - otp.last_sent_at).total_seconds()) if otp else 61
        if seconds < 60:
            messages.warning(request, f"برای ارسال دوباره {60 - seconds} ثانیه صبر کنید.")
        else:
            otp = EmailVerificationCode.issue(user)
            try:
                _send_otp(user, otp)
                messages.success(request, "کد جدید ارسال شد.")
            except Exception:
                messages.error(request, "ارسال کد جدید ممکن نشد.")
        return redirect("verify_email_code")

    error = ""
    if request.method == "POST":
        code = _normalize_code(request.POST.get("code"))
        otp = EmailVerificationCode.objects.filter(user=user).first()
        if not otp:
            error = "کد تأیید پیدا نشد؛ درخواست ارسال مجدد بدهید."
        elif otp.is_expired:
            error = "کد تأیید منقضی شده است؛ کد جدید دریافت کنید."
        elif otp.attempts >= 6:
            error = "تعداد تلاش‌های ناموفق زیاد شده است؛ کد جدید دریافت کنید."
        elif len(code) != 6 or not otp.matches(code):
            otp.attempts += 1
            otp.save(update_fields=["attempts", "updated_at"])
            error = "کد تأیید نادرست است."
        else:
            user.is_active = True
            user.save(update_fields=["is_active"])
            CustomerProfile.ensure(user)
            otp.delete()
            request.session.pop("pending_verification_user_id", None)
            request.session.pop("account_email", None)
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            messages.success(request, "ایمیل شما تأیید شد و حساب فعال شد.")
            return redirect(_safe_account_target(request))

    return render(
        request,
        "registration/verification_sent.html",
        {
            "email": user.email,
            "verification_error": error,
            "otp_expires_at": otp.expires_at if otp else None,
        },
    )


@login_required
def account_home(request):
    profile = CustomerProfile.ensure(request.user)
    active_statuses = ["pending", "review", "rejected", "paid", "processing", "shipped"]
    orders = request.user.orders.all()
    return render(
        request,
        "shop/account_home.html",
        {
            "customer_profile": profile,
            "orders_count": orders.count(),
            "active_orders_count": orders.filter(status__in=active_statuses).count(),
        },
    )


@login_required
def account_profile(request):
    profile = CustomerProfile.ensure(request.user)
    orders = request.user.orders.all()
    paid_statuses = ["paid", "processing", "shipped", "delivered"]
    return render(
        request,
        "shop/account_profile.html",
        {
            "user_profile": request.user,
            "customer_profile": profile,
            "orders_count": orders.count(),
            "active_orders_count": orders.exclude(status__in=["delivered", "cancelled"]).count(),
            "total_spent": orders.filter(status__in=paid_statuses).aggregate(total=Sum("total"))["total"] or 0,
        },
    )
