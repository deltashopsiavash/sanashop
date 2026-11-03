import io
import json
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase


class SafeLocalRestoreCommandTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.backup = Path(self.tmp.name) / "old-site.sanabackup"
        with zipfile.ZipFile(self.backup, "w") as archive:
            archive.writestr("manifest.json", json.dumps({
                "format": "sanashop-backup",
                "schema_version": 1,
                "database_objects": 17,
                "media_file_count": 3,
                "created_at": "2026-11-02T21:43:34Z",
            }))
            archive.writestr("database.json", "[]")

    def test_preview_is_read_only_by_default(self):
        stdout = io.StringIO()
        with patch(
            "shop.management.commands.restore_store_backup.restore_backup_archive"
        ) as restore:
            call_command("restore_store_backup", str(self.backup), stdout=stdout)
            restore.assert_not_called()
        self.assertIn("Preview only", stdout.getvalue())
        self.assertIn("2026-11-02", stdout.getvalue())

    def test_invalid_archive_not_restored_even_with_confirm(self):
        path = Path(self.tmp.name) / "invalid.sanabackup"
        path.write_bytes(b"not a backup")
        with patch(
            "shop.management.commands.restore_store_backup.restore_backup_archive"
        ) as restore:
            with self.assertRaises(CommandError):
                call_command("restore_store_backup", str(path), "--confirm")
            restore.assert_not_called()

    def test_confirm_calls_restore_and_reports_emergency_snapshot(self):
        stdout = io.StringIO()
        emergency = Path("/app/backups/sanashop-before-restore.sanabackup")
        with patch(
            "shop.management.commands.restore_store_backup.restore_backup_archive",
            return_value=emergency,
        ) as restore:
            call_command("restore_store_backup", str(self.backup), "--confirm", stdout=stdout)
            restore.assert_called_once_with(self.backup)
        self.assertIn("Backup restored successfully", stdout.getvalue())
        self.assertIn(str(emergency), stdout.getvalue())
