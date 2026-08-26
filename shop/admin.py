from django.contrib import admin

from .extra_models import CustomerProfile, EmailVerificationCode
from .models import Category, ContentPage, DiscountCode, EmailVerificationToken, HeroSlide, Order, OrderItem, OrderStatusEvent, PaymentReceipt, Product, ProductImage, SiteSetting, SocialLink


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 0


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("sku", "name", "category", "price", "stock", "is_active", "is_featured", "is_amazing", "updated_at")
    list_filter = ("category", "is_active", "is_featured", "is_amazing")
    list_editable = ("price", "stock", "is_active", "is_featured", "is_amazing")
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


class OrderStatusInline(admin.TabularInline):
    model = OrderStatusEvent
    extra = 0
    readonly_fields = ("status", "note", "created_at")


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("code", "full_name", "customer", "mobile", "total", "payment_method", "status", "tracking_code", "created_at")
    list_filter = ("status", "payment_method", "created_at")
    list_editable = ("status",)
    search_fields = ("code", "full_name", "mobile", "postal_code", "tracking_code", "customer__email", "customer__customer_profile__customer_code")
    readonly_fields = ("code", "subtotal", "shipping", "total", "authority", "payment_ref_id", "created_at", "updated_at")
    inlines = [OrderItemInline, OrderStatusInline]


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
        ("پشتیبان‌گیری", {"fields": ("backup_interval_minutes", "last_backup_at")}),
        ("مجوز و قوانین", {"fields": ("enamad_html", "terms_text", "return_policy")}),
    )

    def has_add_permission(self, request):
        return not SiteSetting.objects.exists()


@admin.register(CustomerProfile)
class CustomerProfileAdmin(admin.ModelAdmin):
    list_display = ("customer_code", "user", "phone", "created_at")
    search_fields = ("customer_code", "phone", "user__email", "user__first_name", "user__last_name")
    readonly_fields = ("customer_code", "created_at", "updated_at")


@admin.register(EmailVerificationCode)
class EmailVerificationCodeAdmin(admin.ModelAdmin):
    list_display = ("user", "expires_at", "attempts", "last_sent_at")
    readonly_fields = ("code", "created_at", "updated_at")
    search_fields = ("user__email",)


admin.site.site_header = "مدیریت فروشگاه"
admin.site.site_title = "پنل فروشگاه"


@admin.register(ContentPage)
class ContentPageAdmin(admin.ModelAdmin):
    list_display = ("title", "slug", "footer_group", "show_in_footer", "is_active", "sort_order")
    list_editable = ("show_in_footer", "is_active", "sort_order")
    search_fields = ("title", "slug", "body")


@admin.register(HeroSlide)
class HeroSlideAdmin(admin.ModelAdmin):
    list_display = ("title", "is_active", "sort_order", "created_at")
    list_editable = ("is_active", "sort_order")


@admin.register(DiscountCode)
class DiscountCodeAdmin(admin.ModelAdmin):
    list_display = ("code", "percent", "min_order_amount", "used_count", "max_uses", "expires_at", "is_active")
    list_filter = ("is_active",)
    search_fields = ("code",)


@admin.register(SocialLink)
class SocialLinkAdmin(admin.ModelAdmin):
    list_display = ("title", "url", "is_active", "sort_order", "updated_at")
    list_editable = ("is_active", "sort_order")
    search_fields = ("title", "url")
