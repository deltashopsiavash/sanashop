from django.contrib import messages
from django.contrib.auth import authenticate, get_user_model, login
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.db.models import Q
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .forms import CheckoutForm, EmailLookupForm, PasswordOnlyForm, ReceiptForm, RegistrationForm
from .iran_locations import province_city_map
from .models import Category, ContentPage, EmailVerificationToken, HeroSlide, Order, PaymentReceipt, Product, SiteSetting
from .services import (
    cart_rows,
    create_order,
    discount_from_session,
    expire_reservations,
    order_event_payload,
    queue_bot_event,
    release_order_stock,
    send_receipt_to_telegram,
    set_order_status,
    zarinpal_request,
    zarinpal_verify,
)

User = get_user_model()


def _user_for_email(email):
    return User.objects.filter(Q(email__iexact=email) | Q(username__iexact=email)).first()


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
        if _user_for_email(email):
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
    form = PasswordOnlyForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = authenticate(request, username=user_record.username, password=form.cleaned_data["password"])
        if user is not None:
            login(request, user)
            request.session.pop("account_email", None)
            target = request.session.pop("account_next", "")
            if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
                return redirect(target)
            return redirect("account_home")
        if not user_record.is_active:
            form.add_error("password", "این حساب ساخته شده اما ایمیل هنوز تأیید نشده است. ایمیل تأیید را بررسی کنید.")
        else:
            form.add_error("password", "رمز عبور نادرست است.")
    return render(request, "registration/login_password.html", {"form": form, "email": email})


def register(request):
    if request.user.is_authenticated:
        return redirect("account_home")
    email = (request.session.get("account_email") or "").strip().lower()
    if not email:
        return redirect("login")
    if _user_for_email(email):
        return redirect("account_password")
    form = RegistrationForm(request.POST or None, fixed_email=email)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        token = EmailVerificationToken.issue(user)
        verify_url = request.build_absolute_uri(reverse("verify_email", args=[token.token]))
        try:
            send_mail(
                f"تأیید عضویت در {SiteSetting.load().site_name}",
                f"برای فعال‌سازی حساب خود روی لینک زیر بزنید:\n\n{verify_url}\n\nاین لینک ۲۴ ساعت معتبر است.",
                None,
                [user.email],
                fail_silently=False,
            )
        except Exception:
            user.delete()
            form.add_error(None, "ارسال ایمیل ممکن نشد؛ تنظیمات ایمیل فروشگاه هنوز کامل نیست.")
        else:
            request.session.pop("account_email", None)
            return render(request, "registration/verification_sent.html", {"email": user.email})
    return render(request, "registration/register.html", {"form": form, "registration_email": email})


def verify_email(request, token):
    record = get_object_or_404(EmailVerificationToken.objects.select_related("user"), token=token)
    if record.expires_at < timezone.now():
        record.user.delete()
        messages.error(request, "لینک فعال‌سازی منقضی شده است؛ دوباره ثبت‌نام کنید.")
        return redirect("register")
    user = record.user
    user.is_active = True
    user.save(update_fields=["is_active"])
    record.delete()
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    messages.success(request, "ایمیل تأیید شد و حساب شما فعال است.")
    target = request.session.pop("account_next", "")
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return redirect(target)
    return redirect("account_home")


@login_required
def account_home(request):
    return render(request, "shop/account_home.html")


@login_required
def account_profile(request):
    return render(request, "shop/account_profile.html", {"user_profile": request.user})


@login_required
def my_orders(request):
    expire_reservations(limit=50)
    orders = request.user.orders.prefetch_related("items", "status_events").all()
    return render(request, "shop/my_orders.html", {"orders": orders})


def home(request):
    expire_reservations(limit=30)
    now = timezone.now()
    amazing = (
        Product.objects.filter(is_active=True, is_amazing=True)
        .filter(Q(amazing_until__isnull=True) | Q(amazing_until__gt=now))
        .select_related("category")[:10]
    )
    return render(
        request,
        "shop/home.html",
        {
            "featured": Product.objects.filter(is_active=True, is_featured=True).select_related("category")[:8],
            "newest": Product.objects.filter(is_active=True).select_related("category").order_by("-created_at")[:8],
            "amazing": amazing,
            "categories": Category.objects.filter(is_active=True, parent__isnull=True)[:12],
            "hero_slides": HeroSlide.objects.filter(is_active=True)[:8],
        },
    )


def safe_next(request, fallback):
    target = request.POST.get("next", "")
    return target if url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()) else fallback


def catalog(request, category_slug=None):
    products = Product.objects.filter(is_active=True).select_related("category")
    category = None
    if category_slug:
        category = get_object_or_404(Category, slug=category_slug, is_active=True)
        products = products.filter(category__in=[category, *category.children.filter(is_active=True)])
    query = request.GET.get("q", "").strip()
    if query:
        products = products.filter(Q(name__icontains=query) | Q(sku__icontains=query) | Q(description__icontains=query))
    sort = request.GET.get("sort", "new")
    products = products.order_by({"cheap": "price", "expensive": "-price", "new": "-created_at"}.get(sort, "-created_at"))
    return render(request, "shop/catalog.html", {"products": products, "category": category, "query": query, "sort": sort})


def product_detail(request, slug):
    product = get_object_or_404(Product.objects.select_related("category").prefetch_related("gallery"), slug=slug, is_active=True)
    related = Product.objects.filter(category=product.category, is_active=True).exclude(pk=product.pk)[:4]
    return render(request, "shop/product.html", {"product": product, "related": related})


def _cart_context(request):
    rows, subtotal = cart_rows(request)
    store = SiteSetting.load()
    shipping = store.shipping_for(subtotal) if rows else 0
    discount, discount_amount = discount_from_session(request, subtotal)
    total = max(0, subtotal + shipping - discount_amount) if rows else 0
    threshold = int(store.free_shipping_threshold or 0)
    remaining = max(0, threshold - subtotal) if threshold else 0
    progress = 100 if threshold and subtotal >= threshold else (min(100, int(subtotal * 100 / threshold)) if threshold else 0)
    return {
        "rows": rows,
        "subtotal": subtotal,
        "shipping": shipping,
        "discount": discount,
        "discount_amount": discount_amount,
        "total": total,
        "free_shipping_threshold": threshold,
        "remaining_to_free_shipping": remaining,
        "free_shipping_progress": progress,
        "free_shipping": bool(rows and threshold and subtotal >= threshold),
    }


def _wants_json(request):
    return request.headers.get("x-requested-with") == "XMLHttpRequest" or "application/json" in request.headers.get("accept", "")


def _cart_json(request):
    data = _cart_context(request)
    return {
        "count": sum(row["quantity"] for row in data["rows"]),
        "subtotal": data["subtotal"],
        "shipping": data["shipping"],
        "discount_amount": data["discount_amount"],
        "total": data["total"],
        "free_shipping_threshold": data["free_shipping_threshold"],
        "remaining_to_free_shipping": data["remaining_to_free_shipping"],
        "free_shipping_progress": data["free_shipping_progress"],
        "free_shipping": data["free_shipping"],
        "lines": [
            {
                "id": row["product"].id,
                "quantity": row["quantity"],
                "stock": row["product"].available_stock,
                "total": row["total"],
            }
            for row in data["rows"]
        ],
    }


def cart(request):
    return render(request, "shop/cart.html", _cart_context(request))


def cart_data(request):
    return JsonResponse({"ok": True, **_cart_json(request)})


@require_POST
def cart_add(request, product_id):
    product = get_object_or_404(Product, pk=product_id, is_active=True)
    if not product.available:
        if _wants_json(request):
            return JsonResponse({"ok": False, "error": "این محصول در حال حاضر موجود نیست."}, status=400)
        messages.warning(request, "این محصول در حال حاضر موجود نیست.")
        return redirect(safe_next(request, reverse("catalog")))
    try:
        requested = int(request.POST.get("quantity", 1))
    except (TypeError, ValueError):
        requested = 1
    qty = min(max(1, requested), product.available_stock)
    data = request.session.get("cart", {})
    data[str(product.pk)] = min(int(data.get(str(product.pk), 0)) + qty, product.available_stock)
    request.session["cart"] = data
    request.session.modified = True
    if _wants_json(request):
        return JsonResponse({"ok": True, **_cart_json(request)})
    messages.success(request, f"«{product.name}» به سبد خرید اضافه شد.")
    return redirect(safe_next(request, reverse("cart")))


@require_POST
def cart_update(request, product_id):
    data = request.session.get("cart", {})
    product = get_object_or_404(Product, pk=product_id)
    try:
        requested = int(request.POST.get("quantity", request.POST.get("qty", 0)))
    except (TypeError, ValueError):
        requested = 0
    qty = max(0, min(requested, product.available_stock))
    if qty:
        data[str(product_id)] = qty
    else:
        data.pop(str(product_id), None)
    request.session["cart"] = data
    request.session.modified = True
    if _wants_json(request):
        return JsonResponse({"ok": True, **_cart_json(request)})
    return redirect("cart")


@require_POST
def discount_apply(request):
    rows, subtotal = cart_rows(request)
    if not rows:
        messages.warning(request, "سبد خرید خالی است.")
        return redirect("cart")
    code = (request.POST.get("discount_code") or "").strip().upper()
    from .models import DiscountCode

    discount = DiscountCode.objects.filter(code__iexact=code).first()
    if discount and discount.is_valid_for(subtotal):
        request.session["discount_code"] = discount.code
        messages.success(request, f"کد {discount.code} اعمال شد؛ {discount.percent}٪ تخفیف.")
    else:
        request.session.pop("discount_code", None)
        messages.error(request, "کد تخفیف معتبر نیست، منقضی شده یا شرایط سفارش را ندارد.")
    return redirect("cart")


@require_POST
def discount_remove(request):
    request.session.pop("discount_code", None)
    request.session.modified = True
    messages.success(request, "کد تخفیف حذف شد.")
    return redirect("cart")


@login_required
def checkout(request):
    totals = _cart_context(request)
    rows, subtotal = totals["rows"], totals["subtotal"]
    if not rows:
        messages.warning(request, "سبد خرید شما خالی است.")
        return redirect("catalog")
    store = SiteSetting.load()
    initial = {"full_name": request.user.first_name, "email": request.user.email}
    form = CheckoutForm(request.POST or None, store_settings=store, initial=initial)
    if request.method == "POST" and form.is_valid():
        try:
            order = create_order(
                form,
                rows,
                subtotal,
                store,
                customer=request.user,
                discount=totals["discount"],
                discount_amount=totals["discount_amount"],
            )
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect("cart")
        request.session["cart"] = {}
        request.session.pop("discount_code", None)
        request.session["order_code"] = order.code
        request.session.modified = True
        if order.payment_method == "zarinpal":
            try:
                callback = request.build_absolute_uri(reverse("zarinpal_callback"))
                return redirect(zarinpal_request(order, callback))
            except Exception as exc:
                order.admin_note = f"خطای شروع زرین‌پال: {exc}"
                order.save(update_fields=["admin_note", "updated_at"])
                release_order_stock(order)
                order.status = "cancelled"
                order.save(update_fields=["status", "updated_at"])
                queue_bot_event("payment_failed", order_event_payload(order))
                messages.error(request, "اتصال به درگاه ممکن نشد و رزرو سفارش آزاد شد. دوباره سفارش ثبت کنید.")
                return redirect("order_status", code=order.code)
        return redirect("card_payment", code=order.code)
    return render(request, "shop/checkout.html", {**totals, "form": form, "locations": province_city_map()})


def _can_view_order(request, order):
    return (
        (request.user.is_authenticated and order.customer_id == request.user.id)
        or request.session.get("order_code") == order.code
        or request.user.is_staff
    )


def card_payment(request, code):
    expire_reservations(limit=50)
    order = get_object_or_404(Order.objects.prefetch_related("items"), code=code, payment_method="card")
    if not _can_view_order(request, order):
        raise Http404
    if order.stock_committed or order.status in ("paid", "processing", "shipped", "delivered"):
        return redirect("order_status", code=order.code)
    if not order.reservation_active:
        messages.error(request, "مهلت رزرو این فاکتور تمام شده است. یک سفارش جدید ثبت کنید.")
        return redirect("order_status", code=order.code)

    receipt_form = ReceiptForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and receipt_form.is_valid():
        receipt, _ = PaymentReceipt.objects.update_or_create(
            order=order,
            defaults={"image": receipt_form.cleaned_data["image"], "status": "pending", "reviewed_at": None},
        )
        order.receipt_rejection_reason = ""
        order.save(update_fields=["receipt_rejection_reason", "updated_at"])
        set_order_status(order, "review", "رسید کارت‌به‌کارت برای بررسی ارسال شد")
        send_receipt_to_telegram(receipt)
        messages.success(request, "رسید با موفقیت ارسال شد و در انتظار بررسی مدیر است.")
        return redirect("order_status", code=order.code)
    return render(request, "shop/card_payment.html", {"order": order, "receipt_form": receipt_form, "store": SiteSetting.load()})


def order_status(request, code):
    expire_reservations(limit=50)
    order = get_object_or_404(Order.objects.prefetch_related("items", "status_events"), code=code)
    if not _can_view_order(request, order):
        raise Http404
    receipt_form = ReceiptForm()
    if request.method == "POST" and order.payment_method == "card":
        return redirect("card_payment", code=order.code)
    return render(request, "shop/order_status.html", {"order": order, "receipt_form": receipt_form})


def zarinpal_callback(request):
    authority = request.GET.get("Authority", "")
    order = get_object_or_404(Order, authority=authority, payment_method="zarinpal")
    request.session["order_code"] = order.code
    request.session.modified = True
    if order.stock_committed and order.status in ("paid", "processing", "shipped", "delivered"):
        messages.success(request, "این پرداخت قبلاً با موفقیت تأیید شده است.")
        return redirect("order_status", code=order.code)
    if request.GET.get("Status") != "OK":
        release_order_stock(order)
        order.status = "cancelled"
        order.save(update_fields=["status", "updated_at"])
        queue_bot_event("payment_failed", order_event_payload(order))
        messages.error(request, "پرداخت انجام نشد یا توسط شما لغو شد.")
        return redirect("order_status", code=order.code)
    try:
        verified = zarinpal_verify(order)
    except Exception as exc:
        release_order_stock(order)
        order.status = "cancelled"
        order.admin_note = f"خطای تایید زرین‌پال: {exc}"
        order.save(update_fields=["status", "admin_note", "updated_at"])
        queue_bot_event("payment_failed", order_event_payload(order))
        verified = False
    if verified:
        messages.success(request, f"پرداخت با موفقیت انجام شد. کد پیگیری: {order.payment_ref_id}")
    else:
        messages.error(request, "پرداخت ناموفق بود یا امکان تأیید آن وجود نداشت.")
    return redirect("order_status", code=order.code)


def content_page(request, page):
    content = get_object_or_404(ContentPage, slug=page, is_active=True)
    return render(request, "shop/content_page.html", {"content_page": content})


def health(request):
    SiteSetting.load()
    return JsonResponse({"status": "ok"})


def robots(request):
    sitemap = request.build_absolute_uri(reverse("sitemap"))
    return HttpResponse(
        f"User-agent: *\nAllow: /\nDisallow: /admin/\nDisallow: /checkout/\nSitemap: {sitemap}\n",
        content_type="text/plain",
    )


def sitemap(request):
    products = Product.objects.filter(is_active=True).only("slug", "updated_at")
    pages = ContentPage.objects.filter(is_active=True).only("slug", "updated_at")
    return render(request, "shop/sitemap.xml", {"products": products, "pages": pages}, content_type="application/xml")
