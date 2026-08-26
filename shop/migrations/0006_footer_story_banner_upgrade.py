from django.db import migrations, models


def copy_legacy_footer(apps, schema_editor):
    SiteSetting = apps.get_model("shop", "SiteSetting")
    FooterSetting = apps.get_model("shop", "FooterSetting")
    LegacySocial = apps.get_model("shop", "SocialLink")
    FooterSocial = apps.get_model("shop", "FooterSocial")

    store = SiteSetting.objects.filter(pk=1).first()
    if store:
        FooterSetting.objects.update_or_create(
            pk=1,
            defaults={
                "address": store.address or "",
                "phone": store.phone or "",
                "email": "",
                "description": store.tagline or "",
                "support_text": "",
            },
        )

    platform_terms = [
        ("instagram", ("instagram", "اینستاگرام")),
        ("telegram", ("telegram", "t.me", "تلگرام")),
        ("whatsapp", ("whatsapp", "wa.me", "واتساپ")),
        ("rubika", ("rubika", "روبیکا")),
        ("eitaa", ("eitaa", "ایتا")),
        ("youtube", ("youtube", "youtu.be", "یوتیوب")),
        ("aparat", ("aparat", "آپارات")),
        ("facebook", ("facebook", "فیسبوک")),
        ("x", ("twitter", "x.com", "توییتر", "ایکس")),
    ]
    for item in LegacySocial.objects.all().order_by("sort_order", "id"):
        haystack = f"{item.title} {item.url}".lower()
        platform = "other"
        for value, terms in platform_terms:
            if any(term.lower() in haystack for term in terms):
                platform = value
                break
        FooterSocial.objects.get_or_create(
            label=item.title,
            url=item.url,
            defaults={
                "platform": platform,
                "is_active": item.is_active,
                "sort_order": item.sort_order,
            },
        )


class Migration(migrations.Migration):
    dependencies = [("shop", "0005_checkout_reservations_bot_events")]

    operations = [
        migrations.AlterField(
            model_name="orderstatusevent",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "در انتظار پرداخت"),
                    ("review", "در انتظار تایید رسید"),
                    ("rejected", "رسید رد شده"),
                    ("paid", "پرداخت‌شده"),
                    ("processing", "در حال آماده‌سازی"),
                    ("shipped", "ارسال‌شده"),
                    ("delivered", "تحویل‌شده"),
                    ("cancelled", "لغوشده"),
                ],
                max_length=16,
            ),
        ),
        migrations.CreateModel(
            name="FooterSetting",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("address", models.TextField(blank=True)),
                ("phone", models.CharField(blank=True, max_length=40)),
                ("email", models.EmailField(blank=True, max_length=254)),
                ("description", models.TextField(blank=True)),
                ("support_text", models.CharField(blank=True, max_length=240)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"verbose_name": "تنظیمات فوتر", "verbose_name_plural": "تنظیمات فوتر"},
        ),
        migrations.CreateModel(
            name="FooterSocial",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("platform", models.CharField(choices=[("instagram", "اینستاگرام"), ("telegram", "تلگرام"), ("whatsapp", "واتساپ"), ("rubika", "روبیکا"), ("eitaa", "ایتا"), ("youtube", "یوتیوب"), ("aparat", "آپارات"), ("x", "ایکس"), ("facebook", "فیسبوک"), ("other", "سایر")], default="other", max_length=20)),
                ("label", models.CharField(max_length=80)),
                ("url", models.CharField(max_length=500)),
                ("is_active", models.BooleanField(default=True)),
                ("sort_order", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["sort_order", "id"]},
        ),
        migrations.CreateModel(
            name="TrustBadge",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("image", models.ImageField(blank=True, upload_to="branding/trust/%Y/%m/")),
                ("target_url", models.CharField(blank=True, max_length=500)),
                ("is_active", models.BooleanField(default=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name="ProductStory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=160)),
                ("media", models.FileField(upload_to="stories/%Y/%m/")),
                ("media_type", models.CharField(choices=[("image", "عکس"), ("video", "ویدئو")], default="image", max_length=10)),
                ("target_url", models.CharField(max_length=500)),
                ("expires_at", models.DateTimeField(db_index=True)),
                ("is_active", models.BooleanField(default=True)),
                ("sort_order", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["sort_order", "-id"]},
        ),
        migrations.RunPython(copy_legacy_footer, migrations.RunPython.noop),
    ]
