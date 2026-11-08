import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("shop", "0010_product_colors_order_snapshots")]

    operations = [
        migrations.CreateModel(
            name="ProductOption",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("number", models.PositiveIntegerField(validators=[django.core.validators.MinValueValidator(1)], verbose_name="شماره محصول")),
                ("name", models.CharField(max_length=120, blank=True, default="", verbose_name="عنوان اختیاری")),
                ("price", models.PositiveBigIntegerField(validators=[django.core.validators.MinValueValidator(1)], verbose_name="قیمت (تومان)")),
                ("is_available", models.BooleanField(default=True, verbose_name="موجود و قابل خرید")),
                ("sort_order", models.PositiveIntegerField(default=0, verbose_name="ترتیب")),
                ("product", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="numbered_options", to="shop.product")),
            ],
            options={"ordering": ["sort_order", "number", "id"]},
        ),
        migrations.AddConstraint(
            model_name="productoption",
            constraint=models.UniqueConstraint(fields=("product", "number"), name="unique_product_option_number"),
        ),
        migrations.AddField(
            model_name="orderitem",
            name="option_number",
            field=models.PositiveIntegerField(blank=True, null=True, verbose_name="شماره زیرمحصول"),
        ),
        migrations.AddField(
            model_name="orderitem",
            name="option_code",
            field=models.CharField(blank=True, default="", max_length=90, verbose_name="کد زیرمحصول سفارش"),
        ),
        migrations.AddField(
            model_name="orderitem",
            name="option_title",
            field=models.CharField(blank=True, default="", max_length=120, verbose_name="عنوان زیرمحصول سفارش"),
        ),
    ]
