import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("shop", "0009_default_footer_pages")]

    operations = [
        migrations.CreateModel(
            name="ProductColor",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=60, verbose_name="نام رنگ")),
                ("hex_code", models.CharField(
                    max_length=7, default="#808080",
                    validators=[django.core.validators.RegexValidator(
                        regex=r"^#[0-9A-Fa-f]{6}$",
                        message="کد رنگ باید به صورت #RRGGBB باشد.",
                    )], verbose_name="کد رنگ",
                )),
                ("is_active", models.BooleanField(default=True, verbose_name="قابل انتخاب")),
                ("sort_order", models.PositiveIntegerField(default=0, verbose_name="ترتیب")),
                ("product", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="colors", to="shop.product",
                )),
            ],
            options={"ordering": ["sort_order", "id"]},
        ),
        migrations.AddConstraint(
            model_name="productcolor",
            constraint=models.UniqueConstraint(
                fields=("product", "name"), name="unique_product_color_name"
            ),
        ),
        migrations.AddField(
            model_name="orderitem",
            name="selected_color",
            field=models.CharField(
                max_length=60, blank=True, default="", verbose_name="رنگ انتخاب‌شده"
            ),
        ),
        migrations.AddField(
            model_name="orderitem",
            name="color_hex",
            field=models.CharField(
                max_length=7, blank=True, default="", verbose_name="کد رنگ سفارش"
            ),
        ),
    ]
