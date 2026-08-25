from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("shop", "0003_storefront_v2")]

    operations = [
        migrations.AddField(
            model_name="product",
            name="assurance_1",
            field=models.CharField(blank=True, default="تضمین سلامت فیزیکی", max_length=160, verbose_name="مزیت اول"),
        ),
        migrations.AddField(
            model_name="product",
            name="assurance_2",
            field=models.CharField(blank=True, default="بسته‌بندی مناسب هدیه", max_length=160, verbose_name="مزیت دوم"),
        ),
        migrations.AddField(
            model_name="product",
            name="assurance_3",
            field=models.CharField(blank=True, default="امکان پیگیری سفارش", max_length=160, verbose_name="مزیت سوم"),
        ),
        migrations.CreateModel(
            name="SocialLink",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=80)),
                ("url", models.CharField(help_text="لینک مستقیم شبکه اجتماعی یا پیام‌رسان", max_length=500)),
                ("image", models.ImageField(upload_to="social/%Y/%m/")),
                ("is_active", models.BooleanField(default=True)),
                ("sort_order", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["sort_order", "id"]},
        ),
    ]
