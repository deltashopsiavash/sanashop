"""Product color management in each independent SanaShop Telegram site panel."""
import logging
import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

import external_bot as core

logger = logging.getLogger(__name__)

PREFIXES = (
    "prod_colors_v21:", "color_add_v21:", "color_edit_v21:",
    "color_toggle_v21:", "color_delete_v21:", "color_delete_confirm_v21:",
)
TEXT_FLOWS = {"v21_color_add", "v21_color_edit"}
PRESET = {
    "مشکی": "#000000", "سفید": "#FFFFFF", "قرمز": "#FF0000",
    "آبی": "#0066CC", "سبز": "#008000", "صورتی": "#FF69B4",
    "طلایی": "#D4AF37", "نقره‌ای": "#C0C0C0",
    "زرد": "#FFD700", "طوسی": "#808080", "بنفش": "#800080",
    "قهوه‌ای": "#8B4513", "کرم": "#F5DEB3",
}


def handles(data):
    return str(data or "").startswith(PREFIXES)


def _site(uid, sid):
    try:
        sid = int(sid)
    except (TypeError, ValueError):
        return None
    return core.get_site(sid) if core.can_access(uid, sid) else None


def _back(sid, pid):
    return InlineKeyboardButton("⬅️ مدیریت همین محصول", callback_data=f"product:{sid}:{pid}")


async def _show(q, site, sid, pid):
    status = (await core.api(site, "ping"))["site"]
    if "product_colors_v21" not in status.get("capabilities", []):
        return await q.edit_message_text(
            "⚠️ قابلیت رنگ هنوز روی همین سایت نصب نشده است. ابتدا سرور این سایت را آپدیت کن.",
            reply_markup=InlineKeyboardMarkup([[_back(sid, pid)]]),
        )
    data = (await core.api(site, "product_colors_list", {"id": pid}))["data"]
    colors = data["colors"]
    rows = []
    for item in colors:
        cid = item["id"]
        title = f"{'✅' if item['is_active'] else '🚫'} {item['name']} ({item['hex_code']})"
        rows.append([InlineKeyboardButton(title[:63], callback_data=f"color_edit_v21:{sid}:{pid}:{cid}")])
        rows.append([
            InlineKeyboardButton("🔄 فعال/غیرفعال", callback_data=f"color_toggle_v21:{sid}:{pid}:{cid}"),
            InlineKeyboardButton("🗑 حذف", callback_data=f"color_delete_v21:{sid}:{pid}:{cid}"),
        ])
    rows += [
        [InlineKeyboardButton("➕ افزودن رنگ جدید", callback_data=f"color_add_v21:{sid}:{pid}")],
        [_back(sid, pid)],
    ]
    text = (
        f"🎨 رنگ‌های «{data['product_name']}» در سایت «{site['name']}»\n\n"
        + ("برای تغییر نام یا کد رنگ روی نام رنگ بزن.\n" if colors else "هنوز رنگی تعریف نشده است.\n")
        + "هر رنگ فقط به همین محصول تعلق دارد. موجودی بین رنگ‌ها مشترک است."
    )
    return await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows))


async def callback(update, context):
    q = update.callback_query
    parts = (q.data or "").split(":")
    if not parts or not handles(q.data):
        return None
    action = parts[0]
    if len(parts) not in (3, 4):
        return await q.answer("درخواست نامعتبر", show_alert=True)
    try:
        sid, pid = int(parts[1]), int(parts[2])
        cid = int(parts[3]) if len(parts) == 4 else None
    except ValueError:
        return await q.answer("شناسه نامعتبر", show_alert=True)
    site = _site(q.from_user.id, sid)
    if site is None:
        return await q.answer("عدم دسترسی به این سایت", show_alert=True)
    await q.answer()
    if action == "prod_colors_v21":
        return await _show(q, site, sid, pid)
    if action in ("color_add_v21", "color_edit_v21"):
        context.user_data.clear()
        context.user_data.update(
            flow="v21_color_add" if action == "color_add_v21" else "v21_color_edit",
            site_id=sid, product_id=pid, color_id=cid,
        )
        return await q.edit_message_text(
            "🎨 نام رنگ و کد HEX را به این شکل بفرست:\n\nمشکی | #000000\nصورتی | #FF69B4\n\n"
            "برای رنگ‌های رایج می‌توانی فقط نام فارسی آن را بفرستی؛ کد رنگ خودکار انتخاب می‌شود.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(
                "⬅️ بازگشت به رنگ‌ها", callback_data=f"prod_colors_v21:{sid}:{pid}"
            )]]),
        )
    if cid is None:
        return await q.edit_message_text("شناسه رنگ انتخاب نشده است.")
    if action == "color_toggle_v21":
        items = (await core.api(site, "product_colors_list", {"id": pid}))["data"]["colors"]
        item = next((x for x in items if x["id"] == cid), None)
        if not item:
            return await q.edit_message_text("این رنگ وجود ندارد.")
        await core.api(site, "product_colors_update", {
            "id": pid, "color_id": cid, "is_active": not item["is_active"],
        })
        return await _show(q, site, sid, pid)
    if action == "color_delete_v21":
        return await q.edit_message_text(
            "⚠️ این رنگ از گزینه‌های خرید حذف می‌شود؛ رنگ سفارش‌های قبلی محفوظ می‌ماند. تأیید می‌کنی؟",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🗑 بله، حذف رنگ", callback_data=f"color_delete_confirm_v21:{sid}:{pid}:{cid}")],
                [InlineKeyboardButton("انصراف", callback_data=f"prod_colors_v21:{sid}:{pid}")],
            ]),
        )
    if action == "color_delete_confirm_v21":
        await core.api(site, "product_colors_delete", {"id": pid, "color_id": cid})
        return await _show(q, site, sid, pid)


async def message(update, context):
    if context.user_data.get("flow") not in TEXT_FLOWS:
        return False
    uid = update.effective_user.id
    sid, pid = context.user_data.get("site_id"), context.user_data.get("product_id")
    site = _site(uid, sid)
    if not site or not pid:
        context.user_data.clear()
        await update.message.reply_text("⛔️ دسترسی به سایت انتخابی ندارید.")
        return True
    raw = (update.message.text or "").strip()
    if "|" in raw:
        name, hex_code = [x.strip() for x in raw.split("|", 1)]
    else:
        name, hex_code = raw, PRESET.get(raw)
    if not name or len(name) > 60 or not hex_code or not re.fullmatch(r"#[a-fA-F0-9]{6}", hex_code):
        await update.message.reply_text("فرمت صحیح: مشکی | #000000 (یا نام رنگ‌های رایج مثل سفید)")
        return True
    payload = {"id": int(pid), "name": name, "hex_code": hex_code}
    if context.user_data["flow"] == "v21_color_edit":
        payload["color_id"] = context.user_data.get("color_id")
        action = "product_colors_update"
    else:
        action = "product_colors_add"
    try:
        await core.api(site, action, payload)
    except Exception as exc:
        logger.exception("Product color update failed (site=%s product=%s)", sid, pid)
        await update.message.reply_text(f"❌ رنگ ذخیره نشد: {str(exc)[:180]}")
        return True
    context.user_data.clear()
    await update.message.reply_text(
        f"✅ رنگ «{name}» برای همین محصول ذخیره شد.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🎨 مشاهده رنگ‌ها", callback_data=f"prod_colors_v21:{sid}:{pid}")
        ]]),
    )
    return True
