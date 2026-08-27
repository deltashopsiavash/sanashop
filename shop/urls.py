from django.contrib.auth import views as auth_views
from django.urls import path
from django.urls import reverse_lazy

from . import account_views, views
from .auth_views import BrandedPasswordResetView
from .site_api_v10 import bot_api

urlpatterns = [
    path("", views.home, name="home"),
    path("api/bot/v1/", bot_api, name="bot_api_v1"),
    path("account/register/", account_views.register, name="register"),
    path("account/verify/", account_views.verify_email_code, name="verify_email_code"),
    path("account/verify/<uuid:token>/", views.verify_email, name="verify_email_legacy"),
    path("account/login/", account_views.account_entry, name="login"),
    path("account/password/", account_views.account_password, name="account_password"),
    path("account/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path(
        "account/password-reset/",
        BrandedPasswordResetView.as_view(
            template_name="registration/password_reset_form.html",
            email_template_name="registration/password_reset_email.txt",
            html_email_template_name="emails/password_reset.html",
            success_url=reverse_lazy("password_reset_done"),
        ),
        name="password_reset",
    ),
    path("account/password-reset/sent/", auth_views.PasswordResetDoneView.as_view(template_name="registration/password_reset_done.html"), name="password_reset_done"),
    path("account/password-reset/<uidb64>/<token>/", auth_views.PasswordResetConfirmView.as_view(template_name="registration/password_reset_confirm.html", success_url=reverse_lazy("password_reset_complete")), name="password_reset_confirm"),
    path("account/password-reset/complete/", auth_views.PasswordResetCompleteView.as_view(template_name="registration/password_reset_complete.html"), name="password_reset_complete"),
    path("account/home/", account_views.account_home, name="account_home"),
    path("account/orders/", views.my_orders, name="my_orders"),
    path("account/profile/", account_views.account_profile, name="account_profile"),
    path("products/", views.catalog, name="catalog"),
    path("category/<str:category_slug>/", views.catalog, name="category"),
    path("product/<str:slug>/", views.product_detail, name="product_detail"),
    path("cart/", views.cart, name="cart"),
    path("cart/data/", views.cart_data, name="cart_data"),
    path("cart/add/<int:product_id>/", views.cart_add, name="cart_add"),
    path("cart/update/<int:product_id>/", views.cart_update, name="cart_update"),
    path("cart/discount/apply/", views.discount_apply, name="discount_apply"),
    path("cart/discount/remove/", views.discount_remove, name="discount_remove"),
    path("checkout/", views.checkout, name="checkout"),
    path("payment/card/<str:code>/", views.card_payment, name="card_payment"),
    path("order/<str:code>/", views.order_status, name="order_status"),
    path("payment/zarinpal/callback/", views.zarinpal_callback, name="zarinpal_callback"),
    path("page/<str:page>/", views.content_page, name="content_page"),
    path("health/", views.health, name="health"),
    path("robots.txt", views.robots, name="robots"),
    path("sitemap.xml", views.sitemap, name="sitemap"),
]
