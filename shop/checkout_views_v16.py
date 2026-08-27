import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .forms import CheckoutForm, ReceiptForm
from .iran_locations import province_city_map
from .models import Order, PaymentReceipt, SiteSetting
from .services import (
    create_order,
    expire_reservations,
    order_event_payload,
    queue_bot_event,
    release_order_stock,
    send_receipt_to_telegram,
    set_order_status,
    zarinpal_request,
    zarinpal_verify,
)
from .views import _cart_context

logger = logging.getLogger(__name__)


def _can_view_order(request, order):
    return (
        (request.user.is_authenticated and order.customer_id == request.user.id)
        or request.session.get("order_code") == order.code
        or request.user.is_staff
    )


def _clear_cart_after_invoice(request, order):
    request.session["cart"] = {}
    request.session.pop("discount_code", None)
    request.session["order_code"] = order.code
    request.session.modified = True


def _render_checkout(request, totals, form):
    return render(request, "shop/checkout.html", {**totals, "form": form, "locations": province_city_map()})


@login_required
def checkout(request):
    totals = _cart_context(request)
    rows, subtotal = totals["rows"], totals["subtotal"]
    if not rows:
        messages.warning(request, "سبد خرید شما خالی است.")
        return redirect("catalog")

    store = SiteSetting.load()
    initial = {
        "full_name": f"{request.user.first_name} {request.user.last_name}".strip(),
        "email": request.user.email,
    }
    form = CheckoutForm(request.POST or None, store_settings=store, initial=initial)

    if request.method == "POST" and form.is_valid():
        method = form.cleaned_data.get("payment_method")
        if method == "card" and not (store.card_number or "").strip():
            form.add_error("payment_method", "شماره کارت فروشگاه هنوز تنظیم نشده است؛ مدیر فروشگاه باید اطلاعات کارت را ثبت کند.")
        if method == "zarinpal" and not (store.zarinpal_merchant_id or "").strip():
            form.add_error("payment_method", "مرچنت زرین‌پال تنظیم نشده است؛ روش پرداخت آنلاین فعلاً قابل استفاده نیست.")

        if not form.errors:
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
                form.add_error(None, str(exc))
                return _render_checkout(request, _cart_context(request), form)
            except Exception:
                logger.exception("Unexpected invoice creation failure for user=%s", request.user.pk)
                form.add_error(None, "ساخت فاکتور انجام نشد. سبد خرید شما حفظ شده است؛ دوباره تلاش کنید.")
                return _render_checkout(request, _cart_context(request), form)

            if order.payment_method == "zarinpal":
                try:
                    callback = request.build_absolute_uri(reverse("zarinpal_callback"))
                    gateway_url = zarinpal_request(order, callback)
                except Exception as exc:
                    logger.exception("Zarinpal request failed for order=%s", order.code)
                    order.admin_note = f"خطای شروع زرین‌پال: {exc}"
                    order.save(update_fields=["admin_note", "updated_at"])
                    release_order_stock(order)
                    order.status = "cancelled"
                    order.save(update_fields=["status", "updated_at"])
                    queue_bot_event("payment_failed", order_event_payload(order))
                    # Do not clear the cart when the gateway could not even start.
                    messages.error(request, "اتصال به درگاه ممکن نشد. سبد خرید شما حفظ شد و می‌توانید دوباره تلاش کنید.")
                    return redirect("checkout")
                _clear_cart_after_invoice(request, order)
                return redirect(gateway_url)

            _clear_cart_after_invoice(request, order)
            return redirect("card_payment", code=order.code)

    return _render_checkout(request, totals, form)


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
        try:
            with transaction.atomic():
                locked = Order.objects.select_for_update().get(pk=order.pk)
                if not locked.reservation_active:
                    raise ValueError("مهلت رزرو این فاکتور تمام شده است.")
                receipt, _ = PaymentReceipt.objects.update_or_create(
                    order=locked,
                    defaults={
                        "image": receipt_form.cleaned_data["image"],
                        "status": "pending",
                        "reviewed_at": None,
                    },
                )
                locked.receipt_rejection_reason = ""
                locked.save(update_fields=["receipt_rejection_reason", "updated_at"])
                set_order_status(locked, "review", "رسید کارت‌به‌کارت برای بررسی ارسال شد")
        except ValueError as exc:
            receipt_form.add_error(None, str(exc))
        except Exception:
            logger.exception("Receipt upload failed for order=%s", order.code)
            receipt_form.add_error(None, "ذخیره رسید انجام نشد. دوباره فایل را ارسال کنید؛ فاکتور شما حذف نشده است.")
        else:
            send_receipt_to_telegram(receipt)
            messages.success(request, "رسید با موفقیت ارسال شد و در انتظار بررسی مدیر است.")
            return redirect("order_status", code=order.code)

    return render(request, "shop/card_payment.html", {"order": order, "receipt_form": receipt_form, "store": SiteSetting.load()})


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
        # A temporary network/API error after the customer returns from Zarinpal does
        # not prove payment failed. Never release stock or cancel a possibly-paid order.
        logger.exception("Zarinpal verification temporarily failed for order=%s", order.code)
        order.admin_note = (
            (order.admin_note or "")
            + f"\nنیازمند بررسی پرداخت زرین‌پال؛ خطای تایید: {exc}"
        ).strip()
        order.save(update_fields=["admin_note", "updated_at"])
        queue_bot_event("payment_verification_pending", order_event_payload(order))
        messages.warning(request, "بازگشت از درگاه ثبت شد اما تأیید نهایی موقتاً در دسترس نبود. سفارش لغو نشده و نیازمند بررسی است.")
        return redirect("order_status", code=order.code)

    if verified:
        messages.success(request, f"پرداخت با موفقیت انجام شد. کد پیگیری: {order.payment_ref_id}")
    else:
        # Non-success verify responses can also be ambiguous. Keep the reservation
        # instead of destroying a possibly paid order; expiry/manager review handles it safely.
        order.admin_note = ((order.admin_note or "") + "\nپاسخ تأیید زرین‌پال موفق نبود؛ نیازمند بررسی.").strip()
        order.save(update_fields=["admin_note", "updated_at"])
        queue_bot_event("payment_verification_pending", order_event_payload(order))
        messages.warning(request, "پرداخت هنوز تأیید نهایی نشده است. سفارش شما حذف یا لغو نشده و در حال بررسی است.")
    return redirect("order_status", code=order.code)
