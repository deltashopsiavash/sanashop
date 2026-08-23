from django.contrib import admin

from .models import Category, Order, OrderItem, PaymentReceipt, Product, ProductImage, SiteSetting


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 0


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "price", "stock", "is_active", "is_featured", "updated_at")
    list_filter = ("category", "is_active", "is_featured")
    list_editable = ("price", "stock", "is_active", "is_featured")
    search_fields = ("name", "sku", "description")
    prepopulated_fields = {"slug": ("name",)}
    inlines = [ProductImageInline]


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "parent", "is_active", "sort_order")
    list_editable = ("is_active", "sort_order")
    search_fields = ("name",)


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ("product", "title", "unit_price", "quantity", "total")


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("code", "full_name", "mobile", "total", "payment_method", "status", "created_at")
    list_filter = ("status", "payment_method", "created_at")
    list_editable = ("status",)
    search_fields = ("code", "full_name", "mobile", "postal_code")
    readonly_fields = ("code", "subtotal", "shipping", "total", "authority", "payment_ref_id", "created_at", "updated_at")
    inlines = [OrderItemInline]


@admin.register(PaymentReceipt)
class ReceiptAdmin(admin.ModelAdmin):
    list_display = ("order", "status", "created_at", "preview")
    list_filter = ("status",)
    readonly_fields = ("preview", "created_at")

    def preview(self, obj):
        return "تصویر رسید برای مدیر در تلگرام ارسال شده است." if obj.image else "-"


@admin.register(SiteSetting)
class SiteSettingAdmin(admin.ModelAdmin):
    fieldsets = (
        ("برند", {"fields": ("site_name", "tagline", "announcement", "logo", "primary_color")}),
        ("تماس", {"fields": ("phone", "instagram", "telegram", "address")}),
        ("پرداخت", {"fields": ("payment_mode", "zarinpal_merchant_id", "zarinpal_sandbox", "card_number", "card_owner")}),
        ("ارسال", {"fields": ("shipping_fee", "free_shipping_threshold")}),
        ("مجوز و قوانین", {"fields": ("enamad_html", "terms_text", "return_policy")}),
    )

    def has_add_permission(self, request):
        return not SiteSetting.objects.exists()

admin.site.site_header = "مدیریت فروشگاه"
admin.site.site_title = "پنل فروشگاه"
