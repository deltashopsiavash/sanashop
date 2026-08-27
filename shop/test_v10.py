import base64
import io
import json
import os
import zipfile
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.test import Client, TestCase
from django.urls import reverse

from .models import SiteSetting


class BackupApiV10Tests(TestCase):
    def setUp(self):
        self.client = Client()
        self.headers = {"HTTP_AUTHORIZATION": "Bearer test-api-key"}
        self.env = patch.dict(os.environ, {"SANASHOP_BOT_API_KEY": "test-api-key"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def api(self, action, payload=None):
        return self.client.post(
            reverse("bot_api_v1"),
            data=json.dumps({"action": action, "payload": payload or {}}),
            content_type="application/json",
            **self.headers,
        )

    def test_backup_interval_status_round_trip(self):
        response = self.api("backup_interval_set", {"minutes": 60})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["interval_minutes"], 60)
        store = SiteSetting.load()
        self.assertEqual(store.backup_interval_minutes, 60)
        status = self.api("backup_status").json()["data"]
        self.assertEqual(status["interval_minutes"], 60)
        self.assertTrue(status["due"])

    def test_manual_backup_returns_valid_sanabackup(self):
        response = self.api("backup_create", {"label": "test"})
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertTrue(data["filename"].endswith(".sanabackup"))
        raw = base64.b64decode(data["backup_b64"])
        self.assertGreater(len(raw), 100)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            self.assertIn("manifest.json", archive.namelist())
            self.assertIn("database.json", archive.namelist())


class DistributionV10Tests(TestCase):
    def test_readme_is_only_install_and_update_commands(self):
        text = (Path(settings.BASE_DIR) / "README.md").read_text(encoding="utf-8")
        self.assertIn("install-site.sh", text)
        self.assertIn("install-bot.sh", text)
        self.assertIn("update-site.sh", text)
        self.assertIn("update-bot.sh", text)
        self.assertNotIn("امکانات نسخه فعلی", text)
        self.assertNotIn("Storefront V2", text)

    def test_bot_installers_run_v11_and_clean_stale_pollers(self):
        for filename in ("install-bot.sh", "update-bot.sh"):
            text = (Path(settings.BASE_DIR) / filename).read_text(encoding="utf-8")
            self.assertIn("external_bot_v11.py", text)
            self.assertIn("pkill -TERM", text)
            self.assertIn("runtime.lock", text)

    def test_v11_entrypoint_uses_single_instance_guard(self):
        text = (Path(settings.BASE_DIR) / "external_bot_v11.py").read_text(encoding="utf-8")
        self.assertIn("acquire_single_instance_lock", text)
        self.assertIn("v10.run()", text)

    def test_site_updater_preserves_env_and_forces_web_rebuild(self):
        text = (Path(settings.BASE_DIR) / "update-site.sh").read_text(encoding="utf-8")
        self.assertIn("git reset --hard origin/main", text)
        self.assertIn("docker compose build --pull --no-cache web", text)
        self.assertIn("python manage.py migrate --noinput", text)
        self.assertNotIn("rm -f .env", text)
