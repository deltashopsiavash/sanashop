"""Inspect and restore SanaShop archives from a local file inside the web container.

Use after transferring a .sanabackup via SFTP/docker cp when the foreign
Telegram bot cannot download the document from Telegram.
"""
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from shop.backup import restore_backup_archive, validate_backup_archive


class Command(BaseCommand):
    help = "Preview/restore a local SanaShop .sanabackup. Requires --confirm to change any data."

    def add_arguments(self, parser):
        parser.add_argument("archive", help="Path to .sanabackup accessible inside the container")
        parser.add_argument(
            "--confirm", action="store_true",
            help="Replace this site's database and media only after reviewing the preview"
        )

    def handle(self, *args, **options):
        path = Path(options["archive"])
        if path.suffix.lower() != ".sanabackup" or not path.is_file():
            raise CommandError("A readable .sanabackup file is required.")
        try:
            manifest = validate_backup_archive(path)
        except Exception as exc:
            raise CommandError(f"Backup validation failed: {exc}") from exc

        self.stdout.write("SanaShop backup validated:")
        self.stdout.write(f"  Backup date: {manifest.get('created_at') or 'unknown'}")
        self.stdout.write(f"  DB rows: {manifest.get('database_objects') or 'unknown'}")
        self.stdout.write(f"  Media files: {manifest.get('media_file_count') or 0}")
        self.stdout.write(f"  File size: {path.stat().st_size:,} bytes")
        if not options["confirm"]:
            self.stdout.write(self.style.WARNING(
                "Preview only. No data changed. To replace the database and media, "
                "rerun the same command with --confirm."
            ))
            return

        self.stdout.write(self.style.WARNING(
            "RESTORE CONFIRMED: replacing current database and media. "
            "Creating an emergency snapshot first..."
        ))
        try:
            emergency = restore_backup_archive(path)
        except Exception as exc:
            raise CommandError(f"Restore failed; built-in rollback was attempted: {exc}") from exc

        self.stdout.write(self.style.SUCCESS("Backup restored successfully."))
        self.stdout.write(
            "Emergency pre-restore backup: " + str(emergency)
        )
        self.stdout.write(
            "Do not remove the emergency backup until the store is verified. "
            "Deployment secrets in .env are deliberately not included in site backups."
        )
