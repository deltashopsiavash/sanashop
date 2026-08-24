import os
import uuid
from datetime import timedelta

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone
from django.utils.text import slugify


def unique_slug(instance, value):
    base = slugify(value, allow_unicode=True) or uuid.uuid4().hex[:8]
    slug = base
    model = instance.__class__
    index = 2
    while model.objects.filter(slug=slug).exclude(pk=instance.pk).exists():
        slug = f"{base}-{index}"
        index += 1
    return slug


class SiteSetting(models.Model):
    PAYMENT_CHOICES = [("zarinpal", "زرین‌پال"), ("card", "کارت به کارت"), ("both", "هر دو")]
    site_name = models.CharField(max_length=80, default=os.environ.get("DEFAULT_SITE_NAME", "سنا"))
    tagline = models.CharField(max_length=180, default="جزئیات کوچک، حس بزرگ")
    announcement = models.CharField(max_length=220, blank=True, default="ارسال رایگان برای خریدهای بالای ۲ میلیون تومان")
    logo = models.ImageField(upload_to="branding/", blank=True)
    primary_color = models.CharField(max_length=7, default="#7b243f")
    phone = models.CharField(max_length=30, blank=True)
    instagram = models.CharField(max_length=80, blank=True)
    telegram = models.CharField(max_length=80, blank=True)
    address = models.TextField(blank=True)
    payment_mode = models.CharField(max_length=12, choices=PAYMENT_CHOICES, default="card")
    zarinpal_merchant_id = models.CharField(max_length=64, blank=True, default=os.environ.get("ZARINPAL_MERCHANT_ID", ""))
    zarinpal_sandbox = models.BooleanField(default=os.environ.get("ZARINPAL_SANDBOX", "0") == "1")
    card_number = models.CharField(max_length=24, blank=True, default=os.environ.get("DEFAULT_CARD_NUMBER", ""))
    card_owner = models.CharField(max_length=100, blank=True, default=os.environ.get("DEFAULT_CARD_OWNER", ""))
    shipping_fee = models.PositiveBigIntegerField(default=90000)
    free_shipping_threshold = models.PositiveBigIntegerField(default=2000000)
    enamad_html = models.TextField(blank=True, help_text="کد HTML دریافت‌شده از اینماد")
    terms_text = models.TextField(blank=True)
    return_policy = models.TextField(blank=True)
    backup_interval_minutes = models.PositiveIntegerField(default=0, help_text="صفر یعنی غیرفعال")
    last_backup_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def __str__(self):
        return self.site_name


class Category(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=130, unique=True, allow_unicode=True, blank=True)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="children")
    image = models.ImageField(upload_to="categories/", blank=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name_plural = "دسته‌بندی‌ها"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(self, self.name)
        super().save(*args, **kwargs)

    @property
    def active_product_count(self):
        return self.products.filter(is_active=True).count()

    def __str__(self):
        return self.name


class Product(models.Model):
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="products")
    name = models.CharField(max_length=180)
    slug = models.SlugField(max_length=220, unique=True, allow_unicode=True, blank=True)
    sku = models.CharField(max_length=50, unique=True, blank=True)
    description = models.TextField(blank=True)
    price = models.PositiveBigIntegerField(validators=[MinValueValidator(1)])
    compare_at_price = models.PositiveBigIntegerField(null=True, blank=True)
    stock = models.PositiveIntegerField(default=0)
    image = models.ImageField(upload_to="products/%Y/%m/", blank=True)
    is_active = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False)
    is_amazing = models.BooleanField(default=False, verbose_name="پیشنهاد شگفت‌انگیز")
    amazing_until = models.DateTimeField(null=True, blank=True, verbose_name="پایان شگفت‌انگیز")
    assurance_1 = models.CharField(max_length=160, blank=True, default="تضمین سلامت فیزیکی", verbose_name="مزیت اول")
    assurance_2 = models.CharField(max_length=160, blank=True, default="بسته‌بندی مناسب هدیه", verbose_name="مزیت دوم")
    assurance_3 = models.CharField(max_length=160, blank=True, default="امکان پیگیری سفارش", verbose_name="مزیت سوم")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_featured", "-created_at"]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(self, self.name)
        if not self.sku:
            self.sku = f"SNA-{uuid.uuid4().hex[:8].upper()}"
        super().save(*args, **kwargs)

    @property
    def available(self):
        return self.is_active and self.stock > 0

    def __str__(self):
        return self.name


class ProductImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="gallery")
    image = models.ImageField(upload_to="products/%Y/%m/")
    alt = models.CharField(max_length=180, blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "id"]


class Order(models.Model):
    STATUS = [("pending", "در انتظار پرداخت"), ("review", "بررسی پرداخت"), ("paid", "پرداخت‌شده"), ("processing", "در حال آماده‌سازی"), ("shipped", "ارسال‌شده"), ("cancelled", "لغوشده")]
    PAYMENT = [("zarinpal", "زرین‌پال"), ("card", "کارت به کارت")]
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="orders")
    code = models.CharField(max_length=16, unique=True, editable=False)
    full_name = models.CharField(max_length=120)
    mobile = models.CharField(max_length=20)
    email = models.EmailField(blank=True)
    province = models.CharField(max_length=80)
    city = models.CharField(max_length=80)
    address = models.TextField()
    postal_code = models.CharField(max_length=20)
    note = models.TextField(blank=True)
    subtotal = models.PositiveBigIntegerField(default=0)
    shipping = models.PositiveBigIntegerField(default=0)
    total = models.PositiveBigIntegerField(default=0)
    discount_amount = models.PositiveBigIntegerField(default=0)
    discount_code = models.CharField(max_length=50, blank=True)
    payment_method = models.CharField(max_length=12, choices=PAYMENT)
    status = models.CharField(max_length=16, choices=STATUS, default="pending")
    authority = models.CharField(max_length=64, blank=True)
    payment_ref_id = models.CharField(max_length=64, blank=True)
    tracking_code = models.CharField(max_length=100, blank=True)
    tracking_url = models.URLField(blank=True)
    shipped_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = uuid.uuid4().hex[:10].upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.code} - {self.full_name}"


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, null=True, on_delete=models.SET_NULL)
    title = models.CharField(max_length=180)
    unit_price = models.PositiveBigIntegerField()
    quantity = models.PositiveIntegerField(default=1)

    @property
    def total(self):
        return self.unit_price * self.quantity


class PaymentReceipt(models.Model):
    STATUS = [("pending", "در انتظار"), ("approved", "تاییدشده"), ("rejected", "ردشده")]
    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name="receipt")
    image = models.ImageField(upload_to="receipts/%Y/%m/")
    status = models.CharField(max_length=12, choices=STATUS, default="pending")
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)


class OrderStatusEvent(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="status_events")
    status = models.CharField(max_length=16, choices=Order.STATUS)
    note = models.CharField(max_length=250, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]


class EmailVerificationToken(models.Model):
    token = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="email_verification")
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    @classmethod
    def issue(cls, user):
        cls.objects.filter(user=user).delete()
        return cls.objects.create(user=user, expires_at=timezone.now() + timedelta(hours=24))


class ContentPage(models.Model):
    GROUPS = [("guide", "راهنمای خرید"), ("contact", "ارتباط با ما"), ("other", "سایر")]
    title = models.CharField(max_length=120)
    slug = models.SlugField(max_length=150, unique=True, allow_unicode=True, blank=True)
    body = models.TextField(blank=True)
    footer_group = models.CharField(max_length=20, choices=GROUPS, default="guide")
    show_in_footer = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["footer_group", "sort_order", "id"]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(self, self.title)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title


class HeroSlide(models.Model):
    title = models.CharField(max_length=150, blank=True)
    subtitle = models.CharField(max_length=240, blank=True)
    image = models.ImageField(upload_to="banners/%Y/%m/")
    mobile_image = models.ImageField(upload_to="banners/mobile/%Y/%m/", blank=True)
    button_text = models.CharField(max_length=60, blank=True, default="مشاهده محصولات")
    link = models.CharField(max_length=300, blank=True, default="/products/")
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self):
        return self.title or f"بنر {self.pk}"


class SocialLink(models.Model):
    title = models.CharField(max_length=80)
    url = models.CharField(max_length=500, help_text="لینک مستقیم شبکه اجتماعی یا پیام‌رسان")
    image = models.ImageField(upload_to="social/%Y/%m/")
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self):
        return self.title


class DiscountCode(models.Model):
    code = models.CharField(max_length=50, unique=True)
    percent = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(99)])
    min_order_amount = models.PositiveBigIntegerField(default=0)
    max_uses = models.PositiveIntegerField(default=0, help_text="صفر یعنی بدون محدودیت")
    used_count = models.PositiveIntegerField(default=0)
    expires_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        self.code = self.code.strip().upper()
        self.percent = min(max(int(self.percent), 1), 99)
        super().save(*args, **kwargs)

    def is_valid_for(self, subtotal):
        if not self.is_active or subtotal < self.min_order_amount:
            return False
        if self.expires_at and self.expires_at <= timezone.now():
            return False
        if self.max_uses and self.used_count >= self.max_uses:
            return False
        return True

    def discount_for(self, subtotal):
        return (subtotal * self.percent) // 100 if self.is_valid_for(subtotal) else 0

    def __str__(self):
        return f"{self.code} - {self.percent}%"
