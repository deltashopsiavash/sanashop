from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("products/", views.catalog, name="catalog"),
    path("category/<str:category_slug>/", views.catalog, name="category"),
    path("product/<str:slug>/", views.product_detail, name="product_detail"),
    path("cart/", views.cart, name="cart"),
    path("cart/add/<int:product_id>/", views.cart_add, name="cart_add"),
    path("cart/update/<int:product_id>/", views.cart_update, name="cart_update"),
    path("checkout/", views.checkout, name="checkout"),
    path("order/<str:code>/", views.order_status, name="order_status"),
    path("payment/zarinpal/callback/", views.zarinpal_callback, name="zarinpal_callback"),
    path("page/<str:page>/", views.content_page, name="content_page"),
    path("health/", views.health, name="health"),
    path("robots.txt", views.robots, name="robots"),
    path("sitemap.xml", views.sitemap, name="sitemap"),
]
