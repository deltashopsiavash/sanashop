#!/usr/bin/env python3
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

import external_bot as core
import external_bot_plus as plus


async def callback(update: Update, context):
    q = update.callback_query
    uid = q.from_user.id
    data = q.data or ""

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
        text = (update.message.text or "").strip()
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
