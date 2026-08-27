import base64
import hashlib
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

    def test_manual_backup_is_full_integrity_checked_snapshot(self):
        response = self.api("backup_create", {"label": "test"})
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertTrue(data["filename"].endswith(".sanabackup"))
        raw = base64.b64decode(data["backup_b64"])
        self.assertGreater(len(raw), 100)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            self.assertIn("manifest.json", archive.namelist())
            self.assertIn("database.json", archive.namelist())
            manifest = json.loads(archive.read("manifest.json"))
            database_raw = archive.read("database.json")
            self.assertEqual(manifest["schema_version"], 2)
            self.assertEqual(manifest["backup_kind"], "full-site")
            self.assertIn("all_application_database_rows", manifest["includes"])
            self.assertIn("all_uploaded_media", manifest["includes"])
            self.assertEqual(manifest["database_sha256"], hashlib.sha256(database_raw).hexdigest())
            self.assertIn("model_counts", manifest)
            self.assertIn("media_files", manifest)
            self.assertFalse(manifest["deployment_secrets_included"])


class DistributionV10Tests(TestCase):
    def test_readme_is_only_install_and_update_commands(self):
        text = (Path(settings.BASE_DIR) / "README.md").read_text(encoding="utf-8")
        self.assertIn("install-site.sh", text)
        self.assertIn("install-bot.sh", text)
        self.assertIn("update-site.sh", text)
        self.assertIn("update-bot.sh", text)
        self.assertNotIn("امکانات نسخه فعلی", text)
        self.assertNotIn("Storefront V2", text)

    def test_bot_installers_run_v15_and_clean_stale_pollers(self):
        for filename in ("install-bot.sh", "update-bot.sh"):
            text = (Path(settings.BASE_DIR) / filename).read_text(encoding="utf-8")
            self.assertIn("external_bot_v15.py", text)
            self.assertIn("pkill -TERM", text)
            self.assertIn("runtime.lock", text)

    def test_v12_handles_connection_without_legacy_message_chain(self):
        text = (Path(settings.BASE_DIR) / "external_bot_v12.py").read_text(encoding="utf-8")
        self.assertIn('data == "connect"', text)
        self.assertIn('flow == "v12_connect_url"', text)
        self.assertIn('flow == "v12_connect_key"', text)
        self.assertIn("_upsert_connected_site", text)
        self.assertIn('core.api(candidate, "ping"', text)
        self.assertIn("سایت واقعاً در دیتابیس ربات ثبت شد", text)
        self.assertIn("acquire_single_instance_lock", text)

    def test_v13_guards_action_errors_without_deleting_site(self):
        text = (Path(settings.BASE_DIR) / "external_bot_v13.py").read_text(encoding="utf-8")
        self.assertIn("_backup_version_guard", text)
        self.assertIn("await v12.callback", text)
        self.assertIn("اتصال سایت از ربات حذف نشده", text)
        self.assertIn("اتصال ذخیره‌شده سایت دست‌نخورده باقی ماند", text)
        self.assertNotIn("DELETE FROM sites", text)

    def test_v14_processes_buttons_concurrently_and_avoids_backup_pre_ping(self):
        text = (Path(settings.BASE_DIR) / "external_bot_v14.py").read_text(encoding="utf-8")
        self.assertIn(".concurrent_updates(16)", text)
        self.assertIn(".connection_pool_size(32)", text)
        self.assertIn("await v12.callback", text)
        self.assertNotIn("_backup_version_guard", text)
        self.assertIn("بکاپ کامل صفر تا صد", text)

    def test_full_backup_replaces_media_and_covers_all_application_data(self):
        text = (Path(settings.BASE_DIR) / "shop" / "backup.py").read_text(encoding="utf-8")
        self.assertIn("SCHEMA_VERSION = 2", text)
        self.assertIn('"dumpdata"', text)
        self.assertIn("exclude=DATABASE_EXCLUDES", text)
        self.assertIn("_collect_media_manifest", text)
        self.assertIn("database_sha256", text)
        self.assertIn("_clear_media", text)
        self.assertIn("_restore_media(archive, replace=True)", text)

    def test_site_updater_preserves_env_and_forces_web_rebuild(self):
        text = (Path(settings.BASE_DIR) / "update-site.sh").read_text(encoding="utf-8")
        self.assertIn("git reset --hard origin/main", text)
        self.assertIn("docker compose build --pull --no-cache web", text)
        self.assertIn("python manage.py migrate --noinput", text)
        self.assertNotIn("rm -f .env", text)
