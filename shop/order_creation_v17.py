from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .models import DiscountCode, OrderItem, OrderStatusEvent, Product
from .pricing import effective_price
from .services import order_event_payload, queue_bot_event, reservation_deadline


@transaction.atomic
def create_order(form, rows, subtotal, store, customer=None, discount=None, discount_amount=0):
    """Create an invoice while locking only Product rows.

    PostgreSQL rejects SELECT ... FOR UPDATE when Django adds the optional reverse
    OneToOne promotion relation as a LEFT OUTER JOIN. Lock the Product row first,
    then let effective_price() read the optional promotion separately.
    """
    shipping = store.shipping_for(subtotal)
    locked_rows = []
    locked_subtotal = 0

    for row in rows:
        product = Product.objects.select_for_update().get(pk=row["product"].pk)
        qty = int(row["quantity"])
        if not product.is_active or product.available_stock < qty:
            raise ValueError(f"موجودی آزاد «{product.name}» کافی نیست.")

        unit_price = effective_price(product)
        locked_rows.append((product, qty, unit_price))
        locked_subtotal += unit_price * qty

    if locked_subtotal != subtotal:
        subtotal = locked_subtotal
        shipping = store.shipping_for(subtotal)
        if discount:
            discount_amount = discount.discount_for(subtotal)

    order = form.save(commit=False)
    order.customer = customer
    order.subtotal = subtotal
    order.shipping = shipping
    order.discount_amount = min(max(int(discount_amount or 0), 0), subtotal)
    order.discount_code = discount.code if discount else ""
    order.total = max(0, subtotal + shipping - order.discount_amount)
    order.status = "pending"
    order.reservation_expires_at = reservation_deadline()
    order.stock_committed = False
    order.reservation_released = False
    order.save()

    for product, qty, unit_price in locked_rows:
        OrderItem.objects.create(
            order=order,
            product=product,
            title=product.name,
            unit_price=unit_price,
            quantity=qty,
        )
        Product.objects.filter(pk=product.pk).update(
            reserved_stock=F("reserved_stock") + qty,
            updated_at=timezone.now(),
        )

    OrderStatusEvent.objects.create(
        order=order,
        status="pending",
        note="فاکتور ساخته شد و موجودی موقتاً رزرو شد",
    )
    if discount:
        DiscountCode.objects.filter(pk=discount.pk).update(used_count=F("used_count") + 1)

    order.refresh_from_db()
    queue_bot_event("order_created", order_event_payload(order))
    return order
