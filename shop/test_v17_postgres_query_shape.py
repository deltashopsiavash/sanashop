from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class PostgreSQLQueryShapeSourceTests(SimpleTestCase):
    def test_invoice_lock_does_not_use_nullable_promotion_join(self):
        source = (Path(settings.BASE_DIR) / "shop" / "order_creation_v17.py").read_text(encoding="utf-8")
        self.assertIn('Product.objects.select_for_update().get', source)
        self.assertNotIn('select_for_update().select_related("promotion")', source)
