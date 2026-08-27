from . import checkout_views_v16 as v16
from .order_creation_v17 import create_order as postgres_safe_create_order

# checkout_v16 keeps all of the v16 payment and receipt reliability behavior.
# Replace only its invoice factory with the PostgreSQL-safe implementation.
v16.create_order = postgres_safe_create_order

checkout = v16.checkout
card_payment = v16.card_payment
zarinpal_callback = v16.zarinpal_callback
