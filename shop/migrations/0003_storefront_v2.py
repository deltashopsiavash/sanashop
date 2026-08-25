from django.db import migrations, models
import django.core.validators
import django.db.models.deletion


def seed_pages(apps, schema_editor):
    Page = apps.get_model("shop", "ContentPage")
    defaults = [
        ("راهنمای خرید", "buy-guide", "guide", "برای خرید، محصول موردنظر را به سبد اضافه کنید، اطلاعات گیرنده را کامل کنید و روش پرداخت را انتخاب کنید."),
        ("قوانین و شرایط", "terms", "guide", "ثبت سفارش به معنی پذیرش مشخصات محصول، مبلغ، روش ارسال و قوانین جاری فروشگاه است."),
        ("رویه بازگشت کالا", "returns", "guide", "در صورت ایراد یا مغایرت، پیش از استفاده از کالا با پشتیبانی فروشگاه تماس بگیرید."),
        ("حریم خصوصی", "privacy", "guide", "اطلاعات مشتری فقط برای ثبت، ارسال و پیگیری سفارش استفاده می‌شود."),
        ("ارتباط با ما", "contact", "contact", "برای پرسش درباره محصول یا پیگیری سفارش از راه‌های ارتباطی فروشگاه استفاده کنید."),
        ("آدرس", "address", "contact", "آدرس فروشگاه را از ربات تلگرام ویرایش کنید."),
        ("درباره ما", "about", "other", "درباره فروشگاه و داستان برندتان در این بخش بنویسید."),
    ]
    try:
        Store = apps.get_model("shop", "SiteSetting")
        store = Store.objects.filter(pk=1).first()
    except Exception:
        store = None
    for i, (title, slug, group, body) in enumerate(defaults):
        if store and slug == "terms" and store.terms_text:
            body = store.terms_text
        elif store and slug == "returns" and store.return_policy:
            body = store.return_policy
        elif store and slug == "address" and store.address:
            body = store.address
        Page.objects.get_or_create(slug=slug, defaults={"title": title, "footer_group": group, "body": body, "sort_order": i})


class Migration(migrations.Migration):
    dependencies = [("shop", "0002_accounts_tracking_backups")]
    operations = [
        migrations.AddField(model_name="product", name="is_amazing", field=models.BooleanField(default=False, verbose_name="پیشنهاد شگفت‌انگیز")),
        migrations.AddField(model_name="product", name="amazing_until", field=models.DateTimeField(blank=True, null=True, verbose_name="پایان شگفت‌انگیز")),
        migrations.AddField(model_name="order", name="discount_amount", field=models.PositiveBigIntegerField(default=0)),
        migrations.AddField(model_name="order", name="discount_code", field=models.CharField(blank=True, max_length=50)),
        migrations.CreateModel(name="ContentPage", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("title", models.CharField(max_length=120)), ("slug", models.SlugField(allow_unicode=True, blank=True, max_length=150, unique=True)),
            ("body", models.TextField(blank=True)), ("footer_group", models.CharField(choices=[("guide", "راهنمای خرید"), ("contact", "ارتباط با ما"), ("other", "سایر")], default="guide", max_length=20)),
            ("show_in_footer", models.BooleanField(default=True)), ("is_active", models.BooleanField(default=True)), ("sort_order", models.PositiveIntegerField(default=0)),
            ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)),
        ], options={"ordering": ["footer_group", "sort_order", "id"]}),
        migrations.CreateModel(name="HeroSlide", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")), ("title", models.CharField(blank=True, max_length=150)),
            ("subtitle", models.CharField(blank=True, max_length=240)), ("image", models.ImageField(upload_to="banners/%Y/%m/")), ("mobile_image", models.ImageField(blank=True, upload_to="banners/mobile/%Y/%m/")),
            ("button_text", models.CharField(blank=True, default="مشاهده محصولات", max_length=60)), ("link", models.CharField(blank=True, default="/products/", max_length=300)),
            ("is_active", models.BooleanField(default=True)), ("sort_order", models.PositiveIntegerField(default=0)), ("created_at", models.DateTimeField(auto_now_add=True)),
        ], options={"ordering": ["sort_order", "id"]}),
        migrations.CreateModel(name="DiscountCode", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")), ("code", models.CharField(max_length=50, unique=True)),
            ("percent", models.PositiveSmallIntegerField(validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(99)])), ("min_order_amount", models.PositiveBigIntegerField(default=0)),
            ("max_uses", models.PositiveIntegerField(default=0, help_text="صفر یعنی بدون محدودیت")), ("used_count", models.PositiveIntegerField(default=0)), ("expires_at", models.DateTimeField(blank=True, null=True)),
            ("is_active", models.BooleanField(default=True)), ("created_at", models.DateTimeField(auto_now_add=True)),
        ], options={"ordering": ["-created_at"]}),
        migrations.RunPython(seed_pages, migrations.RunPython.noop),
    ]
