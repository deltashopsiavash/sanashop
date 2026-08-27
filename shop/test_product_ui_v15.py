from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class ProductUiV15Tests(SimpleTestCase):
    def test_product_card_is_clickable_beyond_image(self):
        text = (Path(settings.BASE_DIR) / "templates" / "shop" / "_product_card.html").read_text(encoding="utf-8")
        self.assertIn("product-card-hitarea", text)
        self.assertIn("مشاهده جزئیات", text)
        self.assertIn("product-card-form", text)

    def test_base_and_promotion_prices_are_explicit(self):
        card = (Path(settings.BASE_DIR) / "templates" / "shop" / "_product_card.html").read_text(encoding="utf-8")
        detail = (Path(settings.BASE_DIR) / "templates" / "shop" / "product.html").read_text(encoding="utf-8")
        for text in (card, detail):
            self.assertIn("قیمت اصلی", text)
            self.assertIn("قیمت با تخفیف", text)
            self.assertIn("قیمت شگفت‌انگیز", text)
            self.assertIn("<del>", text)
            self.assertIn("promotion_label", text)

    def test_iran_updater_has_clear_quiet_database_progress(self):
        text = (Path(settings.BASE_DIR) / "update-site.sh").read_text(encoding="utf-8")
        self.assertIn("[5/9] بررسی و اعمال migrationهای دیتابیس", text)
        self.assertIn("migrate --noinput --verbosity 0", text)
        self.assertIn("✅ دیتابیس آماده است.", text)
        self.assertIn("collectstatic --noinput --clear --verbosity 0", text)
