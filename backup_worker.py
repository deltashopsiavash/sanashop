#!/usr/bin/env python3
import asyncio
import os
from datetime import timedelta

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django
django.setup()

from asgiref.sync import sync_to_async
from django.utils import timezone
from telegram import Bot

from shop.backup import create_backup_archive
from shop.models import SiteSetting

ADMIN_IDS = [int(x) for x in os.environ.get("TELEGRAM_ADMIN_IDS", "").split(",") if x.strip().isdigit()]
MAX_TELEGRAM_BYTES = 48 * 1024 * 1024


async def send_backup(bot, chat_id, label="auto"):
    path = await asyncio.to_thread(create_backup_archive, label)
    if path.stat().st_size > MAX_TELEGRAM_BYTES:
        await bot.send_message(chat_id, f"⚠️ بکاپ ساخته شد ولی حجم آن بیشتر از ۴۸ مگابایت است و در تلگرام ارسال نشد.\nمسیر سرور: {path}")
        return path
    with path.open("rb") as document:
        await bot.send_document(chat_id, document=document, filename=path.name, caption="🔐 بکاپ کامل SanaShop؛ شامل کاربران، سفارش‌ها، محصولات، تنظیمات و تصاویر")
    return path


async def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is required")
    async with Bot(token) as bot:
        while True:
            store = await sync_to_async(SiteSetting.load)()
            interval = store.backup_interval_minutes
            due = interval and (not store.last_backup_at or timezone.now() >= store.last_backup_at + timedelta(minutes=interval))
            if due:
                for chat_id in ADMIN_IDS:
                    try:
                        await send_backup(bot, chat_id)
                    except Exception as exc:
                        await bot.send_message(chat_id, f"❌ ساخت یا ارسال بکاپ ناموفق بود: {exc}")
                store.last_backup_at = timezone.now()
                await store.asave(update_fields=["last_backup_at", "updated_at"])
            await asyncio.sleep(60)


if __name__ == "__main__":
    asyncio.run(main())
