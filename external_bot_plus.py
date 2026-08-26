#!/usr/bin/env python3
import asyncio
import base64
import io
import logging
from urllib.parse import urlparse

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

import external_bot as core

logger = logging.getLogger(__name__)
ORIGINAL_CALLBACK = core.callback
ORIGINAL_MESSAGE = core.message
ORIGINAL_PHOTO = core.photo
MAX_IMAGE_BYTES = 15 * 1024 * 1024
MAX_STORY_BYTES = 48 * 1024 * 1024

PLATFORMS = [
    ("instagram", "اینستاگرام"), ("telegram", "تلگرام"), ("whatsapp", "واتساپ"),
    ("rubika", "روبیکا"), ("eitaa", "ایتا"), ("youtube", "یوتیوب"),
    ("aparat", "آپارات"), ("x", "ایکس"), ("facebook", "فیسبوک"), ("other", "سایر"),
]
PLATFORM_LABELS = dict(PLATFORMS)


def money(value):
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value or 0)


def valid_link(value, allow_relative=True):
    value = (value or "").strip()
    if allow_relative and value.startswith("/"):
        return True
    try:
        return urlparse(value).scheme in ("http", "https") and bool(urlparse(value).netloc)
    except Exception:
        return False


def site_from(uid, site_id):
    try:
        site_id = int(site_id)
    except Exception:
        return None
    if not core.can_access(uid, site_id):
        return None
    return core.get_site(site_id)


def enhanced_site_panel(site, uid):
    sid = site["id"]
    rows = [
        [InlineKeyboardButton(f"🏪 {site['name']}", callback_data=f"site_info:{sid}")],
        [InlineKeyboardButton("📊 داشبورد", callback_data=f"dash:{sid}"), InlineKeyboardButton("🛍 محصولات", callback_data=f"products:{sid}")],
        [InlineKeyboardButton("🗂 دسته‌ها", callback_data=f"categories:{sid}"), InlineKeyboardButton("🛒 سفارش‌ها", callback_data=f"orders:{sid}")],
        [InlineKeyboardButton("🧾 رسیدها", callback_data=f"receipts:{sid}"), InlineKeyboardButton("👥 کاربران", callback_data=f"users:{sid}")],
        [InlineKeyboardButton("🎞 بنرها", callback_data=f"banners:{sid}"), InlineKeyboardButton("🔴 معرفی محصول", callback_data=f"stories:{sid}")],
        [InlineKeyboardButton("🦶 فوتر", callback_data=f"footer:{sid}"), InlineKeyboardButton("🔗 شبکه‌های اجتماعی", callback_data=f"socials:{sid}")],
        [InlineKeyboardButton("🎟 کد تخفیف", callback_data=f"discounts:{sid}"), InlineKeyboardButton("⚙️ تنظیمات فروشگاه", callback_data=f"settings:{sid}")],
    ]
    if core.is_owner(uid):
        rows.append([InlineKeyboardButton("⬅️ سایت‌های متصل", callback_data="owner_sites")])
    return InlineKeyboardMarkup(rows)


core.site_panel = enhanced_site_panel


def recipients_for(site_id):
    recipients = {core.OWNER_ID}
    with core.db() as conn:
        rows = conn.execute("SELECT telegram_id FROM site_admins WHERE site_id=?", (site_id,)).fetchall()
        recipients.update(int(row["telegram_id"]) for row in rows)
    return recipients


def event_text(event):
    payload = event.get("payload") or {}
    kind = event.get("kind")
    if kind == "order_created":
        lines = [
            "🧾 فاکتور جدید ساخته شد",
            f"کد: {payload.get('code','-')}", f"مشتری: {payload.get('full_name','-')}",
            f"موبایل: {payload.get('mobile','-')}",
            f"آدرس: {payload.get('province','')}، {payload.get('city','')} — {payload.get('address','')}",
            f"روش پرداخت: {payload.get('payment_method_label','-')}",
            f"جمع کالاها: {money(payload.get('subtotal'))} تومان",
        ]
        if payload.get("discount_amount"):
            lines.append(f"تخفیف: {money(payload.get('discount_amount'))} تومان")
        lines += [
            f"ارسال: {'رایگان' if not payload.get('shipping') else money(payload.get('shipping')) + ' تومان'}",
            f"مبلغ نهایی: {money(payload.get('total'))} تومان", "", "📦 محصولات:",
        ]
        for item in payload.get("items") or []:
            lines.append(f"• {item.get('title')} × {item.get('quantity')} — {money(item.get('total'))} تومان")
        remaining = int(payload.get("reservation_remaining_seconds") or 0)
        if remaining:
            lines += ["", f"⏳ رزرو موجودی: حدود {max(1, remaining // 60)} دقیقه"]
        return "\n".join(lines)
    if kind == "payment_success":
        return f"✅ پرداخت تأیید شد\nسفارش: {payload.get('code','-')}\nمبلغ: {money(payload.get('total'))} تومان\nمشتری: {payload.get('full_name','-')}"
    if kind == "payment_failed":
        return f"❌ پرداخت ناموفق/لغوشده\nسفارش: {payload.get('code','-')}\nمبلغ: {money(payload.get('total'))} تومان"
    if kind == "reservation_expired":
        return f"⌛ مهلت رزرو فاکتور تمام شد\nسفارش: {payload.get('code','-')}\nمشتری: {payload.get('full_name','-')}"
    if kind == "order_status":
        return f"📦 تغییر وضعیت سفارش\nسفارش: {payload.get('code','-')}\nوضعیت: {payload.get('status_label') or payload.get('status','-')}\nمبلغ: {money(payload.get('total'))} تومان"
    return f"🔔 رویداد جدید سایت\n{kind}"


async def send_event(application, site, event):
    payload = event.get("payload") or {}
    recipients = recipients_for(site["id"])
    delivered = False
    if event.get("kind") == "receipt_uploaded" and payload.get("receipt_id"):
        try:
            image_data = (await core.api(site, "receipt_image", {"id": payload["receipt_id"]}, timeout=45))["data"]
            raw = base64.b64decode(image_data["image_b64"])
            caption = f"🧾 رسید کارت‌به‌کارت جدید\nسفارش: {payload.get('code','-')}\nمشتری: {payload.get('full_name','-')}\nمبلغ: {money(payload.get('total'))} تومان"
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("✅ تأیید رسید", callback_data=f"receipt_set:{site['id']}:{payload['receipt_id']}:approved"), InlineKeyboardButton("❌ رد رسید", callback_data=f"receipt_set:{site['id']}:{payload['receipt_id']}:rejected")]])
            for chat_id in recipients:
                try:
                    photo = io.BytesIO(raw); photo.name = image_data.get("filename") or "receipt.jpg"
                    await application.bot.send_photo(chat_id=chat_id, photo=photo, caption=caption, reply_markup=keyboard)
                    delivered = True
                except Exception:
                    logger.exception("Could not send receipt event to %s", chat_id)
        except Exception:
            logger.exception("Could not load receipt image for site %s", site["id"])
        return delivered
    keyboard = None
    if payload.get("order_id"):
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("باز کردن سفارش", callback_data=f"order:{site['id']}:{payload['order_id']}")]])
    for chat_id in recipients:
        try:
            await application.bot.send_message(chat_id=chat_id, text=event_text(event), reply_markup=keyboard)
            delivered = True
        except Exception:
            logger.exception("Could not send site event to %s", chat_id)
    return delivered


async def notification_loop(application):
    await asyncio.sleep(3)
    while True:
        try:
            with core.db() as conn:
                sites = conn.execute("SELECT * FROM sites ORDER BY id").fetchall()
            for site in sites:
                try:
                    events = (await core.api(site, "events_poll", {"limit": 20}, timeout=20))["data"]
                except Exception:
                    continue
                ack = []
                for event in events:
                    if await send_event(application, site, event):
                        ack.append(event["id"])
                if ack:
                    try:
                        await core.api(site, "events_ack", {"ids": ack}, timeout=20)
                    except Exception:
                        logger.exception("Could not ack events for site %s", site["id"])
        except Exception:
            logger.exception("Notification loop error")
        await asyncio.sleep(8)


async def _download_media(message, max_bytes=MAX_STORY_BYTES):
    media_type = None
    filename = None
    file_size = None
    tg_file = None
    if message.photo:
        media_type = "image"
        obj = message.photo[-1]
        file_size = getattr(obj, "file_size", None)
        tg_file = await obj.get_file()
        filename = "image.jpg"
    elif message.video:
        media_type = "video"
        file_size = message.video.file_size
        tg_file = await message.video.get_file()
        filename = message.video.file_name or "video.mp4"
    elif message.document:
        mime = message.document.mime_type or ""
        if mime.startswith("image/"):
            media_type = "image"
        elif mime.startswith("video/"):
            media_type = "video"
        else:
            raise ValueError("فایل باید عکس یا ویدئو باشد.")
        file_size = message.document.file_size
        tg_file = await message.document.get_file()
        filename = message.document.file_name or ("video.mp4" if media_type == "video" else "image.jpg")
    else:
        raise ValueError("عکس یا ویدئو ارسال کنید.")
    if file_size and file_size > max_bytes:
        raise ValueError(f"حجم فایل بیشتر از {max_bytes // 1024 // 1024} مگابایت است.")
    raw = bytes(await tg_file.download_as_bytearray())
    if len(raw) > max_bytes:
        raise ValueError(f"حجم فایل بیشتر از {max_bytes // 1024 // 1024} مگابایت است.")
    return media_type, filename, base64.b64encode(raw).decode("ascii")


def _back_site(sid):
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ پنل سایت", callback_data=f"site_info:{sid}")]])


async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    data = q.data or ""

    # Existing enhanced product screen.
    if data.startswith("product:") and len(data.split(":")) == 3:
        _, sid, pid = data.split(":")
        site = site_from(uid, sid)
        if not site:
            return await q.answer("به این سایت دسترسی ندارید.", show_alert=True)
        await q.answer()
        p = (await core.api(site, "product_detail", {"id": int(pid)}))["data"]
        old = p.get("compare_at_price")
        text = f"🛍 {p['name']}\nکد: {p['sku']}\nقیمت جدید: {money(p['price'])} تومان\nقیمت قبلی: {money(old) + ' تومان' if old else '-'}\nموجودی کل: {p['stock']}\nرزرو: {p.get('reserved_stock',0)} | قابل فروش: {p.get('available_stock',p['stock'])}\nشگفت‌انگیز: {'✅' if p['is_amazing'] else '❌'}\nوضعیت: {'فعال' if p['is_active'] else 'غیرفعال'}"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💰 قیمت جدید", callback_data=f"prod_price:{sid}:{pid}"), InlineKeyboardButton("🏷 قیمت قبلی", callback_data=f"prod_old:{sid}:{pid}")],
            [InlineKeyboardButton("📦 موجودی", callback_data=f"prod_stock:{sid}:{pid}"), InlineKeyboardButton("🔥 شگفت‌انگیز", callback_data=f"prod_amazing:{sid}:{pid}")],
            [InlineKeyboardButton("🔄 فعال/غیرفعال", callback_data=f"prod_toggle:{sid}:{pid}"), InlineKeyboardButton("🖼 تعویض عکس", callback_data=f"prod_photo:{sid}:{pid}")],
            [InlineKeyboardButton("⬅️ محصولات", callback_data=f"products:{sid}")],
        ])
        return await q.edit_message_text(text, reply_markup=kb)

    if data.startswith("prod_old:"):
        _, sid, pid = data.split(":")
        site = site_from(uid, sid)
        if not site: return await q.answer("عدم دسترسی", show_alert=True)
        await q.answer(); context.user_data.clear(); context.user_data.update(flow="prod_old_price", site_id=int(sid), product_id=int(pid))
        return await q.edit_message_text("قیمت قبلی/خط‌خورده را بفرستید. مثال: 2,900,000\nبرای حذف قیمت قبلی عدد 0 را بفرستید.")

    if data.startswith("category:") and len(data.split(":")) == 3:
        _, sid, cid = data.split(":")
        site = site_from(uid, sid)
        if not site: return await q.answer("عدم دسترسی", show_alert=True)
        await q.answer()
        c = (await core.api(site, "category_detail", {"id": int(cid)}))["data"]
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ تغییر نام", callback_data=f"cat_name:{sid}:{cid}"), InlineKeyboardButton("🔄 نمایش/توقف", callback_data=f"cat_toggle:{sid}:{cid}")],
            [InlineKeyboardButton("🖼 گذاشتن/تعویض عکس", callback_data=f"cat_photo:{sid}:{cid}"), InlineKeyboardButton("🗑 حذف عکس", callback_data=f"cat_photo_remove:{sid}:{cid}")],
            [InlineKeyboardButton("⬅️ دسته‌ها", callback_data=f"categories:{sid}")],
        ])
        return await q.edit_message_text(f"🗂 {c['name']}\nوضعیت نمایش: {'✅ فعال' if c['is_active'] else '⛔️ مخفی/متوقف'}\nعکس: {'✅ دارد' if c.get('has_image') else '❌ ندارد'}\nمحصولات فعال: {c['product_count']}", reply_markup=kb)

    if data.startswith("cat_photo:"):
        _, sid, cid = data.split(":"); site = site_from(uid, sid)
        if not site: return await q.answer("عدم دسترسی", show_alert=True)
        await q.answer(); context.user_data.clear(); context.user_data.update(flow="cat_photo", site_id=int(sid), category_id=int(cid))
        return await q.edit_message_text("عکس دسته را ارسال کنید:")

    if data.startswith("cat_photo_remove:"):
        _, sid, cid = data.split(":"); site = site_from(uid, sid)
        if not site: return await q.answer("عدم دسترسی", show_alert=True)
        await q.answer(); await core.api(site, "category_image_remove", {"id": int(cid)})
        return await q.edit_message_text("✅ عکس دسته حذف شد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ دسته", callback_data=f"category:{sid}:{cid}")]]))

    if data.startswith("receipt:") and len(data.split(":")) == 3:
        _, sid, rid = data.split(":"); site = site_from(uid, sid)
        if not site: return await q.answer("عدم دسترسی", show_alert=True)
        await q.answer()
        detail = (await core.api(site, "receipt_detail", {"id": int(rid)}))["data"]
        image = (await core.api(site, "receipt_image", {"id": int(rid)}, timeout=45))["data"]
        raw = base64.b64decode(image["image_b64"]); photo = io.BytesIO(raw); photo.name=image.get("filename") or "receipt.jpg"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ تأیید", callback_data=f"receipt_set:{sid}:{rid}:approved"), InlineKeyboardButton("❌ رد", callback_data=f"receipt_set:{sid}:{rid}:rejected")],[InlineKeyboardButton("⬅️ رسیدها", callback_data=f"receipts:{sid}")]])
        await context.bot.send_photo(chat_id=q.message.chat_id, photo=photo, caption=f"🧾 رسید سفارش {detail['order_code']}\nمشتری: {detail.get('full_name','-')}\nمبلغ: {money(detail['total'])} تومان\nوضعیت: {detail['status']}", reply_markup=kb)
        return

    # Settings / logo.
    if data.startswith("settings:"):
        _, sid = data.split(":"); site = site_from(uid, sid)
        if not site: return await q.answer("عدم دسترسی", show_alert=True)
        await q.answer(); x=(await core.api(site,"settings_get"))["data"]
        kb=InlineKeyboardMarkup([
            [InlineKeyboardButton("🖼 لوگوی سایت",callback_data=f"logo:{sid}"),InlineKeyboardButton("📣 اعلان",callback_data=f"v4_announcement:{sid}")],
            [InlineKeyboardButton("✏️ نام سایت",callback_data=f"v4_name:{sid}"),InlineKeyboardButton("🦶 تنظیمات فوتر",callback_data=f"footer:{sid}")],
            [InlineKeyboardButton("🚚 هزینه ارسال",callback_data=f"v4_shipping:{sid}"),InlineKeyboardButton("🎁 حد ارسال رایگان",callback_data=f"v4_free:{sid}")],
            [InlineKeyboardButton("💳 اطلاعات کارت",callback_data=f"v4_card:{sid}")],
            [InlineKeyboardButton("⬅️ پنل سایت",callback_data=f"site_info:{sid}")],
        ])
        return await q.edit_message_text(f"⚙️ تنظیمات {x['site_name']}\nلوگو: {'✅' if x.get('has_logo') else '❌'}\nاعلان: {x.get('announcement') or '-'}\nارسال: {money(x.get('shipping_fee'))} تومان\nارسال رایگان از: {money(x.get('free_shipping_threshold'))} تومان",reply_markup=kb)

    if data.startswith("logo:"):
        _, sid=data.split(":"); site=site_from(uid,sid)
        if not site:return await q.answer("عدم دسترسی",show_alert=True)
        await q.answer(); x=(await core.api(site,"settings_get"))["data"]
        kb=InlineKeyboardMarkup([[InlineKeyboardButton("📤 گذاشتن/تعویض لوگو",callback_data=f"logo_set:{sid}")],[InlineKeyboardButton("🗑 حذف لوگو",callback_data=f"logo_remove:{sid}")],[InlineKeyboardButton("⬅️ تنظیمات",callback_data=f"settings:{sid}")]])
        return await q.edit_message_text(f"🖼 لوگوی سایت\nوضعیت: {'✅ لوگو ثبت شده' if x.get('has_logo') else '❌ لوگویی ثبت نشده'}",reply_markup=kb)

    if data.startswith("logo_set:"):
        _,sid=data.split(":"); site=site_from(uid,sid)
        if not site:return await q.answer("عدم دسترسی",show_alert=True)
        await q.answer();context.user_data.clear();context.user_data.update(flow="v4_logo",site_id=int(sid))
        return await q.edit_message_text("لوگوی سایت را به صورت عکس یا فایل تصویر بفرستید.\nپیشنهاد: PNG با پس‌زمینه شفاف و حداقل 512×512.")

    if data.startswith("logo_remove:"):
        _,sid=data.split(":");site=site_from(uid,sid)
        if not site:return await q.answer("عدم دسترسی",show_alert=True)
        await q.answer();await core.api(site,"logo_remove")
        return await q.edit_message_text("✅ لوگوی سایت حذف شد.",reply_markup=_back_site(sid))

    for prefix,flow,prompt in [
        ("v4_name:","v4_name","نام جدید سایت را بفرستید:"),
        ("v4_announcement:","v4_announcement","متن اعلان بالای سایت را بفرستید:"),
        ("v4_shipping:","v4_shipping","هزینه ارسال را به تومان بفرستید؛ مثال 90,000:"),
        ("v4_free:","v4_free","حد ارسال رایگان را به تومان بفرستید:"),
        ("v4_card:","v4_card","شماره کارت و نام صاحب کارت را با | جدا کنید.\nمثال: 6037... | نام صاحب کارت"),
    ]:
        if data.startswith(prefix):
            sid=data.split(":")[1];site=site_from(uid,sid)
            if not site:return await q.answer("عدم دسترسی",show_alert=True)
            await q.answer();context.user_data.clear();context.user_data.update(flow=flow,site_id=int(sid));return await q.edit_message_text(prompt)

    # Delta footer.
    if data.startswith("footer:"):
        _,sid=data.split(":");site=site_from(uid,sid)
        if not site:return await q.answer("عدم دسترسی",show_alert=True)
        await q.answer();x=(await core.api(site,"settings_get"))["data"]
        text=f"🦶 فوتر سایت\n\n📍 آدرس: {x.get('address') or '-'}\n☎️ تلفن: {x.get('phone') or '-'}\n✉️ ایمیل: {x.get('contact_email') or '-'}\n📝 توضیح: {x.get('footer_description') or '-'}\n🛡 اینماد: {'✅' if x.get('has_enamad_image') else '❌'}"
        kb=InlineKeyboardMarkup([
            [InlineKeyboardButton("📍 آدرس",callback_data=f"footer_address:{sid}"),InlineKeyboardButton("☎️ تلفن",callback_data=f"footer_phone:{sid}")],
            [InlineKeyboardButton("✉️ ایمیل",callback_data=f"footer_email:{sid}"),InlineKeyboardButton("📝 توضیح فوتر",callback_data=f"footer_desc:{sid}")],
            [InlineKeyboardButton("🔗 شبکه‌های اجتماعی",callback_data=f"socials:{sid}"),InlineKeyboardButton("🛡 عکس اینماد",callback_data=f"enamad:{sid}")],
            [InlineKeyboardButton("⬅️ پنل سایت",callback_data=f"site_info:{sid}")],
        ])
        return await q.edit_message_text(text,reply_markup=kb)

    footer_prompts={"footer_address":"آدرس کامل را بفرستید:","footer_phone":"شماره تماس را بفرستید:","footer_email":"ایمیل فوتر را بفرستید:","footer_desc":"توضیح کوتاه فوتر را بفرستید؛ برای خالی - بفرستید:"}
    for prefix,prompt in footer_prompts.items():
        if data.startswith(prefix+":"):
            sid=data.split(":")[1];site=site_from(uid,sid)
            if not site:return await q.answer("عدم دسترسی",show_alert=True)
            await q.answer();context.user_data.clear();context.user_data.update(flow=prefix,site_id=int(sid));return await q.edit_message_text(prompt)

    if data.startswith("enamad:"):
        _,sid=data.split(":");site=site_from(uid,sid)
        if not site:return await q.answer("عدم دسترسی",show_alert=True)
        await q.answer();x=(await core.api(site,"settings_get"))["data"]
        kb=InlineKeyboardMarkup([[InlineKeyboardButton("📤 گذاشتن/تعویض عکس اینماد",callback_data=f"enamad_set:{sid}")],[InlineKeyboardButton("🗑 حذف عکس اینماد",callback_data=f"enamad_remove:{sid}")],[InlineKeyboardButton("⬅️ فوتر",callback_data=f"footer:{sid}")]])
        return await q.edit_message_text(f"🛡 نماد اعتماد\nوضعیت: {'✅ ثبت شده' if x.get('has_enamad_image') else '❌ ثبت نشده'}",reply_markup=kb)

    if data.startswith("enamad_set:"):
        _,sid=data.split(":");site=site_from(uid,sid)
        if not site:return await q.answer("عدم دسترسی",show_alert=True)
        await q.answer();context.user_data.clear();context.user_data.update(flow="v4_enamad",site_id=int(sid));return await q.edit_message_text("عکس اینماد را ارسال کنید:")

    if data.startswith("enamad_remove:"):
        _,sid=data.split(":");site=site_from(uid,sid)
        if not site:return await q.answer("عدم دسترسی",show_alert=True)
        await q.answer();await core.api(site,"enamad_remove");return await q.edit_message_text("✅ عکس اینماد حذف شد.",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ فوتر",callback_data=f"footer:{sid}")]]))

    # Social links: platform icons are rendered by site; no icon upload needed.
    if data.startswith("socials:"):
        _,sid=data.split(":");site=site_from(uid,sid)
        if not site:return await q.answer("عدم دسترسی",show_alert=True)
        await q.answer();rows=(await core.api(site,"socials"))["data"]
        keys=[]
        for item in rows[:30]:
            keys.append([InlineKeyboardButton(f"{'✅' if item['is_active'] else '⛔️'} {item.get('platform_label') or item['title']}",callback_data=f"social_v4:{sid}:{item['id']}" )])
        keys += [[InlineKeyboardButton("➕ افزودن شبکه اجتماعی",callback_data=f"social_add_v4:{sid}")],[InlineKeyboardButton("⬅️ فوتر",callback_data=f"footer:{sid}")]]
        return await q.edit_message_text("🔗 شبکه‌های اجتماعی فوتر\nلوگوی هر شبکه به صورت خودکار مثل Delta Janebi نمایش داده می‌شود.",reply_markup=InlineKeyboardMarkup(keys))

    if data.startswith("social_add_v4:"):
        _,sid=data.split(":");site=site_from(uid,sid)
        if not site:return await q.answer("عدم دسترسی",show_alert=True)
        await q.answer();keys=[[InlineKeyboardButton(label,callback_data=f"social_platform_v4:{sid}:{value}")] for value,label in PLATFORMS];keys.append([InlineKeyboardButton("⬅️ برگشت",callback_data=f"socials:{sid}")])
        return await q.edit_message_text("نوع شبکه اجتماعی را انتخاب کنید:",reply_markup=InlineKeyboardMarkup(keys))

    if data.startswith("social_platform_v4:"):
        _,_,sid,platform=data.split(":",3);site=site_from(uid,sid)
        if not site:return await q.answer("عدم دسترسی",show_alert=True)
        await q.answer();context.user_data.clear();context.user_data.update(flow="v4_social_url",site_id=int(sid),platform=platform)
        return await q.edit_message_text(f"لینک کامل {PLATFORM_LABELS.get(platform,'شبکه اجتماعی')} را بفرستید:")

    if data.startswith("social_v4:"):
        _,sid,social_id=data.split(":");site=site_from(uid,sid)
        if not site:return await q.answer("عدم دسترسی",show_alert=True)
        await q.answer();item=(await core.api(site,"social_detail",{"id":int(social_id)}))["data"]
        kb=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 فعال/غیرفعال",callback_data=f"social_toggle_v4:{sid}:{social_id}"),InlineKeyboardButton("🗑 حذف",callback_data=f"social_delete_v4:{sid}:{social_id}")],[InlineKeyboardButton("⬅️ شبکه‌ها",callback_data=f"socials:{sid}")]])
        return await q.edit_message_text(f"🔗 {item.get('platform_label') or item['title']}\n{item['url']}\nوضعیت: {'فعال' if item['is_active'] else 'غیرفعال'}",reply_markup=kb)

    if data.startswith("social_toggle_v4:"):
        _,_,sid,social_id=data.split(":");site=site_from(uid,sid)
        if not site:return await q.answer("عدم دسترسی",show_alert=True)
        await q.answer();item=(await core.api(site,"social_detail",{"id":int(social_id)}))["data"];await core.api(site,"social_update",{"id":int(social_id),"is_active":not item["is_active"]})
        return await q.edit_message_text("✅ وضعیت تغییر کرد.",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ شبکه‌ها",callback_data=f"socials:{sid}")]]))

    if data.startswith("social_delete_v4:"):
        _,_,sid,social_id=data.split(":");site=site_from(uid,sid)
        if not site:return await q.answer("عدم دسترسی",show_alert=True)
        await q.answer();await core.api(site,"social_delete",{"id":int(social_id)})
        return await q.edit_message_text("✅ شبکه اجتماعی حذف شد.",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ شبکه‌ها",callback_data=f"socials:{sid}")]]))

    # Dual desktop/mobile banners.
    if data.startswith("banners:"):
        _,sid=data.split(":");site=site_from(uid,sid)
        if not site:return await q.answer("عدم دسترسی",show_alert=True)
        await q.answer();rows=(await core.api(site,"banners"))["data"]
        keys=[[InlineKeyboardButton(f"{'✅' if x['is_active'] else '⛔️'} {x['title'] or ('بنر #'+str(x['id']))}",callback_data=f"banner_v4:{sid}:{x['id']}")] for x in rows[:30]]
        keys += [[InlineKeyboardButton("➕ بنر جدید",callback_data=f"banner_add_v4:{sid}")],[InlineKeyboardButton("⬅️ پنل سایت",callback_data=f"site_info:{sid}")]]
        return await q.edit_message_text("🎞 بنرهای صفحه اول\n📱 موبایل: 1080×420\n🖥 دسکتاپ: 1800×300",reply_markup=InlineKeyboardMarkup(keys))

    if data.startswith("banner_add_v4:"):
        _,sid=data.split(":");site=site_from(uid,sid)
        if not site:return await q.answer("عدم دسترسی",show_alert=True)
        await q.answer();context.user_data.clear();context.user_data.update(flow="v4_banner_mobile",site_id=int(sid))
        return await q.edit_message_text("📱 اول عکس موبایل/اندروید را بفرستید.\nابعاد پیشنهادی دقیق: 1080×420 پیکسل (نسبت 18:7).")

    if data.startswith("banner_v4:"):
        _,sid,bid=data.split(":");site=site_from(uid,sid)
        if not site:return await q.answer("عدم دسترسی",show_alert=True)
        await q.answer();item=(await core.api(site,"banner_detail",{"id":int(bid)}))["data"]
        kb=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 فعال/غیرفعال",callback_data=f"banner_toggle_v4:{sid}:{bid}"),InlineKeyboardButton("🗑 حذف",callback_data=f"banner_delete_v4:{sid}:{bid}")],[InlineKeyboardButton("⬅️ بنرها",callback_data=f"banners:{sid}")]])
        return await q.edit_message_text(f"🎞 {item['title'] or ('بنر #'+bid)}\n📱 موبایل: {'✅' if item.get('has_mobile_image') else '❌'}\n🖥 دسکتاپ: {'✅' if item.get('has_desktop_image') else '❌'}\nلینک: {item.get('link') or '-'}\nوضعیت: {'فعال' if item['is_active'] else 'غیرفعال'}",reply_markup=kb)

    if data.startswith("banner_toggle_v4:"):
        _,_,sid,bid=data.split(":");site=site_from(uid,sid)
        if not site:return await q.answer("عدم دسترسی",show_alert=True)
        await q.answer();item=(await core.api(site,"banner_detail",{"id":int(bid)}))["data"];await core.api(site,"banner_update",{"id":int(bid),"is_active":not item["is_active"]})
        return await q.edit_message_text("✅ وضعیت بنر تغییر کرد.",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ بنرها",callback_data=f"banners:{sid}")]]))

    if data.startswith("banner_delete_v4:"):
        _,_,sid,bid=data.split(":");site=site_from(uid,sid)
        if not site:return await q.answer("عدم دسترسی",show_alert=True)
        await q.answer();await core.api(site,"banner_delete",{"id":int(bid)})
        return await q.edit_message_text("✅ بنر حذف شد.",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ بنرها",callback_data=f"banners:{sid}")]]))

    # Timed product stories.
    if data.startswith("stories:"):
        _,sid=data.split(":");site=site_from(uid,sid)
        if not site:return await q.answer("عدم دسترسی",show_alert=True)
        await q.answer();rows=(await core.api(site,"stories"))["data"]
        keys=[]
        for item in rows[:30]:
            remaining=int(item.get("remaining_seconds") or 0);status="🔴" if item.get("active_now") else "⚫️"
            keys.append([InlineKeyboardButton(f"{status} {item['title']} | {remaining//3600}h",callback_data=f"story_v4:{sid}:{item['id']}")])
        keys += [[InlineKeyboardButton("➕ معرفی محصول جدید",callback_data=f"story_add_v4:{sid}")],[InlineKeyboardButton("⬅️ پنل سایت",callback_data=f"site_info:{sid}")]]
        return await q.edit_message_text("🔴 معرفی محصولات / استوری‌ها\nاستوری منقضی‌شده خودکار از سایت ناپدید می‌شود.",reply_markup=InlineKeyboardMarkup(keys))

    if data.startswith("story_add_v4:"):
        _,sid=data.split(":");site=site_from(uid,sid)
        if not site:return await q.answer("عدم دسترسی",show_alert=True)
        await q.answer();context.user_data.clear();context.user_data.update(flow="v4_story_title",site_id=int(sid))
        return await q.edit_message_text("عنوان معرفی محصول را بنویسید.\nمثال: گردنبند طرح پروانه")

    if data.startswith("story_v4:"):
        _,sid,story_id=data.split(":");site=site_from(uid,sid)
        if not site:return await q.answer("عدم دسترسی",show_alert=True)
        await q.answer();item=(await core.api(site,"story_detail",{"id":int(story_id)}))["data"];remaining=int(item.get("remaining_seconds") or 0)
        kb=InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ عنوان",callback_data=f"story_title_v4:{sid}:{story_id}"),InlineKeyboardButton("🔗 لینک خرید",callback_data=f"story_link_v4:{sid}:{story_id}")],
            [InlineKeyboardButton("🖼 تعویض عکس/ویدئو",callback_data=f"story_media_v4:{sid}:{story_id}"),InlineKeyboardButton("⏳ تمدید زمان",callback_data=f"story_time_v4:{sid}:{story_id}")],
            [InlineKeyboardButton("🔄 فعال/غیرفعال",callback_data=f"story_toggle_v4:{sid}:{story_id}"),InlineKeyboardButton("🗑 حذف",callback_data=f"story_delete_v4:{sid}:{story_id}")],
            [InlineKeyboardButton("⬅️ استوری‌ها",callback_data=f"stories:{sid}")],
        ])
        return await q.edit_message_text(f"🔴 {item['title']}\nنوع: {'ویدئو' if item['media_type']=='video' else 'عکس'}\nلینک: {item['target_url']}\nوضعیت: {'فعال' if item['active_now'] else 'منقضی/غیرفعال'}\nزمان باقی‌مانده: {remaining//3600} ساعت و {(remaining%3600)//60} دقیقه",reply_markup=kb)

    for prefix,flow,prompt in [
        ("story_title_v4:","v4_story_edit_title","عنوان جدید را بفرستید:"),
        ("story_link_v4:","v4_story_edit_link","لینک جدید خرید را بفرستید؛ لینک کامل یا مسیر مثل /product/...:"),
        ("story_time_v4:","v4_story_edit_time","چند ساعت از الان فعال باشد؟ فقط عدد؛ مثال 24:"),
        ("story_media_v4:","v4_story_edit_media","عکس یا ویدئوی جدید را بفرستید:"),
    ]:
        if data.startswith(prefix):
            _,sid,story_id=data.split(":");site=site_from(uid,sid)
            if not site:return await q.answer("عدم دسترسی",show_alert=True)
            await q.answer();context.user_data.clear();context.user_data.update(flow=flow,site_id=int(sid),story_id=int(story_id));return await q.edit_message_text(prompt)

    if data.startswith("story_toggle_v4:"):
        _,_,sid,story_id=data.split(":");site=site_from(uid,sid)
        if not site:return await q.answer("عدم دسترسی",show_alert=True)
        await q.answer();item=(await core.api(site,"story_detail",{"id":int(story_id)}))["data"];await core.api(site,"story_update",{"id":int(story_id),"is_active":not item["is_active"]})
        return await q.edit_message_text("✅ وضعیت معرفی محصول تغییر کرد.",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ استوری‌ها",callback_data=f"stories:{sid}")]]))

    if data.startswith("story_delete_v4:"):
        _,_,sid,story_id=data.split(":");site=site_from(uid,sid)
        if not site:return await q.answer("عدم دسترسی",show_alert=True)
        await q.answer();await core.api(site,"story_delete",{"id":int(story_id)})
        return await q.edit_message_text("✅ معرفی محصول حذف شد.",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ استوری‌ها",callback_data=f"stories:{sid}")]]))

    return await ORIGINAL_CALLBACK(update, context)


async def message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid=update.effective_user.id;flow=context.user_data.get("flow");text=(update.message.text or "").strip()
    site_id=context.user_data.get("site_id")
    if flow and str(flow).startswith("v4_"):
        if not site_id or not core.can_access(uid,int(site_id)):
            context.user_data.clear();return await update.message.reply_text("⛔️ دسترسی شما به این سایت لغو شده است.")
        site=core.get_site(int(site_id));sid=site["id"]
        try:
            if flow=="v4_name":
                await core.api(site,"settings_update",{"site_name":text});context.user_data.clear();return await update.message.reply_text("✅ نام سایت ذخیره شد.",reply_markup=enhanced_site_panel(site,uid))
            if flow=="v4_announcement":
                await core.api(site,"settings_update",{"announcement":text});context.user_data.clear();return await update.message.reply_text("✅ اعلان ذخیره شد.",reply_markup=enhanced_site_panel(site,uid))
            if flow in ("v4_shipping","v4_free"):
                raw=text.replace(",","").replace("٬","")
                if not raw.isdigit():return await update.message.reply_text("فقط عدد بفرستید.")
                field="shipping_fee" if flow=="v4_shipping" else "free_shipping_threshold";await core.api(site,"settings_update",{field:int(raw)});context.user_data.clear();return await update.message.reply_text("✅ ذخیره شد.",reply_markup=enhanced_site_panel(site,uid))
            if flow=="v4_card":
                if "|" not in text:return await update.message.reply_text("شماره کارت و نام صاحب کارت را با | جدا کنید.")
                card,owner=[x.strip() for x in text.split("|",1)];await core.api(site,"settings_update",{"card_number":card,"card_owner":owner});context.user_data.clear();return await update.message.reply_text("✅ اطلاعات کارت ذخیره شد.",reply_markup=enhanced_site_panel(site,uid))
            if flow in ("footer_address","footer_phone","footer_email","footer_desc"):
                field={"footer_address":"address","footer_phone":"phone","footer_email":"contact_email","footer_desc":"footer_description"}[flow]
                value="" if text=="-" else text
                await core.api(site,"settings_update",{field:value});context.user_data.clear();return await update.message.reply_text("✅ فوتر ذخیره شد.",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ فوتر",callback_data=f"footer:{sid}")]]))
            if flow=="v4_social_url":
                if not valid_link(text,False):return await update.message.reply_text("لینک باید کامل و با http:// یا https:// باشد.")
                platform=context.user_data["platform"];await core.api(site,"social_create",{"platform":platform,"title":PLATFORM_LABELS.get(platform,"شبکه اجتماعی"),"url":text});context.user_data.clear();return await update.message.reply_text("✅ شبکه اجتماعی اضافه شد. لوگو به‌صورت خودکار روی سایت نمایش داده می‌شود.",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ شبکه‌ها",callback_data=f"socials:{sid}")]]))
            if flow=="v4_banner_link":
                link="/products/" if text in ("","-") else text
                if not valid_link(link,True):return await update.message.reply_text("لینک معتبر بفرستید؛ مثل /products/ یا https://...")
                payload={"title":"","subtitle":"","link":link,"mobile_image_b64":context.user_data["mobile_b64"],"mobile_image_filename":context.user_data["mobile_filename"],"desktop_image_b64":context.user_data["desktop_b64"],"desktop_image_filename":context.user_data["desktop_filename"]}
                await core.api(site,"banner_create",payload,timeout=60);context.user_data.clear();return await update.message.reply_text("✅ بنر موبایل و دسکتاپ ساخته شد.",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ بنرها",callback_data=f"banners:{sid}")]]))
            if flow=="v4_story_title":
                if not text:return await update.message.reply_text("عنوان را بفرستید.")
                context.user_data["story_title"]=text[:160];context.user_data["flow"]="v4_story_media";return await update.message.reply_text("حالا عکس یا فیلم محصول را بفرستید.\nبرای ویدئو حداکثر 48 مگابایت.")
            if flow=="v4_story_link":
                if not valid_link(text,True):return await update.message.reply_text("لینک معتبر بفرستید؛ لینک کامل یا مسیر /product/... قابل قبول است.")
                context.user_data["story_link"]=text;context.user_data["flow"]="v4_story_hours";return await update.message.reply_text("چند ساعت فعال باشد؟ فقط عدد بفرستید.\nمثال: 24")
            if flow=="v4_story_hours":
                raw=text.replace(" ","");
                if not raw.isdigit() or int(raw)<=0:return await update.message.reply_text("فقط تعداد ساعت را به صورت عدد مثبت بفرستید؛ مثال 24")
                payload={"title":context.user_data["story_title"],"media_type":context.user_data["story_media_type"],"media_b64":context.user_data["story_media_b64"],"media_filename":context.user_data["story_media_filename"],"target_url":context.user_data["story_link"],"duration_hours":int(raw)}
                await core.api(site,"story_create",payload,timeout=90);context.user_data.clear();return await update.message.reply_text("✅ معرفی محصول ساخته شد و بالای اسلایدر سایت نمایش داده می‌شود.",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔴 مشاهده استوری‌ها",callback_data=f"stories:{sid}")]]))
            if flow=="v4_story_edit_title":
                await core.api(site,"story_update",{"id":context.user_data["story_id"],"title":text});story_id=context.user_data["story_id"];context.user_data.clear();return await update.message.reply_text("✅ عنوان تغییر کرد.",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ استوری",callback_data=f"story_v4:{sid}:{story_id}")]]))
            if flow=="v4_story_edit_link":
                if not valid_link(text,True):return await update.message.reply_text("لینک معتبر بفرستید.")
                story_id=context.user_data["story_id"];await core.api(site,"story_update",{"id":story_id,"target_url":text});context.user_data.clear();return await update.message.reply_text("✅ لینک خرید تغییر کرد.",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ استوری",callback_data=f"story_v4:{sid}:{story_id}")]]))
            if flow=="v4_story_edit_time":
                if not text.isdigit() or int(text)<=0:return await update.message.reply_text("فقط تعداد ساعت را عددی بفرستید.")
                story_id=context.user_data["story_id"];await core.api(site,"story_update",{"id":story_id,"duration_hours":int(text)});context.user_data.clear();return await update.message.reply_text("✅ زمان استوری از همین لحظه تمدید شد.",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ استوری",callback_data=f"story_v4:{sid}:{story_id}")]]))
        except Exception as exc:
            return await update.message.reply_text(f"❌ عملیات ناموفق بود:\n{exc}")

    if flow=="prod_old_price":
        if not site_id or not core.can_access(uid,int(site_id)):
            context.user_data.clear();return await update.message.reply_text("⛔️ دسترسی شما به این سایت لغو شده است.")
        raw=text.replace(",","")
        if not raw.isdigit():return await update.message.reply_text("فقط عدد بفرستید؛ مثال 2,900,000")
        site=core.get_site(int(site_id));pid=context.user_data["product_id"];await core.api(site,"product_update",{"id":pid,"compare_at_price":int(raw)});context.user_data.clear();return await update.message.reply_text("✅ قیمت قبلی ذخیره شد.",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ محصول",callback_data=f"product:{site['id']}:{pid}")]]))
    return await ORIGINAL_MESSAGE(update,context)


async def media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid=update.effective_user.id;flow=context.user_data.get("flow");site_id=context.user_data.get("site_id")
    our_flows={"cat_photo","v4_logo","v4_enamad","v4_banner_mobile","v4_banner_desktop","v4_story_media","v4_story_edit_media"}
    if flow not in our_flows:
        if update.message.photo:return await ORIGINAL_PHOTO(update,context)
        return
    if not site_id or not core.can_access(uid,int(site_id)):
        context.user_data.clear();return await update.message.reply_text("⛔️ دسترسی شما به این سایت لغو شده است.")
    site=core.get_site(int(site_id));sid=site["id"]
    try:
        max_bytes=MAX_STORY_BYTES if flow in ("v4_story_media","v4_story_edit_media") else MAX_IMAGE_BYTES
        media_type,filename,encoded=await _download_media(update.message,max_bytes=max_bytes)
        if flow in ("cat_photo","v4_logo","v4_enamad","v4_banner_mobile","v4_banner_desktop") and media_type!="image":
            return await update.message.reply_text("برای این بخش فقط عکس ارسال کنید.")
        if flow=="cat_photo":
            cid=context.user_data["category_id"];await core.api(site,"category_image_set",{"id":cid,"image_b64":encoded,"filename":filename},timeout=60);context.user_data.clear();return await update.message.reply_text("✅ عکس دسته ذخیره شد.",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ دسته",callback_data=f"category:{sid}:{cid}")]]))
        if flow=="v4_logo":
            await core.api(site,"logo_set",{"image_b64":encoded,"image_filename":filename},timeout=60);context.user_data.clear();return await update.message.reply_text("✅ لوگوی سایت ذخیره شد.",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ تنظیمات",callback_data=f"settings:{sid}")]]))
        if flow=="v4_enamad":
            await core.api(site,"enamad_set",{"image_b64":encoded,"image_filename":filename},timeout=60);context.user_data.clear();return await update.message.reply_text("✅ عکس اینماد ذخیره شد.",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ فوتر",callback_data=f"footer:{sid}")]]))
        if flow=="v4_banner_mobile":
            context.user_data["mobile_b64"]=encoded;context.user_data["mobile_filename"]=filename;context.user_data["flow"]="v4_banner_desktop"
            return await update.message.reply_text("✅ عکس موبایل دریافت شد.\n\n🖥 حالا عکس ویندوز/دسکتاپ را بفرستید.\nابعاد پیشنهادی دقیق: 1800×300 پیکسل (نسبت 6:1).")
        if flow=="v4_banner_desktop":
            context.user_data["desktop_b64"]=encoded;context.user_data["desktop_filename"]=filename;context.user_data["flow"]="v4_banner_link"
            return await update.message.reply_text("✅ عکس دسکتاپ دریافت شد.\nحالا لینک مقصد بنر را بفرستید.\nبرای لینک پیش‌فرض محصولات فقط - بفرستید.")
        if flow=="v4_story_media":
            context.user_data["story_media_type"]=media_type;context.user_data["story_media_filename"]=filename;context.user_data["story_media_b64"]=encoded;context.user_data["flow"]="v4_story_link"
            return await update.message.reply_text("✅ رسانه دریافت شد.\nحالا لینک مخصوص خرید این محصول را بفرستید؛ مثال: /product/گردنبند-پروانه/")
        if flow=="v4_story_edit_media":
            story_id=context.user_data["story_id"];await core.api(site,"story_media_set",{"id":story_id,"media_type":media_type,"media_b64":encoded,"media_filename":filename},timeout=90);context.user_data.clear();return await update.message.reply_text("✅ عکس/ویدئوی استوری تغییر کرد.",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ استوری",callback_data=f"story_v4:{sid}:{story_id}")]]))
    except Exception as exc:
        return await update.message.reply_text(f"❌ آپلود ناموفق بود:\n{exc}")


async def post_init(application):
    application.create_task(notification_loop(application),name="sanashop-site-events")


def run():
    core.db()
    app=Application.builder().token(core.TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start",core.start))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.Document.ALL,media))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,message))
    app.run_polling(drop_pending_updates=True)


if __name__=="__main__":
    run()
