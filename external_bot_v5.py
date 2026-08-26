#!/usr/bin/env python3
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

import external_bot as core
import external_bot_plus as plus


def _save_connected_site(url, api_key, name):
    """Upsert a site while remaining compatible with older bot.sqlite3 schemas."""
    with core.db() as conn:
        existing = conn.execute("SELECT id FROM sites WHERE base_url=?", (url,)).fetchone()
        if existing:
            conn.execute(
                "UPDATE sites SET name=?, api_key=? WHERE id=?",
                (name, api_key, existing["id"]),
            )
        else:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(sites)").fetchall()}
            if "owner_id" in columns:
                conn.execute(
                    "INSERT INTO sites(name, base_url, api_key, owner_id) VALUES(?,?,?,?)",
                    (name, url, api_key, core.OWNER_ID),
                )
            else:
                conn.execute(
                    "INSERT INTO sites(name, base_url, api_key) VALUES(?,?,?)",
                    (name, url, api_key),
                )
        conn.commit()


async def callback(update: Update, context):
    q = update.callback_query
    uid = q.from_user.id
    data = q.data or ""

    if data.startswith("footer:"):
        _, sid = data.split(":")
        site = plus.site_from(uid, sid)
        if not site:
            return await q.answer("عدم دسترسی", show_alert=True)
        await q.answer()
        x = (await core.api(site, "settings_get"))["data"]
        text = (
            f"🦶 فوتر سایت\n\n"
            f"📍 آدرس: {x.get('address') or '-'}\n"
            f"☎️ تلفن: {x.get('phone') or '-'}\n"
            f"✉️ ایمیل: {x.get('contact_email') or '-'}\n"
            f"📝 توضیح: {x.get('footer_description') or '-'}\n"
            f"🛡 اینماد: {'✅' if x.get('has_enamad_image') else '❌'}"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⚙️ تنظیم کامل فوتر", callback_data=f"footer_setup:{sid}")],
            [InlineKeyboardButton("📍 آدرس", callback_data=f"footer_address:{sid}"), InlineKeyboardButton("☎️ تلفن", callback_data=f"footer_phone:{sid}")],
            [InlineKeyboardButton("✉️ ایمیل", callback_data=f"footer_email:{sid}"), InlineKeyboardButton("📝 توضیح فوتر", callback_data=f"footer_desc:{sid}")],
            [InlineKeyboardButton("🔗 شبکه‌های اجتماعی", callback_data=f"socials:{sid}"), InlineKeyboardButton("🛡 عکس اینماد", callback_data=f"enamad:{sid}")],
            [InlineKeyboardButton("⬅️ پنل سایت", callback_data=f"site_info:{sid}")],
        ])
        return await q.edit_message_text(text, reply_markup=kb)

    if data.startswith("footer_setup:"):
        _, sid = data.split(":")
        site = plus.site_from(uid, sid)
        if not site:
            return await q.answer("عدم دسترسی", show_alert=True)
        await q.answer()
        context.user_data.clear()
        context.user_data.update(flow="footer_setup_address", site_id=int(sid))
        return await q.edit_message_text("📍 آدرس کامل فروشگاه را بفرستید:\nبرای خالی گذاشتن فقط - بفرستید.")

    if data.startswith("social_platform_v4:"):
        _, sid, platform = data.split(":", 2)
        site = plus.site_from(uid, sid)
        if not site:
            return await q.answer("عدم دسترسی", show_alert=True)
        await q.answer()
        context.user_data.clear()
        context.user_data.update(flow="v4_social_url", site_id=int(sid), platform=platform)
        label = plus.PLATFORM_LABELS.get(platform, "شبکه اجتماعی")
        return await q.edit_message_text(f"لینک کامل {label} را بفرستید:")

    if data.startswith("social_toggle_v4:"):
        _, sid, social_id = data.split(":")
        site = plus.site_from(uid, sid)
        if not site:
            return await q.answer("عدم دسترسی", show_alert=True)
        await q.answer()
        item = (await core.api(site, "social_detail", {"id": int(social_id)}))["data"]
        await core.api(site, "social_update", {"id": int(social_id), "is_active": not item["is_active"]})
        return await q.edit_message_text(
            "✅ وضعیت تغییر کرد.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ شبکه‌ها", callback_data=f"socials:{sid}")]]),
        )

    if data.startswith("social_delete_v4:"):
        _, sid, social_id = data.split(":")
        site = plus.site_from(uid, sid)
        if not site:
            return await q.answer("عدم دسترسی", show_alert=True)
        await q.answer()
        await core.api(site, "social_delete", {"id": int(social_id)})
        return await q.edit_message_text(
            "✅ شبکه اجتماعی حذف شد.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ شبکه‌ها", callback_data=f"socials:{sid}")]]),
        )

    if data.startswith("banner_toggle_v4:"):
        _, sid, banner_id = data.split(":")
        site = plus.site_from(uid, sid)
        if not site:
            return await q.answer("عدم دسترسی", show_alert=True)
        await q.answer()
        item = (await core.api(site, "banner_detail", {"id": int(banner_id)}))["data"]
        await core.api(site, "banner_update", {"id": int(banner_id), "is_active": not item["is_active"]})
        return await q.edit_message_text(
            "✅ وضعیت بنر تغییر کرد.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ بنرها", callback_data=f"banners:{sid}")]]),
        )

    if data.startswith("banner_delete_v4:"):
        _, sid, banner_id = data.split(":")
        site = plus.site_from(uid, sid)
        if not site:
            return await q.answer("عدم دسترسی", show_alert=True)
        await q.answer()
        await core.api(site, "banner_delete", {"id": int(banner_id)})
        return await q.edit_message_text(
            "✅ بنر حذف شد.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ بنرها", callback_data=f"banners:{sid}")]]),
        )

    if data.startswith("story_toggle_v4:"):
        _, sid, story_id = data.split(":")
        site = plus.site_from(uid, sid)
        if not site:
            return await q.answer("عدم دسترسی", show_alert=True)
        await q.answer()
        item = (await core.api(site, "story_detail", {"id": int(story_id)}))["data"]
        await core.api(site, "story_update", {"id": int(story_id), "is_active": not item["is_active"]})
        return await q.edit_message_text(
            "✅ وضعیت معرفی محصول تغییر کرد.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ استوری‌ها", callback_data=f"stories:{sid}")]]),
        )

    if data.startswith("story_delete_v4:"):
        _, sid, story_id = data.split(":")
        site = plus.site_from(uid, sid)
        if not site:
            return await q.answer("عدم دسترسی", show_alert=True)
        await q.answer()
        await core.api(site, "story_delete", {"id": int(story_id)})
        return await q.edit_message_text(
            "✅ معرفی محصول حذف شد.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ استوری‌ها", callback_data=f"stories:{sid}")]]),
        )

    return await plus.callback(update, context)


async def message(update: Update, context):
    flow = context.user_data.get("flow")
    uid = update.effective_user.id
    text = (update.message.text or "").strip()

    # Handle reconnect here so bot databases created by older SanaShop versions
    # (where sites.owner_id was NOT NULL) can still save a newly connected site.
    if flow == "connect_key" and core.is_owner(uid):
        url = context.user_data.get("url")
        if not url:
            context.user_data.clear()
            return await update.message.reply_text("درخواست اتصال منقضی شده است؛ /start را بزنید و دوباره تلاش کنید.")
        fake = {"base_url": url, "api_key": text}
        try:
            info = await core.api(fake, "ping")
            name = info["site"]["name"]
            _save_connected_site(url, text, name)
        except Exception as exc:
            return await update.message.reply_text(
                f"❌ اتصال ناموفق:\n{exc}\n\nبعد از اصلاح، /start را بزنید و دوباره تلاش کنید."
            )
        context.user_data.clear()
        return await update.message.reply_text(
            f"✅ سایت «{name}» به ربات متصل شد.\nبرای دسترسی مدیران از بخش «مدیران» استفاده کنید.",
            reply_markup=core.owner_home(),
        )

    guided = {
        "footer_setup_address",
        "footer_setup_phone",
        "footer_setup_email",
        "footer_setup_desc",
    }
    if flow in guided:
        site_id = context.user_data.get("site_id")
        if not site_id or not core.can_access(uid, int(site_id)):
            context.user_data.clear()
            return await update.message.reply_text("⛔️ دسترسی شما به این سایت لغو شده است.")
        site = core.get_site(int(site_id))
        value = "" if text == "-" else text
        if flow == "footer_setup_address":
            await core.api(site, "settings_update", {"address": value})
            context.user_data["flow"] = "footer_setup_phone"
            return await update.message.reply_text("☎️ شماره تماس را بفرستید:\nبرای خالی گذاشتن - بفرستید.")
        if flow == "footer_setup_phone":
            await core.api(site, "settings_update", {"phone": value})
            context.user_data["flow"] = "footer_setup_email"
            return await update.message.reply_text("✉️ ایمیل فروشگاه را بفرستید:\nبرای خالی گذاشتن - بفرستید.")
        if flow == "footer_setup_email":
            if text != "-" and ("@" not in text or "." not in text.rsplit("@", 1)[-1]):
                return await update.message.reply_text("ایمیل معتبر بفرستید؛ مثال shop@example.com")
            await core.api(site, "settings_update", {"contact_email": value})
            context.user_data["flow"] = "footer_setup_desc"
            return await update.message.reply_text("📝 یک توضیح کوتاه برای پایین فوتر بفرستید:\nبرای خالی گذاشتن - بفرستید.")
        await core.api(site, "settings_update", {"footer_description": value})
        context.user_data.clear()
        return await update.message.reply_text(
            "✅ اطلاعات اصلی فوتر کامل شد.\nحالا از بخش فوتر می‌توانی شبکه‌های اجتماعی و عکس اینماد را هم تنظیم کنی.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🦶 باز کردن فوتر", callback_data=f"footer:{site_id}")]]),
        )

    footer_fields = {
        "footer_address": "address",
        "footer_phone": "phone",
        "footer_email": "contact_email",
        "footer_desc": "footer_description",
    }
    if flow in footer_fields:
        site_id = context.user_data.get("site_id")
        if not site_id or not core.can_access(uid, int(site_id)):
            context.user_data.clear()
            return await update.message.reply_text("⛔️ دسترسی شما به این سایت لغو شده است.")
        site = core.get_site(int(site_id))
        if flow == "footer_email" and text != "-" and ("@" not in text or "." not in text.rsplit("@", 1)[-1]):
            return await update.message.reply_text("ایمیل معتبر بفرستید؛ مثال shop@example.com")
        value = "" if text == "-" else text
        await core.api(site, "settings_update", {footer_fields[flow]: value})
        context.user_data.clear()
        return await update.message.reply_text(
            "✅ فوتر ذخیره شد.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ فوتر", callback_data=f"footer:{site_id}")]]),
        )
    return await plus.message(update, context)


def run():
    core.db()
    app = Application.builder().token(core.TOKEN).post_init(plus.post_init).build()
    app.add_handler(CommandHandler("start", core.start))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.Document.ALL, plus.media))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message))
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    run()
