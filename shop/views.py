from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.db.models import Q
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import CheckoutForm, ReceiptForm, RegistrationForm
from .models import Category, EmailVerificationToken, Order, PaymentReceipt, Product, SiteSetting
from .services import cart_rows, create_order, send_receipt_to_telegram, send_telegram_text, set_order_status, zarinpal_request, zarinpal_verify


def register(request):
    if request.user.is_authenticated:
        return redirect("my_orders")
    form = RegistrationForm(request.POST or None)
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
            form.add_error("email", "ارسال ایمیل ممکن نشد؛ تنظیمات ایمیل فروشگاه هنوز کامل نیست.")
        else:
            return render(request, "registration/verification_sent.html", {"email": user.email})
    return render(request, "registration/register.html", {"form": form})


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
    return redirect("my_orders")


@login_required
def my_orders(request):
    orders = request.user.orders.prefetch_related("items", "status_events").all()
    return render(request, "shop/my_orders.html", {"orders": orders})


def home(request):
    return render(request, "shop/home.html", {"featured": Product.objects.filter(is_active=True, is_featured=True).select_related("category")[:8], "categories": Category.objects.filter(is_active=True, parent__isnull=True)[:8]})


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


def cart(request):
    rows, subtotal = cart_rows(request)
    store = SiteSetting.load()
    shipping = 0 if subtotal and subtotal >= store.free_shipping_threshold else store.shipping_fee
    return render(request, "shop/cart.html", {"rows": rows, "subtotal": subtotal, "shipping": shipping, "total": subtotal + shipping if rows else 0})


@require_POST
def cart_add(request, product_id):
    product = get_object_or_404(Product, pk=product_id, is_active=True)
    if not product.available:
        messages.warning(request, "این محصول در حال حاضر موجود نیست.")
        return redirect(safe_next(request, reverse("catalog")))
    try:
        requested = int(request.POST.get("quantity", 1))
    except (TypeError, ValueError):
        requested = 1
    qty = min(max(1, requested), product.stock)
    data = request.session.get("cart", {})
    data[str(product.pk)] = min(int(data.get(str(product.pk), 0)) + qty, product.stock)
    request.session["cart"] = data
    messages.success(request, f"«{product.name}» به سبد خرید اضافه شد.")
    return redirect(safe_next(request, reverse("cart")))


@require_POST
def cart_update(request, product_id):
    data = request.session.get("cart", {})
    product = get_object_or_404(Product, pk=product_id)
    try:
        requested = int(request.POST.get("quantity", 0))
    except (TypeError, ValueError):
        requested = 0
    qty = max(0, min(requested, product.stock))
    if qty:
        data[str(product_id)] = qty
    else:
        data.pop(str(product_id), None)
    request.session["cart"] = data
    return redirect("cart")


@login_required
def checkout(request):
    rows, subtotal = cart_rows(request)
    if not rows:
        messages.warning(request, "سبد خرید شما خالی است.")
        return redirect("catalog")
    store = SiteSetting.load()
    initial = {"full_name": request.user.first_name, "email": request.user.email}
    form = CheckoutForm(request.POST or None, store_settings=store, initial=initial)
    shipping = 0 if subtotal >= store.free_shipping_threshold else store.shipping_fee
    if request.method == "POST" and form.is_valid():
        try:
            order = create_order(form, rows, subtotal, store, customer=request.user)
        except ValueError as exc:
            messages.error(request, str(exc))
        else:
            request.session["cart"] = {}
            request.session["order_code"] = order.code
            send_telegram_text(f"🛒 سفارش جدید\nکد: <b>{order.code}</b>\nمشتری: {order.full_name}\nمبلغ: {order.total:,} تومان\nپرداخت: {order.get_payment_method_display()}")
            if order.payment_method == "zarinpal":
                try:
                    callback = request.build_absolute_uri(reverse("zarinpal_callback"))
                    return redirect(zarinpal_request(order, callback))
                except Exception:
                    messages.error(request, "اتصال به درگاه موقتاً ممکن نیست. سفارش شما ذخیره شده است.")
            return redirect("order_status", code=order.code)
    return render(request, "shop/checkout.html", {"form": form, "rows": rows, "subtotal": subtotal, "shipping": shipping, "total": subtotal + shipping})


def order_status(request, code):
    order = get_object_or_404(Order.objects.prefetch_related("items", "status_events"), code=code)
    owns_order = request.user.is_authenticated and order.customer_id == request.user.id
    if not owns_order and request.session.get("order_code") != code and not request.user.is_staff:
        raise Http404
    receipt_form = ReceiptForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and order.payment_method == "card" and receipt_form.is_valid():
        receipt, _ = PaymentReceipt.objects.update_or_create(order=order, defaults={"image": receipt_form.cleaned_data["image"], "status": "pending"})
        set_order_status(order, "review", "رسید کارت‌به‌کارت برای بررسی ارسال شد")
        send_receipt_to_telegram(receipt)
        messages.success(request, "رسید ثبت شد و پس از بررسی نتیجه اعلام می‌شود.")
        return redirect("order_status", code=code)
    return render(request, "shop/order_status.html", {"order": order, "receipt_form": receipt_form})


def zarinpal_callback(request):
    authority = request.GET.get("Authority", "")
    order = get_object_or_404(Order, authority=authority, payment_method="zarinpal")
    request.session["order_code"] = order.code
    try:
        verified = request.GET.get("Status") == "OK" and zarinpal_verify(order)
    except Exception:
        verified = False
    if verified:
        send_telegram_text(f"✅ پرداخت زرین‌پال تایید شد\nسفارش: <b>{order.code}</b>\nکد پیگیری: {order.payment_ref_id}")
        messages.success(request, "پرداخت با موفقیت انجام شد.")
    else:
        messages.error(request, "پرداخت ناموفق بود یا توسط شما لغو شد.")
    return redirect("order_status", code=order.code)


def content_page(request, page):
    allowed = {"about", "contact", "terms", "returns", "privacy"}
    if page not in allowed:
        raise Http404
    return render(request, "shop/content_page.html", {"page": page})


def health(request):
    SiteSetting.load()
    return JsonResponse({"status": "ok"})


def robots(request):
    sitemap = request.build_absolute_uri(reverse("sitemap"))
    return HttpResponse(f"User-agent: *\nAllow: /\nDisallow: /admin/\nDisallow: /checkout/\nSitemap: {sitemap}\n", content_type="text/plain")


def sitemap(request):
    products = Product.objects.filter(is_active=True).only("slug", "updated_at")
    return render(request, "shop/sitemap.xml", {"products": products}, content_type="application/xml")
