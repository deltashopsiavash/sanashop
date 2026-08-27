import hashlib
import io
import json
import shutil
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from django.apps import apps
from django.conf import settings
from django.core.management import call_command
from django.db import connections
from django.utils import timezone

BACKUP_DIR = Path(settings.BASE_DIR) / "backups"
SCHEMA_VERSION = 2
SUPPORTED_SCHEMA_VERSIONS = {1, 2}
DATABASE_EXCLUDES = ["contenttypes", "auth.Permission"]


def _sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _database_model_counts():
    counts = {}
    excluded = {"contenttypes.contenttype", "auth.permission"}
    for model in apps.get_models():
        label = model._meta.label_lower
        if label in excluded:
            continue
        try:
            counts[label] = model._default_manager.count()
        except Exception:
            # A third-party/unmanaged model must never make a site backup fail.
            continue
    return counts


def _collect_media_manifest(media_root):
    files = []
    total_bytes = 0
    if not media_root.exists():
        return files, total_bytes
    for item in sorted(media_root.rglob("*")):
        if not item.is_file() or item.name == ".restore-in-progress":
            continue
        relative = item.relative_to(media_root).as_posix()
        size = item.stat().st_size
        files.append({"path": relative, "size": size, "sha256": _sha256_file(item)})
        total_bytes += size
    return files, total_bytes


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
        version = int(manifest.get("schema_version") or 0)
        if manifest.get("format") != "sanashop-backup" or version not in SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError("نسخه این بکاپ با سایت سازگار نیست.")

        database_raw = archive.read("database.json")
        json.loads(database_raw)

        if version >= 2:
            if manifest.get("database_sha256") != _sha256_bytes(database_raw):
                raise ValueError("کنترل صحت دیتابیس بکاپ ناموفق بود.")
            media_files = manifest.get("media_files") or []
            for item in media_files:
                relative = str(item.get("path") or "")
                member = f"media/{relative}"
                if not relative or member not in names:
                    raise ValueError("یکی از فایل‌های media بکاپ ناقص است.")
                raw = archive.read(member)
                if len(raw) != int(item.get("size") or 0):
                    raise ValueError("اندازه یکی از فایل‌های media بکاپ معتبر نیست.")
                if _sha256_bytes(raw) != item.get("sha256"):
                    raise ValueError("کنترل صحت یکی از فایل‌های media ناموفق بود.")
    return manifest


def create_backup_archive(label="auto"):
    """Create an exact snapshot of all application data and every uploaded media file.

    Deployment secrets (.env), source code and generated static files are intentionally not
    embedded in Telegram backups: source is restored from GitHub, static is regenerated, and
    secrets remain local to the server. Everything that represents the actual store state lives
    in the database/media snapshot below.
    """
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = timezone.localtime().strftime("%Y%m%d-%H%M%S")
    output = BACKUP_DIR / f"sanashop-full-{label}-{stamp}.sanabackup"

    database = io.StringIO()
    call_command(
        "dumpdata",
        exclude=DATABASE_EXCLUDES,
        natural_foreign=True,
        natural_primary=True,
        indent=2,
        stdout=database,
    )
    database_raw = database.getvalue().encode("utf-8")

    media_root = Path(settings.MEDIA_ROOT)
    media_files, media_bytes = _collect_media_manifest(media_root)
    model_counts = _database_model_counts()
    manifest = {
        "format": "sanashop-backup",
        "schema_version": SCHEMA_VERSION,
        "backup_kind": "full-site",
        "created_at": timezone.now().isoformat(),
        "includes": [
            "all_application_database_rows",
            "users_and_permissions",
            "customers_and_profiles",
            "products_and_product_gallery",
            "categories",
            "orders_order_items_receipts_and_status_history",
            "discounts",
            "site_settings_and_payment_settings",
            "content_pages",
            "banners_and_stories",
            "social_links_and_footer",
            "notifications_and_site_events",
            "email_verification_state",
            "all_uploaded_media",
        ],
        "database_excludes": DATABASE_EXCLUDES,
        "database_sha256": _sha256_bytes(database_raw),
        "database_objects": sum(model_counts.values()),
        "model_counts": model_counts,
        "media_file_count": len(media_files),
        "media_bytes": media_bytes,
        "media_files": media_files,
        "deployment_secrets_included": False,
    }

    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        archive.writestr("database.json", database_raw)
        for item in media_files:
            source = media_root / Path(*PurePosixPath(item["path"]).parts)
            archive.write(source, f"media/{item['path']}")

    # Never hand a backup to the bot before its manifest/database/media integrity was verified.
    validate_backup_archive(output)
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


def _clear_media(media_root):
    media_root.mkdir(parents=True, exist_ok=True)
    for item in list(media_root.iterdir()):
        if item.name == ".restore-in-progress":
            continue
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink(missing_ok=True)


def _restore_media(archive, replace=True):
    media_root = Path(settings.MEDIA_ROOT).resolve()
    media_root.mkdir(parents=True, exist_ok=True)
    if replace:
        _clear_media(media_root)
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
    """Restore the database and make MEDIA_ROOT exactly match the backup snapshot."""
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
                _restore_media(archive, replace=True)
            except Exception:
                with zipfile.ZipFile(emergency) as rollback:
                    _load_database_json(rollback.read("database.json"))
                    _restore_media(rollback, replace=True)
                raise
    finally:
        marker.unlink(missing_ok=True)
    return emergency
