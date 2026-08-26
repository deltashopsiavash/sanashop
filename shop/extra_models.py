import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


class FooterSetting(models.Model):
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    description = models.TextField(blank=True)
    support_text = models.CharField(max_length=240, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "shop"
        verbose_name = "تنظیمات فوتر"
        verbose_name_plural = "تنظیمات فوتر"

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)


class FooterSocial(models.Model):
    PLATFORM_CHOICES = [
        ("instagram", "اینستاگرام"),
        ("telegram", "تلگرام"),
        ("whatsapp", "واتساپ"),
        ("rubika", "روبیکا"),
        ("eitaa", "ایتا"),
        ("youtube", "یوتیوب"),
        ("aparat", "آپارات"),
        ("x", "ایکس"),
        ("facebook", "فیسبوک"),
        ("other", "سایر"),
    ]
    platform = models.CharField(max_length=20, choices=PLATFORM_CHOICES, default="other")
    label = models.CharField(max_length=80)
    url = models.CharField(max_length=500)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "shop"
        ordering = ["sort_order", "id"]

    def __str__(self):
        return self.label


class TrustBadge(models.Model):
    image = models.ImageField(upload_to="branding/trust/%Y/%m/", blank=True)
    target_url = models.CharField(max_length=500, blank=True)
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "shop"

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)


class ProductStory(models.Model):
    MEDIA_IMAGE = "image"
    MEDIA_VIDEO = "video"
    MEDIA_CHOICES = [(MEDIA_IMAGE, "عکس"), (MEDIA_VIDEO, "ویدئو")]

    title = models.CharField(max_length=160)
    media = models.FileField(upload_to="stories/%Y/%m/")
    media_type = models.CharField(max_length=10, choices=MEDIA_CHOICES, default=MEDIA_IMAGE)
    target_url = models.CharField(max_length=500)
    expires_at = models.DateTimeField(db_index=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "shop"
        ordering = ["sort_order", "-id"]

    @property
    def active_now(self):
        return bool(self.is_active and self.expires_at > timezone.now())

    @property
    def remaining_seconds(self):
        if not self.active_now:
            return 0
        return max(0, int((self.expires_at - timezone.now()).total_seconds()))

    def __str__(self):
        return self.title


class CustomerProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="customer_profile",
    )
    customer_code = models.CharField(max_length=20, unique=True, null=True, blank=True, db_index=True)
    phone = models.CharField(max_length=20, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "shop"
        ordering = ["-created_at"]
        verbose_name = "پروفایل مشتری"
        verbose_name_plural = "پروفایل مشتریان"

    def save(self, *args, **kwargs):
        needs_code = not self.customer_code
        super().save(*args, **kwargs)
        if needs_code and self.pk:
            code = f"V{1000 + self.pk}"
            type(self).objects.filter(pk=self.pk, customer_code__isnull=True).update(customer_code=code)
            self.customer_code = code

    @classmethod
    def ensure(cls, user, phone=""):
        profile, created = cls.objects.get_or_create(user=user, defaults={"phone": phone or ""})
        changed = False
        if phone and profile.phone != phone:
            profile.phone = phone
            changed = True
        if not profile.customer_code:
            profile.customer_code = f"V{1000 + profile.pk}"
            changed = True
        if changed:
            profile.save(update_fields=["phone", "customer_code", "updated_at"])
        return profile

    def __str__(self):
        return f"{self.customer_code or '-'} - {self.user.email or self.user.username}"


class EmailVerificationCode(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="email_otp",
    )
    code = models.CharField(max_length=6, db_index=True)
    expires_at = models.DateTimeField(db_index=True)
    last_sent_at = models.DateTimeField(default=timezone.now)
    attempts = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "shop"
        verbose_name = "کد تایید ایمیل"
        verbose_name_plural = "کدهای تایید ایمیل"

    @classmethod
    def issue(cls, user, lifetime_minutes=10):
        code = f"{secrets.randbelow(1_000_000):06d}"
        now = timezone.now()
        obj, _ = cls.objects.update_or_create(
            user=user,
            defaults={
                "code": code,
                "expires_at": now + timedelta(minutes=lifetime_minutes),
                "last_sent_at": now,
                "attempts": 0,
            },
        )
        return obj

    @property
    def is_expired(self):
        return timezone.now() >= self.expires_at

    def matches(self, value):
        return not self.is_expired and self.attempts < 6 and secrets.compare_digest(self.code, str(value or "").strip())
