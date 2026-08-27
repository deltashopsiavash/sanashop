from django.db import migrations, models
import django.db.models.deletion


def migrate_legacy_prices(apps, schema_editor):
    Product = apps.get_model("shop", "Product")
    ProductPromotion = apps.get_model("shop", "ProductPromotion")

    for product in Product.objects.all().iterator():
        old_price = product.compare_at_price
        current_price = product.price

        if old_price and old_price > current_price:
            defaults = {}
            if product.is_amazing:
                defaults["amazing_price"] = current_price
            else:
                defaults["discount_price"] = current_price
            ProductPromotion.objects.update_or_create(product_id=product.id, defaults=defaults)
            product.price = old_price
            product.compare_at_price = None
            product.save(update_fields=["price", "compare_at_price"])
        elif product.is_amazing:
            # Old amazing mode had no dedicated price. Disable it until a manager sets one.
            product.is_amazing = False
            product.save(update_fields=["is_amazing"])


def reverse_legacy_prices(apps, schema_editor):
    Product = apps.get_model("shop", "Product")
    ProductPromotion = apps.get_model("shop", "ProductPromotion")
    for promo in ProductPromotion.objects.select_related("product").all().iterator():
        product = promo.product
        special = promo.amazing_price if product.is_amazing and promo.amazing_price else promo.discount_price
        if special and special < product.price:
            product.compare_at_price = product.price
            product.price = special
            product.save(update_fields=["price", "compare_at_price"])


class Migration(migrations.Migration):
    dependencies = [("shop", "0007_customer_profiles_email_otp")]

    operations = [
        migrations.CreateModel(
            name="ProductPromotion",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("discount_price", models.PositiveBigIntegerField(blank=True, null=True)),
                ("amazing_price", models.PositiveBigIntegerField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "product",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="promotion",
                        to="shop.product",
                    ),
                ),
            ],
            options={
                "verbose_name": "قیمت ویژه محصول",
                "verbose_name_plural": "قیمت‌های ویژه محصولات",
            },
        ),
        migrations.RunPython(migrate_legacy_prices, reverse_legacy_prices),
    ]
