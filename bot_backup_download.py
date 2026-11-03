"""Safe and resilient download of store backups received by the Telegram bot.

The cloud Bot API currently limits getFile downloads to 20 MiB. Downloads are
retried only on transient network errors; invalid archives are never confirmed.
"""
import asyncio
import json
import zipfile
from pathlib import Path

from telegram.error import NetworkError

MAX_TELEGRAM_BACKUP_BYTES = 20 * 1024 * 1024
GET_FILE_TIMEOUTS = {
    "connect_timeout": 25,
    "read_timeout": 75,
    "write_timeout": 30,
    "pool_timeout": 25,
}
DOWNLOAD_TIMEOUTS = {
    "connect_timeout": 25,
    "read_timeout": 180,
    "write_timeout": 30,
    "pool_timeout": 25,
}


class BackupDownloadError(Exception):
    """Explain a download/validation error without exposing Telegram tokens."""


class BackupNetworkError(BackupDownloadError):
    pass


class BackupInvalidError(BackupDownloadError):
    pass


def validate_downloaded_backup(path):
    """Cheap structural check, *not* a substitute for site-side integrity check."""
    if not zipfile.is_zipfile(path):
        raise BackupInvalidError("فایل ZIP معتبر SanaShop نیست. فایل اصلی .sanabackup را ارسال کنید.")
    try:
        with zipfile.ZipFile(path) as archive:
            files = set(archive.namelist())
            if not {"manifest.json", "database.json"}.issubset(files):
                raise BackupInvalidError("محتوای ضروری بکاپ (manifest/database) موجود نیست.")
            manifest_info = archive.getinfo("manifest.json")
            if manifest_info.file_size > 2 * 1024 * 1024:
                raise BackupInvalidError("فایل مشخصات بکاپ بیش از حد بزرگ است.")
            with archive.open("manifest.json") as source:
                manifest = json.load(source)
            if manifest.get("format") != "sanashop-backup" or int(manifest.get("schema_version") or 0) not in (1, 2):
                raise BackupInvalidError("فرمت یا نسخه فایل بکاپ با SanaShop سازگار نیست.")
    except BackupInvalidError:
        raise
    except (ValueError, TypeError, KeyError, OSError, zipfile.BadZipFile, UnicodeError) as exc:
        raise BackupInvalidError("فایل بکاپ ناقص یا آسیب‌دیده است.") from exc


async def download_telegram_backup(document, target, attempts=3):
    """Get, download and check a Telegram document, retrying timeouts safely.

    Returns (number of bytes, attempt count). The caller owns the temporary
    file and MUST delete it on error/cancel/after a restore.
    """
    target = Path(target)
    size = int(getattr(document, "file_size", 0) or 0)
    if size > MAX_TELEGRAM_BACKUP_BYTES:
        raise BackupDownloadError(
            "این فایل برای دانلود با Telegram Bot API بزرگ است (حداکثر ۲۰ مگابایت). "
            "از روش انتقال مستقیم به سرور سایت استفاده کنید."
        )
    for attempt in range(1, attempts + 1):
        target.unlink(missing_ok=True)
        try:
            tg_file = await document.get_file(**GET_FILE_TIMEOUTS)
            await tg_file.download_to_drive(
                custom_path=str(target),
                **DOWNLOAD_TIMEOUTS,
            )
            actual = target.stat().st_size
            if actual == 0 or actual > MAX_TELEGRAM_BACKUP_BYTES:
                raise BackupInvalidError("فایل دانلودی خالی یا بزرگ‌تر از حد مجاز است.")
            if size and actual != size:
                # Partial downloads are not valid snapshots.
                raise BackupInvalidError("فایل دریافت‌شده ناقص است؛ اندازه با تلگرام مطابقت ندارد.")
            validate_downloaded_backup(target)
            return actual, attempt
        except (NetworkError, TimeoutError, ConnectionError) as exc:
            target.unlink(missing_ok=True)
            if attempt >= attempts:
                raise BackupNetworkError(
                    "ارتباط سرور ربات با تلگرام هنگام دریافت فایل قطع یا کند است؛ "
                    f"پس از {attempts} تلاش دریافت نشد. "
                    "فایل را بعداً دوباره ارسال کنید یا برای بازیابی مستقیم به سرور سایت منتقل کنید."
                ) from exc
            await asyncio.sleep(2 * attempt)
        except Exception:
            target.unlink(missing_ok=True)
            raise
    raise BackupNetworkError("دریافت فایل از تلگرام ناموفق بود.")
