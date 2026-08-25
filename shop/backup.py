import io
import json
import shutil
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath

from django.conf import settings
from django.core.management import call_command
from django.db import connections
from django.utils import timezone

BACKUP_DIR = Path(settings.BASE_DIR) / "backups"
SCHEMA_VERSION = 1


def validate_backup_archive(path):
    path = Path(path)
    if not zipfile.is_zipfile(path):
        raise ValueError("فایل، بکاپ معتبر SanaShop نیست.")
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        if not {"manifest.json", "database.json"}.issubset(names):
            raise ValueError("فایل‌های اصلی بکاپ وجود ندارند.")
        for name in names:
            item = PurePosixPath(name)
            if item.is_absolute() or ".." in item.parts:
                raise ValueError("ساختار فایل بکاپ ناامن است.")
        manifest = json.loads(archive.read("manifest.json"))
        if manifest.get("format") != "sanashop-backup" or manifest.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("نسخه این بکاپ با سایت سازگار نیست.")
        json.loads(archive.read("database.json"))
    return manifest


def create_backup_archive(label="auto"):
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = timezone.localtime().strftime("%Y%m%d-%H%M%S")
    output = BACKUP_DIR / f"sanashop-{label}-{stamp}.sanabackup"
    database = io.StringIO()
    call_command(
        "dumpdata", "shop", "auth.User", "auth.Group",
        natural_foreign=True, natural_primary=True, indent=2, stdout=database,
    )
    manifest = {
        "format": "sanashop-backup",
        "schema_version": SCHEMA_VERSION,
        "created_at": timezone.now().isoformat(),
        "includes": ["users", "orders", "products", "settings", "media"],
    }
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        archive.writestr("database.json", database.getvalue())
        media_root = Path(settings.MEDIA_ROOT)
        if media_root.exists():
            for item in media_root.rglob("*"):
                if item.is_file() and item.name != ".restore-in-progress":
                    archive.write(item, f"media/{item.relative_to(media_root).as_posix()}")
    return output


def _load_database_json(data):
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".json", delete=False) as handle:
        handle.write(data)
        fixture = Path(handle.name)
    try:
        for connection in connections.all():
            connection.close()
        call_command("flush", interactive=False, verbosity=0)
        call_command("loaddata", str(fixture), verbosity=0)
    finally:
        fixture.unlink(missing_ok=True)


def _restore_media(archive):
    media_root = Path(settings.MEDIA_ROOT).resolve()
    media_root.mkdir(parents=True, exist_ok=True)
    for name in archive.namelist():
        if not name.startswith("media/") or name.endswith("/"):
            continue
        relative = PurePosixPath(name).relative_to("media")
        target = (media_root / Path(*relative.parts)).resolve()
        if media_root not in target.parents:
            raise ValueError("مسیر رسانه‌ای نامعتبر است.")
        target.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(name) as source, target.open("wb") as destination:
            shutil.copyfileobj(source, destination)


def restore_backup_archive(path):
    validate_backup_archive(path)
    emergency = create_backup_archive("before-restore")
    marker = Path(settings.MEDIA_ROOT) / ".restore-in-progress"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(timezone.now().isoformat(), encoding="utf-8")
    try:
        with zipfile.ZipFile(path) as archive:
            data = archive.read("database.json")
            try:
                _load_database_json(data)
                _restore_media(archive)
            except Exception:
                with zipfile.ZipFile(emergency) as rollback:
                    _load_database_json(rollback.read("database.json"))
                    _restore_media(rollback)
                raise
    finally:
        marker.unlink(missing_ok=True)
    return emergency

