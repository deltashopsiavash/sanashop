"""Per-site Telegram manager for numbered product choices.

All callbacks and text flows re-authorize the exact selected site before
calling that site's API. No option data is stored in the bot registry.
"""
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

import external_bot as core

logger = logging.getLogger(__name__)
PREFIXES = (
    "opts_v22:", "opt_add_v22:", "opt_item_v22:", "opt_price_v22:",
    "opt_name_v22:", "opt_switch_v22:", "opt_del_v22:", "opt_del_yes_v22:",
)
FLOWS = {"v22_option_add", "v22_option_price", "v22_option_name"}


def handles(data):
    return str(data or "").startswith(PREFIXES)


def _site(uid, sid):
    try:
        sid = int(sid)
    except (ValueError, TypeError):
        return None
    return core.get_site(sid) if core.can_access(uid, sid) else None


def _money(value):
    return f"{int(value):,}"


def _back(sid, pid):
    return InlineKeyboardButton("⬅️ محصول اصلی", callback_data=f"product:{sid}:{pid}")


async def _list(q, site, sid, pid):
    ping = (await core.api(site, "ping"))["site"]
    if "product_options_v22" not in ping.get("capabilities", []):
        return await q.edit_message_text(
            "⚠️ مدیریت محصولات شماره‌دار روی این سایت هنوز فعال نیست. ابتدا همان سایت را آپدیت کن.",
            reply_markup=InlineKeyboardMarkup([[_back(sid, pid)]]),
        )
    info = (await core.api(site, "product_options_list", {"id": pid}))["data"]
    options = info["options"]
    rows = [[InlineKeyboardButton(
        f"{'✅' if o['is_available'] else '⛔️ ناموجود'} | شماره {o['number']} | {_money(o['price'])} تومان",
        callback_data=f"opt_item_v22:{sid}:{pid}:{o['id']}"
    )] for o in options]
    rows += [
        [InlineKeyboardButton("➕ افزودن محصول شماره‌دار", callback_data=f"opt_add_v22:{sid}:{pid}")],
        [_back(sid, pid)],
    ]
    return await q.edit_message_text(
        f"🔢 گزینه‌های خرید «{info['product_name']}» در «{site['name']}»\n"
        "شماره‌های روی عکس‌های گالری را با شماره گزینه‌ها هماهنگ کن.\n\n"
        "هر گزینه قیمت و وضعیت فروش خودش را دارد. گزینه ناموجود در سایت می‌ماند.\n"
        "موجودی تعدادی بین گزینه‌ها مشترک است.",
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def _item(q, site, sid, pid, oid):
    info = (await core.api(site, "product_options_list", {"id": pid}))["data"]
    option = next((o for o in info["options"] if o["id"] == oid), None)
    if not option:
        return await q.edit_message_text(
            "این گزینه حذف شده است.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ گزینه‌ها", callback_data=f"opts_v22:{sid}:{pid}")]]),
        )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 ویرایش قیمت", callback_data=f"opt_price_v22:{sid}:{pid}:{oid}"),
         InlineKeyboardButton("✏️ شماره / عنوان", callback_data=f"opt_name_v22:{sid}:{pid}:{oid}")],
        [InlineKeyboardButton("🔄 موجود / ناموجود", callback_data=f"opt_switch_v22:{sid}:{pid}:{oid}"),
         InlineKeyboardButton("🗑 حذف کامل", callback_data=f"opt_del_v22:{sid}:{pid}:{oid}")],
        [InlineKeyboardButton("⬅️ فهرست گزینه‌ها", callback_data=f"opts_v22:{sid}:{pid}")],
    ])
    return await q.edit_message_text(
        f"🔢 {option['label']}\n"
        f"کد خرید: {option['code']}\n"
        f"💵 قیمت: {_money(option['price'])} تومان\n"
        f"📦 وضعیت: {'موجود' if option['is_available'] else 'ناموجود'}\n\n"
        "ویرایش یا حذف این گزینه، جزئیات سفارش‌های قبلی را تغییر نمی‌دهد.",
        reply_markup=kb,
    )


async def callback(update, context):
    q = update.callback_query
    parts = str(q.data or "").split(":")
    action = parts[0]
    if len(parts) not in (3, 4) or not handles(q.data):
        return await q.answer("درخواست نامعتبر است.", show_alert=True)
    try:
        sid, pid = int(parts[1]), int(parts[2])
        oid = int(parts[3]) if len(parts) == 4 else None
    except ValueError:
        return await q.answer("شناسه نامعتبر است.", show_alert=True)
    site = _site(q.from_user.id, sid)
    if not site:
        return await q.answer("عدم دسترسی به این سایت", show_alert=True)
    await q.answer()
    if action == "opts_v22":
        return await _list(q, site, sid, pid)
    if action in ("opt_add_v22", "opt_price_v22", "opt_name_v22"):
        context.user_data.clear()
        flow = {
            "opt_add_v22": "v22_option_add",
            "opt_price_v22": "v22_option_price",
            "opt_name_v22": "v22_option_name",
        }[action]
        context.user_data.update(flow=flow, site_id=sid, product_id=pid, option_id=oid)
        prompt = {
            "v22_option_add": (
                "➕ شماره، قیمت (تومان) و نام اختیاری را بفرست:\n"
                "1 | 185000 | گردنبند\n"
                "2 | 95000 | انگشتر\n"
                "اگر نام نمی‌خواهی: 3 | 130000"
            ),
            "v22_option_price": "💰 فقط قیمت جدید این گزینه را به تومان بفرست. مثال: 185000",
            "v22_option_name": "✏️ شماره و نام اختیاری را بفرست. مثال: 3 | دستبند",
        }[flow]
        return await q.edit_message_text(
            prompt,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ انصراف", callback_data=f"opts_v22:{sid}:{pid}")]]),
        )
    if oid is None:
        return await q.answer("گزینه انتخاب نشده.", show_alert=True)
    if action in ("opt_item_v22", "opt_switch_v22", "opt_del_v22", "opt_del_yes_v22"):
        if action == "opt_item_v22":
            return await _item(q, site, sid, pid, oid)
        if action == "opt_del_v22":
            return await q.edit_message_text(
                "⚠️ این گزینه از فهرست محصول حذف می‌شود، اما شماره و کد داخل سفارش‌های قبلی محفوظ است. تأیید می‌کنی؟",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🗑 بله، حذف شود", callback_data=f"opt_del_yes_v22:{sid}:{pid}:{oid}")],
                    [InlineKeyboardButton("انصراف", callback_data=f"opt_item_v22:{sid}:{pid}:{oid}")],
                ]),
            )
        if action == "opt_del_yes_v22":
            await core.api(site, "product_options_delete", {"id": pid, "option_id": oid})
            return await _list(q, site, sid, pid)
        options = (await core.api(site, "product_options_list", {"id": pid}))["data"]["options"]
        option = next((o for o in options if o["id"] == oid), None)
        if not option:
            return await _list(q, site, sid, pid)
        await core.api(site, "product_options_update", {
            "id": pid, "option_id": oid, "is_available": not option["is_available"],
        })
        return await _item(q, site, sid, pid, oid)


def _price(text):
    normalized = str(text).translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))
    normalized = normalized.replace(",", "").replace("،", "").replace("٬", "").strip()
    return int(normalized) if normalized.isascii() and normalized.isdigit() else 0


async def message(update, context):
    flow = context.user_data.get("flow")
    if flow not in FLOWS:
        return False
    uid = update.effective_user.id
    sid, pid = context.user_data.get("site_id"), context.user_data.get("product_id")
    site = _site(uid, sid)
    if not site or not pid:
        context.user_data.clear()
        await update.message.reply_text("⛔️ دسترسی به سایت انتخابی ندارید.")
        return True
    raw = (update.message.text or "").strip()
    try:
        payload = {"id": int(pid)}
        if flow == "v22_option_add":
            parts = [part.strip() for part in raw.split("|", 2)]
            if len(parts) < 2 or not parts[0].isdecimal():
                raise ValueError("فرمت: شماره | قیمت | عنوان اختیاری")
            payload.update(number=int(parts[0]), price=_price(parts[1]), name=parts[2] if len(parts) == 3 else "")
            if payload["price"] < 1:
                raise ValueError("قیمت صحیح به تومان وارد کن.")
            action = "product_options_add"
        elif flow == "v22_option_price":
            price = _price(raw)
            if price < 1:
                raise ValueError("قیمت صحیح به تومان وارد کن.")
            payload.update(option_id=int(context.user_data["option_id"]), price=price)
            action = "product_options_update"
        else:
            parts = [part.strip() for part in raw.split("|", 1)]
            if not parts[0].isdecimal():
                raise ValueError("فرمت: شماره | عنوان اختیاری")
            payload.update(option_id=int(context.user_data["option_id"]), number=int(parts[0]), name=parts[1] if len(parts) == 2 else "")
            action = "product_options_update"
        await core.api(site, action, payload)
    except ValueError as exc:
        await update.message.reply_text(f"❌ {exc}\nدوباره اطلاعات صحیح را ارسال کن.")
        return True
    except Exception:
        logger.exception("Numbered option save failed site=%s product=%s", sid, pid)
        await update.message.reply_text("❌ ذخیره گزینه انجام نشد؛ شماره تکراری یا ارتباط سایت را بررسی کن.")
        return True
    context.user_data.clear()
    await update.message.reply_text(
        "✅ گزینه محصول ذخیره شد.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(
            "🔢 بازگشت به محصولات شماره‌دار", callback_data=f"opts_v22:{sid}:{pid}"
        )]]),
    )
    return True
