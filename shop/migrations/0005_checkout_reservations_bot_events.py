from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("shop", "0004_social_links_product_assurances")]

    operations = [
        migrations.AddField(
            model_name="product",
            name="reserved_stock",
            field=models.PositiveIntegerField(default=0, help_text="تعداد رزروشده در فاکتورهای پرداخت‌نشده"),
        ),
        migrations.AddField(
            model_name="order",
            name="paid_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="order",
            name="reservation_expires_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="order",
            name="stock_committed",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="order",
            name="reservation_released",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="order",
            name="receipt_rejection_reason",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="order",
            name="admin_note",
            field=models.TextField(blank=True),
        ),
        migrations.AlterField(
            model_name="order",
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
                default="pending",
                max_length=16,
            ),
        ),
        migrations.CreateModel(
            name="BotEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kind", models.CharField(choices=[("order_created", "فاکتور جدید"), ("receipt_uploaded", "رسید جدید"), ("payment_success", "پرداخت موفق"), ("payment_failed", "پرداخت ناموفق"), ("reservation_expired", "پایان رزرو"), ("order_status", "تغییر وضعیت سفارش")], max_length=40)),
                ("payload", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("delivered_at", models.DateTimeField(blank=True, db_index=True, null=True)),
            ],
            options={"ordering": ["id"]},
        ),
    ]
