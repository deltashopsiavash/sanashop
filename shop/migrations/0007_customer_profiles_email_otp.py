from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


def backfill_customer_profiles(apps, schema_editor):
    User = apps.get_model(*settings.AUTH_USER_MODEL.split("."))
    Profile = apps.get_model("shop", "CustomerProfile")
    for user in User.objects.filter(is_staff=False).order_by("id").iterator():
        profile, _ = Profile.objects.get_or_create(user_id=user.id, defaults={"phone": ""})
        if not profile.customer_code:
            profile.customer_code = f"V{1000 + profile.id}"
            profile.save(update_fields=["customer_code"])


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("shop", "0006_footer_story_banner_upgrade"),
    ]

    operations = [
        migrations.CreateModel(
            name="CustomerProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("customer_code", models.CharField(blank=True, db_index=True, max_length=20, null=True, unique=True)),
                ("phone", models.CharField(blank=True, db_index=True, max_length=20)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="customer_profile", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "verbose_name": "پروفایل مشتری",
                "verbose_name_plural": "پروفایل مشتریان",
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="EmailVerificationCode",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(db_index=True, max_length=6)),
                ("expires_at", models.DateTimeField(db_index=True)),
                ("last_sent_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("attempts", models.PositiveSmallIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="email_otp", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "verbose_name": "کد تایید ایمیل",
                "verbose_name_plural": "کدهای تایید ایمیل",
            },
        ),
        migrations.RunPython(backfill_customer_profiles, migrations.RunPython.noop),
    ]
