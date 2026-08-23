import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


def attach_existing_orders(apps, schema_editor):
    User = apps.get_model("auth", "User")
    Order = apps.get_model("shop", "Order")
    OrderStatusEvent = apps.get_model("shop", "OrderStatusEvent")
    users = {u.email.lower(): u.id for u in User.objects.exclude(email="")}
    for order in Order.objects.filter(customer__isnull=True).exclude(email=""):
        user_id = users.get(order.email.lower())
        if user_id:
            order.customer_id = user_id
            order.save(update_fields=["customer"])
    for order in Order.objects.all():
        OrderStatusEvent.objects.get_or_create(order=order, status=order.status, defaults={"note": "وضعیت سفارش پیش از بروزرسانی"})


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("shop", "0001_initial"),
    ]

    operations = [
        migrations.AddField(model_name="sitesetting", name="backup_interval_minutes", field=models.PositiveIntegerField(default=0, help_text="صفر یعنی غیرفعال")),
        migrations.AddField(model_name="sitesetting", name="last_backup_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="order", name="customer", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="orders", to=settings.AUTH_USER_MODEL)),
        migrations.AddField(model_name="order", name="tracking_code", field=models.CharField(blank=True, max_length=100)),
        migrations.AddField(model_name="order", name="tracking_url", field=models.URLField(blank=True)),
        migrations.AddField(model_name="order", name="shipped_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.CreateModel(
            name="OrderStatusEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("status", models.CharField(choices=[("pending", "در انتظار پرداخت"), ("review", "بررسی پرداخت"), ("paid", "پرداخت‌شده"), ("processing", "در حال آماده‌سازی"), ("shipped", "ارسال‌شده"), ("cancelled", "لغوشده")], max_length=16)),
                ("note", models.CharField(blank=True, max_length=250)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("order", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="status_events", to="shop.order")),
            ],
            options={"ordering": ["created_at"]},
        ),
        migrations.CreateModel(
            name="EmailVerificationToken",
            fields=[
                ("token", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("expires_at", models.DateTimeField()),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="email_verification", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.RunPython(attach_existing_orders, migrations.RunPython.noop),
    ]
