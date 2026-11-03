from django.db import migrations


def seed_customer_help_pages(apps, schema_editor):
    """Create only missing pages; do not overwrite merchant-edited content."""
    ContentPage = apps.get_model("shop", "ContentPage")
    SiteSetting = apps.get_model("shop", "SiteSetting")
    store = SiteSetting.objects.first()
    terms = str(getattr(store, "terms_text", "") or "").strip()
    templates = [
        (
            "terms", "قوانین و مقررات", "guide", 1,
            terms or (
                "خرید از فروشگاه طبق قوانین جاری تجارت الکترونیکی ایران انجام می‌شود.\n"
                "مشتری در معاملات مشمول قانون حداقل ۷ روز کاری حق انصراف از زمان تحویل کالا دارد؛ "
                "استثنائات قانونی، مانند ساخت سفارشی شخصی‌سازی‌شده، مطابق مقررات اعمال می‌شوند.\n"
                "هزینه و روش ارسال پیش از ثبت نهایی سفارش اعلام می‌شود. "
                "برای پیگیری سفارش و مرجوعی از بخش تماس با ما استفاده کنید."
            ),
        ),
        (
            "contact", "تماس با ما", "contact", 1,
            "برای دریافت راهنمایی درباره سفارش، ارسال، مرجوعی یا خدمات پس از خرید، "
            "از شماره تماس و راه‌های ارتباطی درج‌شده در پایین این صفحه استفاده کنید.",
        ),
        (
            "faq", "سؤالات متداول", "guide", 2,
            "چطور سفارشم را پیگیری کنم؟\n"
            "از بخش حساب کاربری و سفارش‌های من استفاده کنید یا با پشتیبانی تماس بگیرید.\n\n"
            "هزینه و زمان ارسال چقدر است؟\n"
            "جزئیات هزینه و زمان تقریبی، مطابق روش ارسال، قبل از نهایی‌کردن خرید نمایش داده می‌شود.\n\n"
            "در صورت مغایرت محصول چه کنم؟\n"
            "شماره سفارش و توضیح مشکل را به پشتیبانی فروشگاه اعلام کنید.\n\n"
            "چطور درخواست مرجوعی ثبت کنم؟\n"
            "از اطلاعات تماس فروشگاه برای اطلاع‌دادن درخواست و دریافت راهنمای ارسال کالا استفاده کنید.",
        ),
    ]
    for slug, title, group, order, body in templates:
        ContentPage.objects.get_or_create(
            slug=slug,
            defaults={
                "title": title,
                "body": body,
                "footer_group": group,
                "show_in_footer": True,
                "is_active": True,
                "sort_order": order,
            },
        )


class Migration(migrations.Migration):
    dependencies = [("shop", "0008_product_promotion_prices")]

    operations = [
        migrations.RunPython(seed_customer_help_pages, migrations.RunPython.noop),
    ]
