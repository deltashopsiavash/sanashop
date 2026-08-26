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
