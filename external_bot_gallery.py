"""Product gallery controls for the remote, multi-site Telegram admin bot (v16)."""
import base64
import io
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
import external_bot as core

logger = logging.getLogger(__name__)
PREFIXES = (
    "prod_gallery_v17:", "gallery_item_v17:", "gallery_view_v17:",
    "gallery_add_v17:", "gallery_replace_v17:", "gallery_delete_v17:",
    "gallery_confirm_v17:", "gallery_primary_v17:", "gallery_up_v17:",
    "gallery_down_v17:", "gallery_alt_v17:",
)
PHOTO_FLOWS = {"v17_gallery_add", "v17_gallery_replace"}


def handles(data):
    return str(data or "").startswith(PREFIXES)


def _site(uid, sid):
    sid = int(sid)
    if not core.can_access(uid, sid):
        return None
    return core.get_site(sid)


def _btn(label, action, sid, pid, image_id=None):
    suffix = f":{image_id}" if image_id is not None else ""
    return InlineKeyboardButton(
        label, callback_data=f"{action}:{sid}:{pid}{suffix}")


def _back(sid, pid):
    return InlineKeyboardMarkup([[
        _btn("⬅️ گالری محصول", "prod_gallery_v17", sid, pid)
    ]])


async def _gallery(q, site, sid, pid):
    data = (await core.api(site, "product_gallery_list", {"id": int(pid)}))["data"]
    count = data["count"]
    max_photos = data["max_photos"]
    rows = [
        [_btn(
            f"{'⭐️ عکس اصلی' if photo['is_primary'] else '🖼 عکس ' + str(photo['position'])}  •  مشاهده و مدیریت",
            "gallery_item_v17", sid, pid, photo["id"],
        )]
        for photo in data["photos"]
    ]
    if count < max_photos:
        rows.append([_btn("➕ افزودن عکس (چند عکس پشت‌سرهم)", "gallery_add_v17", sid, pid)])
    rows.append([_btn("⬅️ بازگشت به محصول", "product", sid, pid)])
    text = (
        f"🖼 گالری محصول: {data['name']}\n"
        f"📷 تعداد عکس‌ها: {count} از {max_photos}\n\n"
        "روی هر عکس بزن تا بتوانی آن را ببینی، جایگزین کنی، حذف کنی، "
        "عکس اصلی قرار بدهی یا ترتیبش را تغییر بدهی.\n"
        "عکس اصلی در لیست محصولات و کارت فروشگاه نمایش داده می‌شود."
    )
    return await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows))


async def _image_actions(q, site, sid, pid, image_id):
    data = (await core.api(site, "product_gallery_list", {"id": int(pid)}))["data"]
    photo = next((x for x in data["photos"] if x["id"] == image_id), None)
    if photo is None:
        return await _gallery(q, site, sid, pid)
    rows = [
        [_btn("👁 نمایش عکس", "gallery_view_v17", sid, pid, image_id)],
        [_btn("✏️ جایگزینی عکس", "gallery_replace_v17", sid, pid, image_id),
         _btn("🗑 حذف عکس", "gallery_delete_v17", sid, pid, image_id)],
    ]
    if not photo["is_primary"]:
        rows.append([_btn("⭐️ انتخاب به‌عنوان عکس اصلی", "gallery_primary_v17", sid, pid, image_id)])
        rows.append([
            _btn("⬆️ جلوتر", "gallery_up_v17", sid, pid, image_id),
            _btn("⬇️ عقب‌تر", "gallery_down_v17", sid, pid, image_id),
        ])
        rows.append([_btn("📝 تغییر متن جایگزین", "gallery_alt_v17", sid, pid, image_id)])
    rows.append([_btn("⬅️ گالری محصول", "prod_gallery_v17", sid, pid)])
    text = (
        f"🖼 تصویر شماره {photo['position']}\n"
        f"نوع: {'⭐️ عکس اصلی محصول' if photo['is_primary'] else 'تصویر گالری'}\n"
        f"توضیح عکس: {photo['alt']}\n\n"
        "برای ویرایش عکس می‌توانی تصویر جدیدی جایگزین کنی."
    )
    return await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows))


async def callback(update, context):
    q = update.callback_query
    uid = q.from_user.id
    action, sid, pid, *tail = (q.data or "").split(":")
    site = _site(uid, sid)
    if not site:
        return await q.answer("⛔️ دسترسی به این سایت ندارید.", show_alert=True)
    sid, pid = int(sid), int(pid)
    image_id = int(tail[0]) if tail else None
    await q.answer()

    if action == "prod_gallery_v17":
        context.user_data.clear()
        return await _gallery(q, site, sid, pid)
    if action == "gallery_item_v17":
        return await _image_actions(q, site, sid, pid, image_id)
    if action == "gallery_view_v17":
        photo = (await core.api(site, "product_gallery_get",
                               {"id": pid, "image_id": image_id}, timeout=50))["data"]
        image = io.BytesIO(base64.b64decode(photo["image_b64"]))
        image.name = photo.get("filename") or "product.jpg"
        # Send as separate message so the selection menu remains clickable.
        return await q.message.reply_photo(photo=image, caption="🖼 پیش‌نمایش عکس محصول")
    if action == "gallery_add_v17":
        context.user_data.clear()
        context.user_data.update(flow="v17_gallery_add", site_id=sid, product_id=pid)
        return await q.edit_message_text(
            "➕ عکس‌های محصول را یکی‌یکی ارسال کن.\n"
            "عکس تلگرامی یا فایل JPG/PNG/WEBP/GIF بفرست.\n"
            "بعد از هر عکس می‌توانی عکس بعدی را هم بفرستی. "
            "وقتی تمام شد «اتمام» را بزن.\nحداکثر حجم هر عکس: ۱۰ مگابایت.",
            reply_markup=InlineKeyboardMarkup([[
                _btn("✅ اتمام و مشاهده گالری", "prod_gallery_v17", sid, pid)
            ]]),
        )
    if action == "gallery_replace_v17":
        context.user_data.clear()
        context.user_data.update(
            flow="v17_gallery_replace", site_id=sid, product_id=pid, image_id=image_id)
        return await q.edit_message_text(
            "✏️ عکس جدید را ارسال کن تا فقط همین تصویر جایگزین شود.",
            reply_markup=_back(sid, pid),
        )
    if action == "gallery_alt_v17":
        context.user_data.clear()
        context.user_data.update(
            flow="v17_gallery_alt", site_id=sid, product_id=pid, image_id=image_id)
        return await q.edit_message_text(
            "📝 توضیح کوتاه این عکس را ارسال کن (تا ۱۸۰ نویسه).\n"
            "برای خالی کردن توضیح، فقط - بفرست.",
            reply_markup=_back(sid, pid),
        )
    if action == "gallery_delete_v17":
        return await q.edit_message_text(
            "⚠️ این عکس از گالری و فایل‌های سایت حذف می‌شود.\n"
            "اگر عکس اصلی را حذف کنی، اولین تصویر گالری جایگزین آن می‌شود. "
            "ادامه می‌دهی؟",
            reply_markup=InlineKeyboardMarkup([
                [_btn("🗑 بله، حذف عکس", "gallery_confirm_v17", sid, pid, image_id)],
                [_btn("❌ انصراف", "gallery_item_v17", sid, pid, image_id)],
            ]),
        )
    names = {
        "gallery_confirm_v17": ("product_gallery_delete", {}),
        "gallery_primary_v17": ("product_gallery_primary", {}),
        "gallery_up_v17": ("product_gallery_move", {"direction": "up"}),
        "gallery_down_v17": ("product_gallery_move", {"direction": "down"}),
    }
    if action in names:
        operation, extra = names[action]
        await core.api(site, operation, {
            "id": pid, "image_id": image_id, **extra,
        }, timeout=40)
        return await _gallery(q, site, sid, pid)


async def message(update, context):
    """Handle gallery alt-text input; other messages are handled by v15."""
    uid = update.effective_user.id
    sid = context.user_data.get("site_id")
    pid = context.user_data.get("product_id")
    if not sid or not pid or not core.can_access(uid, int(sid)):
        context.user_data.clear()
        return await update.message.reply_text("⛔️ دسترسی به سایت لغو شده است.")
    text = (update.message.text or "").strip()
    if not text or len(text) > 180:
        return await update.message.reply_text("توضیح باید بین ۱ تا ۱۸۰ نویسه باشد.")
    site = core.get_site(int(sid))
    try:
        await core.api(site, "product_gallery_alt", {
            "id": int(pid), "image_id": int(context.user_data["image_id"]),
            "alt": "" if text == "-" else text,
        })
    except Exception as exc:
        return await update.message.reply_text(f"❌ ذخیره توضیح ناموفق بود:\n{str(exc)[:500]}")
    context.user_data.clear()
    return await update.message.reply_text(
        "✅ توضیح عکس ذخیره شد.", reply_markup=_back(sid, pid))


async def media(update, context):
    uid = update.effective_user.id
    sid = context.user_data.get("site_id")
    pid = context.user_data.get("product_id")
    if not sid or not pid or not core.can_access(uid, int(sid)):
        context.user_data.clear()
        return await update.message.reply_text("⛔️ دسترسی شما به این سایت لغو شده است.")

    attachment = None
    filename = "product.jpg"
    if update.message.photo:
        attachment = update.message.photo[-1]
    elif update.message.document:
        doc = update.message.document
        if (doc.mime_type or "").lower() not in (
            "image/jpeg", "image/png", "image/webp", "image/gif"):
            return await update.message.reply_text("❌ فایل تصویری JPG/PNG/WEBP/GIF بفرست.")
        attachment = doc
        filename = doc.file_name or filename
    if attachment is None:
        return await update.message.reply_text("لطفاً عکس یا فایل تصویر بفرست.")
    if attachment.file_size and attachment.file_size > 10 * 1024 * 1024:
        return await update.message.reply_text("❌ عکس باید کمتر از ۱۰ مگابایت باشد.")

    try:
        tg_file = await attachment.get_file()
        raw = bytes(await tg_file.download_as_bytearray())
        if len(raw) > 10 * 1024 * 1024:
            return await update.message.reply_text("❌ عکس باید کمتر از ۱۰ مگابایت باشد.")
        flow = context.user_data.get("flow")
        payload = {
            "id": int(pid),
            "image_b64": base64.b64encode(raw).decode("ascii"),
            "filename": filename,
        }
        if flow == "v17_gallery_replace":
            payload["image_id"] = int(context.user_data["image_id"])
        operation = ("product_gallery_add" if flow == "v17_gallery_add"
                     else "product_gallery_replace")
        result = (await core.api(core.get_site(int(sid)), operation, payload,
                                 timeout=90))["data"]
    except Exception as exc:
        logger.exception("Product gallery upload failed")
        return await update.message.reply_text(
            f"❌ آپلود عکس انجام نشد:\n{str(exc)[:700]}")

    if flow == "v17_gallery_replace":
        context.user_data.clear()
        return await update.message.reply_text(
            "✅ تصویر موردنظر جایگزین شد و روی سایت هم تغییر کرد.",
            reply_markup=_back(sid, pid),
        )
    # Remain in add mode so a Telegram photo album / consecutive photos work.
    return await update.message.reply_text(
        f"✅ عکس اضافه شد. تعداد کل: {len(result['photos'])}\n"
        "عکس بعدی را بفرست یا دکمه اتمام را بزن.",
        reply_markup=InlineKeyboardMarkup([[
            _btn("✅ اتمام و مشاهده گالری", "prod_gallery_v17", sid, pid)
        ]]),
    )
