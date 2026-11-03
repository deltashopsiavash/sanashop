"""Regression tests for foreign-bot backup downloads and per-site restore gates."""
import asyncio
import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-only-invalid-token")
os.environ.setdefault("TELEGRAM_OWNER_ID", "111")

from telegram.error import TimedOut

import bot_backup_download as backup
import external_bot_v10 as v10


def backup_bytes():
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr("manifest.json", json.dumps({
            "format": "sanashop-backup", "schema_version": 2,
            "created_at": "2026-11-02T21:43:34+00:00",
        }))
        archive.writestr("database.json", "[]")
    return data.getvalue()


class FakeFile:
    def __init__(self, owner):
        self.owner = owner

    async def download_to_drive(self, **kwargs):
        self.owner.download_kwargs.append(kwargs)
        self.owner.download_attempts += 1
        if self.owner.download_attempts <= self.owner.fail_download:
            raise TimedOut("Timed out")
        Path(kwargs["custom_path"]).write_bytes(self.owner.content)


class FakeDocument:
    file_name = "sanashop-full-auto.sanabackup"

    def __init__(self, content=None, fail_get=0, fail_download=0, file_size=None):
        self.content = content if content is not None else backup_bytes()
        self.file_size = len(self.content) if file_size is None else file_size
        self.fail_get = fail_get
        self.fail_download = fail_download
        self.get_calls = 0
        self.download_attempts = 0
        self.get_kwargs = []
        self.download_kwargs = []

    async def get_file(self, **kwargs):
        self.get_calls += 1
        self.get_kwargs.append(kwargs)
        if self.get_calls <= self.fail_get:
            raise TimedOut("Timed out")
        return FakeFile(self)


class TelegramBackupDownloaderTests(unittest.IsolatedAsyncioTestCase):
    async def test_first_timeout_then_success(self):
        doc = FakeDocument(fail_get=1)
        with tempfile.TemporaryDirectory() as tmp, patch.object(backup.asyncio, "sleep", new_callable=AsyncMock) as sleeping:
            path = Path(tmp) / "backup.sanabackup"
            size, attempts = await backup.download_telegram_backup(doc, path)
            self.assertEqual(size, len(doc.content))
            self.assertEqual(attempts, 2)
            self.assertEqual(doc.get_calls, 2)
            self.assertEqual(path.read_bytes(), doc.content)
            self.assertEqual(sleeping.await_count, 1)
            self.assertGreater(doc.get_kwargs[0]["read_timeout"], 5)
            self.assertGreater(doc.download_kwargs[0]["read_timeout"], 5)

    async def test_download_timeout_is_retried_and_cleans_partial(self):
        doc = FakeDocument(fail_download=3)
        with tempfile.TemporaryDirectory() as tmp, patch.object(backup.asyncio, "sleep", new_callable=AsyncMock):
            path = Path(tmp) / "backup.sanabackup"
            with self.assertRaises(backup.BackupNetworkError) as caught:
                await backup.download_telegram_backup(doc, path)
            self.assertIn("۳ تلاش", str(caught.exception))
            self.assertEqual(doc.get_calls, 3)
            self.assertFalse(path.exists())

    async def test_invalid_archive_is_rejected_without_retry(self):
        doc = FakeDocument(content=b"broken-backup")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "broken.sanabackup"
            with self.assertRaises(backup.BackupInvalidError):
                await backup.download_telegram_backup(doc, path)
            self.assertEqual(doc.get_calls, 1)
            self.assertFalse(path.exists())

    async def test_oversized_telegram_file_is_rejected_before_getfile(self):
        doc = FakeDocument(file_size=backup.MAX_TELEGRAM_BACKUP_BYTES + 1)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(backup.BackupDownloadError):
                await backup.download_telegram_backup(doc, Path(tmp) / "file.sanabackup")
            self.assertEqual(doc.get_calls, 0)

    async def test_partial_download_is_not_accepted(self):
        doc = FakeDocument(file_size=len(backup_bytes()) + 10)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(backup.BackupInvalidError):
                await backup.download_telegram_backup(doc, Path(tmp) / "file.sanabackup")


class LiveBotRestoreFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_bot_only_enables_confirmation_after_download_and_site_check(self):
        doc = FakeDocument(fail_get=1)
        reply = AsyncMock()
        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=222),
            message=SimpleNamespace(document=doc, reply_text=reply),
        )
        context = SimpleNamespace(user_data={"flow": "v10_restore_upload", "site_id": 7})
        with patch.object(v10.core, "can_access", return_value=True), patch.object(
            backup.asyncio, "sleep", new_callable=AsyncMock
        ):
            await v10.media(update, context)
        self.assertEqual(context.user_data["flow"], "v10_restore_confirm")
        path = Path(context.user_data["restore_path"])
        try:
            self.assertTrue(path.exists())
            markup = reply.await_args_list[-1].kwargs["reply_markup"]
            callbacks = [b.callback_data for row in markup.inline_keyboard for b in row]
            self.assertIn("backup_restore_confirm_v10:7", callbacks)
            self.assertNotIn("backup_restore_confirm_v10:8", callbacks)
        finally:
            path.unlink(missing_ok=True)

    async def test_timeout_keeps_pending_upload_and_never_enables_restore(self):
        doc = FakeDocument(fail_get=3)
        reply = AsyncMock()
        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=222),
            message=SimpleNamespace(document=doc, reply_text=reply),
        )
        context = SimpleNamespace(user_data={"flow": "v10_restore_upload", "site_id": 7})
        with patch.object(v10.core, "can_access", return_value=True), patch.object(
            backup.asyncio, "sleep", new_callable=AsyncMock
        ):
            await v10.media(update, context)
        self.assertEqual(context.user_data["flow"], "v10_restore_upload")
        self.assertNotIn("restore_path", context.user_data)
        self.assertIn("دریافت فایل ناموفق", reply.await_args_list[-1].args[0])

    async def test_switched_site_during_download_never_offers_confirmation(self):
        doc = FakeDocument()
        reply = AsyncMock()
        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=222),
            message=SimpleNamespace(document=doc, reply_text=reply),
        )
        context = SimpleNamespace(user_data={"flow": "v10_restore_upload", "site_id": 7})

        async def switched(doc, path):
            Path(path).write_bytes(backup_bytes())
            context.user_data.update(flow="v10_restore_upload", site_id=8)
            return Path(path).stat().st_size, 1

        with patch.object(v10.core, "can_access", return_value=True), patch.object(
            v10.backup_download, "download_telegram_backup", side_effect=switched
        ):
            await v10.media(update, context)
        self.assertEqual(context.user_data["site_id"], 8)
        self.assertNotIn("restore_path", context.user_data)
        self.assertIn("سایت انتخابی تغییر", reply.await_args_list[-1].args[0])


if __name__ == "__main__":
    unittest.main()
