#!/usr/bin/env python3
import base64
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from bot_single_instance import acquire_single_instance_lock
import external_bot as core
import external_bot_v10 as v10
import external_bot_v13 as v13
import external_bot_v15 as v15

logger = logging.getLogger(__name__)


def _site(uid, sid):
    try:
        sid = int(sid)
    except (TypeError, ValueError):
        return None
    if not core.can_access(uid, sid):
        return None
    return core.get_site(sid)


async def _show_categories(q, site, sid):
    rows = (await core.api(site, "categories"))["data"]
    keys = [
        [InlineKeyboardButton(
            f"{'✅' if item['is_active'] else '⛔️'} {item['name']}",
            callback_data=f"category:{sid}:{item['id']}",
        )]
        for item in rows[:50]
    ]
    keys.append([InlineKeyboardButton("➕ دسته جدید", callback_data=f"category_add:{sid}")])
    keys.append([InlineKeyboardButton("⬅️ پنل سایت", callback_data=f"site_info:{sid}")])
    return await q.edit_message_text("🗂 دسته‌بندی‌ها:", reply_markup=InlineKeyboardMarkup(keys))


async def _show_category(q, site, sid, cid):
    item = (await core.api(site, "category_detail", {"id": int(cid)}))["data"]
    text = (
        f"🗂 {item['name']}\n"
        f"محصولات فعال: {item.get('product_count', 0)}\n"
        f"عکس دسته: {'✅ دارد' if item.get('has_image') else '❌ ندارد'}\n"
        f"وضعیت: {'فعال' if item.get('is_active') else 'غیرفعال'}"
    )
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✏️ تغییر نام", callback_data=f"cat_name:{sid}:{item['id']}"),
            InlineKeyboardButton("🖼 عکس دسته", callback_data=f"cat_photo_v16:{sid}:{item['id']}"),
        ],
        [InlineKeyboardButton("🔄 فعال/غیرفعال", callback_data=f"cat_toggle:{sid}:{item['id']}")],
        [InlineKeyboardButton("🗑 حذف کامل دسته", callback_data=f"cat_delete_v16:{sid}:{item['id']}")],
        [InlineKeyboardButton("⬅️ دسته‌ها", callback_data=f"categories:{sid}")],
    ])
    return await q.edit_message_text(text, reply_markup=kb)


async def callback(update: Update, context):
    q = update.callback_query
    uid = q.from_user.id
    data = q.data or ""

    try:
        if data.startswith("categories:") and len(data.split(":")) == 2:
            _, sid = data.split(":")
            site = _site(uid, sid)
            if not site:
                return await q.answer("عدم دسترسی", show_alert=True)
            await q.answer()
            return await _show_categories(q, site, sid)

        if data.startswith("category:") and len(data.split(":")) == 3:
            _, sid, cid = data.split(":")
            site = _site(uid, sid)
            if not site:
                return await q.answer("عدم دسترسی", show_alert=True)
            await q.answer()
            return await _show_category(q, site, sid, cid)

        if data.startswith("cat_photo_v16:"):
            _, sid, cid = data.split(":")
            site = _site(uid, sid)
            if not site:
                return await q.answer("عدم دسترسی", show_alert=True)
            await q.answer()
            context.user_data.clear()
            context.user_data.update(flow="v16_cat_photo", site_id=int(sid), category_id=int(cid))
            return await q.edit_message_text(
                "🖼 عکس جدید دسته را ارسال کنید.\n"
                "می‌توانید Photo یا فایل تصویری JPG/PNG/WEBP بفرستید.\n"
                "بعد از ذخیره، URL جدید ساخته می‌شود تا عکس قبلی از cache برنگردد."
            )

        if data.startswith("cat_delete_v16:"):
            _, sid, cid = data.split(":")
            site = _site(uid, sid)
            if not site:
                return await q.answer("عدم دسترسی", show_alert=True)
            await q.answer()
            preview = (await core.api(site, "category_delete", {"id": int(cid), "confirm": False}))["data"]
            text = (
                "⚠️ حذف کامل دسته\n\n"
                f"دسته: {preview['name']}\n"
                f"زیر‌دسته‌هایی که حذف می‌شوند: {preview.get('child_category_count', 0)}\n"
                f"محصولاتی که حذف می‌شوند: {preview.get('product_count', 0)}\n\n"
                "با تأیید، خود دسته، تمام زیر‌دسته‌ها، محصولات داخل آن‌ها و فایل‌های media مربوط حذف می‌شوند.\n"
                "این عملیات قابل برگشت نیست مگر از بکاپ کامل Restore کنید."
            )
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🗑 بله، حذف کامل", callback_data=f"cat_delete_confirm_v16:{sid}:{cid}")],
                [InlineKeyboardButton("⬅️ انصراف", callback_data=f"category:{sid}:{cid}")],
            ])
            return await q.edit_message_text(text, reply_markup=kb)

        if data.startswith("cat_delete_confirm_v16:"):
            _, sid, cid = data.split(":")
            site = _site(uid, sid)
            if not site:
                return await q.answer("عدم دسترسی", show_alert=True)
            await q.answer("در حال حذف کامل...")
            result = (await core.api(site, "category_delete", {"id": int(cid), "confirm": True}, timeout=60))["data"]
            await q.edit_message_text(
                "✅ دسته کامل حذف شد.\n"
                f"دسته‌ها: {result.get('category_count', 1)}\n"
                f"محصولات: {result.get('product_count', 0)}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ دسته‌ها", callback_data=f"categories:{sid}")]]),
            )
            return

        return await v15.callback(update, context)
    except Exception as exc:
        logger.exception("v16 category/media action failed: %s", data)
        site = v13._site_from_data(uid, data)
        try:
            await q.answer("عملیات ناموفق بود؛ اتصال سایت حفظ شده است.", show_alert=False)
        except Exception:
            pass
        return await v13._safe_reply(
            q,
            f"❌ عملیات انجام نشد، ولی اتصال سایت حذف نشده است.\n\nخطا: {str(exc)[:700]}",
            v13._site_keyboard(site, uid),
        )


async def message(update: Update, context):
    return await v15.message(update, context)


async def media(update: Update, context):
    if context.user_data.get("flow") != "v16_cat_photo":
        return await v15.media(update, context)

    uid = update.effective_user.id
    site_id = context.user_data.get("site_id")
    category_id = context.user_data.get("category_id")
    if not site_id or not category_id or not core.can_access(uid, int(site_id)):
        context.user_data.clear()
        return await update.message.reply_text("⛔️ دسترسی شما به این سایت لغو شده است.")

    attachment = None
    filename = "category.jpg"
    if update.message.photo:
        attachment = update.message.photo[-1]
    elif update.message.document:
        mime = (update.message.document.mime_type or "").lower()
        if not mime.startswith("image/"):
            return await update.message.reply_text("فایل باید تصویر JPG، PNG یا WEBP باشد.")
        attachment = update.message.document
        filename = update.message.document.file_name or filename

    if not attachment:
        return await update.message.reply_text("یک عکس یا فایل تصویری ارسال کنید.")

    try:
        tg_file = await attachment.get_file()
        raw = bytes(await tg_file.download_as_bytearray())
        encoded = base64.b64encode(raw).decode("ascii")
        site = core.get_site(int(site_id))
        await core.api(
            site,
            "category_image_set",
            {"id": int(category_id), "image_b64": encoded, "filename": filename},
            timeout=60,
        )
    except Exception as exc:
        logger.exception("Category image upload failed")
        return await update.message.reply_text(f"❌ عکس ذخیره نشد:\n{str(exc)[:700]}")

    context.user_data.clear()
    return await update.message.reply_text(
        "✅ عکس جدید دسته ذخیره شد و آدرس فایل جدید است؛ عکس cache‌شده قبلی استفاده نمی‌شود.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ دسته", callback_data=f"category:{site_id}:{category_id}")]]),
    )


def run():
    try:
        acquire_single_instance_lock()
    except RuntimeError as exc:
        logger.error("SanaShop bot refused duplicate startup: %s", exc)
        raise SystemExit(73) from exc

    core.db()
    app = (
        Application.builder()
        .token(core.TOKEN)
        .concurrent_updates(16)
        .connection_pool_size(32)
        .pool_timeout(10.0)
        .post_init(v10.post_init)
        .build()
    )
    app.add_handler(CommandHandler("start", core.start))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.Document.ALL, media))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message))
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    run()
