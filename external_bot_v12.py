#!/usr/bin/env python3
import logging
from urllib.parse import urlsplit

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from bot_single_instance import acquire_single_instance_lock
import external_bot as core
import external_bot_plus as plus
import external_bot_v10 as v10

logger = logging.getLogger(__name__)


def _normalize_site_url(value):
    value = str(value or "").strip()
    if not value:
        raise ValueError("آدرس سایت خالی است.")
    if "://" not in value:
        value = "https://" + value
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("آدرس سایت معتبر نیست.")
    if parsed.username or parsed.password:
        raise ValueError("آدرس سایت نباید شامل نام کاربری یا رمز باشد.")
    netloc = parsed.netloc.lower()
    return f"{parsed.scheme.lower()}://{netloc}".rstrip("/")


def _upsert_connected_site(url, api_key, name):
    """Persist a verified site and support databases created by older bot versions."""
    with core.db() as conn:
        columns = {row[1]: row for row in conn.execute("PRAGMA table_info(sites)").fetchall()}
        existing = conn.execute("SELECT id FROM sites WHERE base_url=?", (url,)).fetchone()
        if existing:
            site_id = int(existing["id"])
            conn.execute(
                "UPDATE sites SET name=?, api_key=?, base_url=? WHERE id=?",
                (name, api_key, url, site_id),
            )
        else:
            if "owner_id" in columns:
                cursor = conn.execute(
                    "INSERT INTO sites(name, base_url, api_key, owner_id) VALUES(?,?,?,?)",
                    (name, url, api_key, core.OWNER_ID),
                )
            else:
                cursor = conn.execute(
                    "INSERT INTO sites(name, base_url, api_key) VALUES(?,?,?)",
                    (name, url, api_key),
                )
            site_id = int(cursor.lastrowid)
        conn.commit()
        saved = conn.execute(
            "SELECT id,name,base_url FROM sites WHERE id=? AND base_url=?",
            (site_id, url),
        ).fetchone()
        if not saved:
            raise RuntimeError("ذخیره سایت در دیتابیس ربات تأیید نشد.")
        return site_id


async def callback(update: Update, context):
    q = update.callback_query
    uid = q.from_user.id
    data = q.data or ""

    if data == "connect":
        if not core.is_owner(uid):
            await q.answer("فقط مالک اصلی می‌تواند سایت اضافه کند.", show_alert=True)
            return
        await q.answer()
        context.user_data.clear()
        context.user_data["flow"] = "v12_connect_url"
        return await q.edit_message_text(
            "🔗 اتصال سایت جدید\n\nآدرس دامنه سایت را بفرستید.\nمثال:\nhttps://shop.example.com"
        )

    return await v10.callback(update, context)


async def message(update: Update, context):
    uid = update.effective_user.id
    flow = context.user_data.get("flow")
    text = (update.message.text or "").strip()

    if flow == "v12_connect_url" and core.is_owner(uid):
        try:
            url = _normalize_site_url(text)
        except ValueError as exc:
            return await update.message.reply_text(f"❌ {exc}\nدوباره آدرس سایت را بفرستید.")
        context.user_data.clear()
        context.user_data.update(flow="v12_connect_key", connect_url=url)
        return await update.message.reply_text(
            f"🌐 آدرس ثبت موقت شد:\n{url}\n\n🔑 حالا SANASHOP_BOT_API_KEY همین سایت را بفرستید."
        )

    if flow == "v12_connect_key" and core.is_owner(uid):
        url = context.user_data.get("connect_url")
        api_key = text
        if not url:
            context.user_data.clear()
            return await update.message.reply_text("❌ مرحله اتصال منقضی شده؛ /start را بزنید و دوباره اتصال سایت را انتخاب کنید.")
        if len(api_key) < 8:
            return await update.message.reply_text("❌ کلید اتصال معتبر نیست؛ SANASHOP_BOT_API_KEY سایت را دوباره بفرستید.")

        await update.message.reply_text("⏳ در حال تست API و ثبت سایت...")
        candidate = {"base_url": url, "api_key": api_key}
        try:
            info = await core.api(candidate, "ping", timeout=30)
            site_info = info.get("site") or {}
            name = str(site_info.get("name") or urlsplit(url).hostname or "SanaShop").strip()[:120]
            site_id = _upsert_connected_site(url, api_key, name)
            saved = core.get_site(site_id)
            if not saved:
                raise RuntimeError("سایت بعد از ذخیره از دیتابیس قابل خواندن نیست.")
        except Exception as exc:
            logger.exception("Direct site connection failed url=%s", url)
            return await update.message.reply_text(
                f"❌ سایت ثبت نشد.\n{exc}\n\nآدرس ذخیره موقت مانده؛ کلید را دوباره بفرستید یا /start را برای شروع مجدد بزنید."
            )

        context.user_data.clear()
        await update.message.reply_text(
            f"✅ سایت واقعاً در دیتابیس ربات ثبت شد.\n🏪 {saved['name']}\n🌐 {saved['base_url']}\n🆔 شناسه سایت: {saved['id']}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🏪 باز کردن پنل سایت", callback_data=f"open_site:{saved['id']}")],
                [InlineKeyboardButton("⬅️ پنل مالک", callback_data="owner_home")],
            ]),
        )
        return

    return await v10.message(update, context)


def run():
    try:
        acquire_single_instance_lock()
    except RuntimeError as exc:
        logger.error("SanaShop bot refused duplicate startup: %s", exc)
        raise SystemExit(73) from exc

    core.db()
    app = Application.builder().token(core.TOKEN).post_init(v10.post_init).build()
    app.add_handler(CommandHandler("start", core.start))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.Document.ALL, v10.media))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message))
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    run()
