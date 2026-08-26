#!/usr/bin/env python3
import base64
import logging
import os
import sqlite3
from pathlib import Path

import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

DB_PATH = Path(os.environ.get("BOT_DB_PATH", "/var/lib/sanashop-bot/bot.sqlite3"))
OWNER_ID = int(os.environ["TELEGRAM_OWNER_ID"])
TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]


def db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS admins(
            telegram_id INTEGER PRIMARY KEY,
            added_by INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sites(
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            base_url TEXT NOT NULL UNIQUE,
            api_key TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS site_admins(
            site_id INTEGER NOT NULL,
            telegram_id INTEGER NOT NULL UNIQUE,
            UNIQUE(site_id, telegram_id)
        );
        """
    )
    conn.commit()
    return conn


def is_owner(uid):
    return uid == OWNER_ID


def assigned_site(uid):
    if is_owner(uid):
        return None
    with db() as c:
        return c.execute(
            """
            SELECT s.* FROM sites s
            JOIN site_admins a ON a.site_id=s.id
            WHERE a.telegram_id=?
            LIMIT 1
            """,
            (uid,),
        ).fetchone()


def is_authorized(uid):
    return is_owner(uid) or assigned_site(uid) is not None


def get_site(site_id):
    with db() as c:
        return c.execute("SELECT * FROM sites WHERE id=?", (site_id,)).fetchone()


def can_access(uid, site_id):
    if is_owner(uid):
        return get_site(site_id) is not None
    s = assigned_site(uid)
    return bool(s and s["id"] == site_id)


async def api(site, action, payload=None, timeout=25):
    url = site["base_url"].rstrip("/") + "/api/bot/v1/"
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {site['api_key']}"},
                json={"action": action, "payload": payload or {}},
            )
    except httpx.ConnectTimeout as exc:
        raise RuntimeError("زمان اتصال به سایت تمام شد؛ پورت 443/DNS/فایروال سایت را بررسی کنید.") from exc
    except httpx.ConnectError as exc:
        raise RuntimeError("سرور ربات نتوانست به سایت وصل شود؛ DNS یا دسترسی شبکه را بررسی کنید.") from exc
    except httpx.TimeoutException as exc:
        raise RuntimeError("سایت در زمان مناسب پاسخ نداد.") from exc
    if response.status_code == 401:
        raise RuntimeError("کلید اتصال سایت اشتباه است.")
    if response.status_code == 403:
        raise RuntimeError("IP این سرور ربات در سایت مجاز نشده است.")
    if response.status_code == 404:
        raise RuntimeError("API مدیریت روی سایت پیدا نشد؛ نسخه سایت را بررسی کنید.")
    try:
        data = response.json()
    except Exception as exc:
        raise RuntimeError(f"پاسخ نامعتبر از سایت (HTTP {response.status_code}).") from exc
    if response.status_code >= 400 or not data.get("ok", False):
        raise RuntimeError(data.get("error") or f"HTTP {response.status_code}")
    return data


def owner_home():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔗 اتصال سایت", callback_data="connect")],
            [InlineKeyboardButton("🏪 سایت‌های متصل شده", callback_data="owner_sites")],
            [InlineKeyboardButton("👤 مدیران", callback_data="admins")],
        ]
    )


def site_panel(site, uid):
    sid = site["id"]
    rows = [
        [InlineKeyboardButton(f"🏪 {site['name']}", callback_data=f"site_info:{sid}")],
        [
            InlineKeyboardButton("📊 داشبورد", callback_data=f"dash:{sid}"),
            InlineKeyboardButton("🛍 محصولات", callback_data=f"products:{sid}"),
        ],
        [
            InlineKeyboardButton("🗂 دسته‌ها", callback_data=f"categories:{sid}"),
            InlineKeyboardButton("🛒 سفارش‌ها", callback_data=f"orders:{sid}"),
        ],
        [
            InlineKeyboardButton("🧾 رسیدها", callback_data=f"receipts:{sid}"),
            InlineKeyboardButton("👥 کاربران", callback_data=f"users:{sid}"),
        ],
        [
            InlineKeyboardButton("🎞 بنرها", callback_data=f"banners:{sid}"),
            InlineKeyboardButton("📄 صفحات", callback_data=f"pages:{sid}"),
        ],
        [
            InlineKeyboardButton("🔗 شبکه‌های اجتماعی", callback_data=f"socials:{sid}"),
            InlineKeyboardButton("🎟 کد تخفیف", callback_data=f"discounts:{sid}"),
        ],
        [InlineKeyboardButton("⚙️ تنظیمات فروشگاه", callback_data=f"settings:{sid}")],
    ]
    if is_owner(uid):
        rows.append([InlineKeyboardButton("⬅️ سایت‌های متصل", callback_data="owner_sites")])
    return InlineKeyboardMarkup(rows)


async def show_site(update_or_query, site, uid, edit=False):
    text = f"💎 پنل مدیریت\n🏪 سایت: {site['name']}\n🌐 {site['base_url']}"
    if edit:
        await update_or_query.edit_message_text(text, reply_markup=site_panel(site, uid))
    else:
        await update_or_query.reply_text(text, reply_markup=site_panel(site, uid))


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    context.user_data.clear()
    if is_owner(uid):
        return await update.message.reply_text(
            "👑 پنل مالک\nاز منوی زیر انتخاب کنید:",
            reply_markup=owner_home(),
        )
    site = assigned_site(uid)
    if not site:
        return await update.message.reply_text("⛔️ شما مجاز به استفاده از ربات نمی‌باشید.")
    await show_site(update.message, site, uid)


def _site_from_callback(uid, data):
    try:
        parts = data.split(":")
        site_id = int(parts[1])
    except Exception:
        return None
    if not can_access(uid, site_id):
        return None
    return get_site(site_id)


async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    data = q.data or ""

    if not is_authorized(uid):
        return await q.answer("شما مجاز به استفاده از ربات نمی‌باشید.", show_alert=True)
    await q.answer()

    if data == "owner_home":
        if not is_owner(uid):
            return
        context.user_data.clear()
        return await q.edit_message_text("👑 پنل مالک", reply_markup=owner_home())

    if data == "connect":
        if not is_owner(uid):
            return await q.edit_message_text("⛔️ فقط مالک اصلی می‌تواند سایت اضافه کند.")
        context.user_data.clear()
        context.user_data["flow"] = "connect_url"
        return await q.edit_message_text(
            "🌐 آدرس کامل سایت را بفرستید.\nمثال:\nhttps://shop.example.com"
        )

    if data == "owner_sites":
        if not is_owner(uid):
            return
        with db() as c:
            sites = c.execute("SELECT * FROM sites ORDER BY id").fetchall()
        if not sites:
            return await q.edit_message_text(
                "هنوز سایتی متصل نشده است.",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [InlineKeyboardButton("🔗 اتصال سایت", callback_data="connect")],
                        [InlineKeyboardButton("⬅️ بازگشت", callback_data="owner_home")],
                    ]
                ),
            )
        keys = [
            [InlineKeyboardButton(f"🏪 {s['name']}", callback_data=f"open_site:{s['id']}")]
            for s in sites
        ]
        keys.append([InlineKeyboardButton("⬅️ بازگشت", callback_data="owner_home")])
        return await q.edit_message_text("🏪 سایت‌های متصل شده:", reply_markup=InlineKeyboardMarkup(keys))

    if data.startswith("open_site:"):
        if not is_owner(uid):
            return
        try:
            site = get_site(int(data.split(":")[1]))
        except Exception:
            site = None
        if not site:
            return await q.edit_message_text("سایت پیدا نشد.", reply_markup=owner_home())
        return await show_site(q, site, uid, edit=True)

    if data == "admins":
        if not is_owner(uid):
            return
        with db() as c:
            rows = c.execute(
                """
                SELECT a.telegram_id, s.name
                FROM admins a
                LEFT JOIN site_admins sa ON sa.telegram_id=a.telegram_id
                LEFT JOIN sites s ON s.id=sa.site_id
                ORDER BY a.telegram_id
                """
            ).fetchall()
        lines = [f"👤 {r['telegram_id']} → {r['name'] or 'بدون دسترسی'}" for r in rows]
        text = "👤 مدیران:\n" + ("\n".join(lines) if lines else "هنوز مدیری اضافه نشده است.")
        kb = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("➕ افزودن / تغییر دسترسی مدیر", callback_data="admin_add")],
                [InlineKeyboardButton("➖ حذف مدیر", callback_data="admin_del")],
                [InlineKeyboardButton("⬅️ بازگشت", callback_data="owner_home")],
            ]
        )
        return await q.edit_message_text(text, reply_markup=kb)

    if data == "admin_add":
        if not is_owner(uid):
            return
        context.user_data.clear()
        context.user_data["flow"] = "admin_add_id"
        return await q.edit_message_text("آیدی عددی تلگرام مدیر را بفرستید:")

    if data == "admin_del":
        if not is_owner(uid):
            return
        context.user_data.clear()
        context.user_data["flow"] = "admin_del"
        return await q.edit_message_text("آیدی عددی مدیری که باید حذف شود را بفرستید:")

    if data.startswith("admin_grant:"):
        if not is_owner(uid):
            return
        admin_id = context.user_data.get("pending_admin_id")
        if not admin_id:
            return await q.edit_message_text("درخواست منقضی شده است.", reply_markup=owner_home())
        site_id = int(data.split(":")[1])
        site = get_site(site_id)
        if not site:
            return await q.edit_message_text("سایت پیدا نشد.", reply_markup=owner_home())
        with db() as c:
            c.execute(
                "INSERT OR IGNORE INTO admins(telegram_id, added_by) VALUES(?,?)",
                (admin_id, uid),
            )
            c.execute("DELETE FROM site_admins WHERE telegram_id=?", (admin_id,))
            c.execute(
                "INSERT INTO site_admins(site_id, telegram_id) VALUES(?,?)",
                (site_id, admin_id),
            )
            c.commit()
        context.user_data.clear()
        return await q.edit_message_text(
            f"✅ مدیر {admin_id} فقط به سایت «{site['name']}» دسترسی دارد.",
            reply_markup=owner_home(),
        )

    site = _site_from_callback(uid, data)
    if not site:
        return await q.answer("به این سایت دسترسی ندارید.", show_alert=True)

    sid = site["id"]

    if data.startswith("site_info:"):
        try:
            info = await api(site, "ping")
            s = info["site"]
            text = f"🏪 {s['name']}\n🌐 {s.get('domain') or site['base_url']}\n✅ اتصال API برقرار است."
        except Exception as exc:
            text = f"❌ اتصال سایت مشکل دارد:\n{exc}"
        return await q.edit_message_text(text, reply_markup=site_panel(site, uid))

    try:
        if data.startswith("dash:"):
            x = (await api(site, "dashboard"))["data"]
            text = (
                f"📊 داشبورد {x['site_name']}\n"
                f"🛍 محصولات فعال: {x['products']}\n"
                f"🛒 کل سفارش‌ها: {x['orders']}\n"
                f"🧾 در انتظار بررسی: {x['pending_orders']}\n"
                f"👥 کاربران: {x['users']}"
            )
            return await q.edit_message_text(
                text,
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("⬅️ پنل سایت", callback_data=f"site_info:{sid}")]]
                ),
            )

        if data.startswith("products:"):
            rows = (await api(site, "products"))["data"]
            keys = [
                [InlineKeyboardButton(
                    f"{'✅' if p['is_active'] else '⛔️'} {p['name']} | {p['stock']}",
                    callback_data=f"product:{sid}:{p['id']}",
                )]
                for p in rows[:40]
            ]
            keys.append([InlineKeyboardButton("➕ محصول جدید", callback_data=f"product_add:{sid}")])
            keys.append([InlineKeyboardButton("⬅️ پنل سایت", callback_data=f"site_info:{sid}")])
            return await q.edit_message_text("🛍 محصولات:", reply_markup=InlineKeyboardMarkup(keys))

        if data.startswith("product:"):
            _, sid_s, pid_s = data.split(":")
            p = (await api(site, "product_detail", {"id": int(pid_s)}))["data"]
            text = (
                f"🛍 {p['name']}\n"
                f"کد: {p['sku']}\n"
                f"قیمت: {p['price']:,} تومان\n"
                f"موجودی: {p['stock']}\n"
                f"وضعیت: {'فعال' if p['is_active'] else 'غیرفعال'}"
            )
            kb = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton("💰 قیمت", callback_data=f"prod_price:{sid}:{p['id']}"),
                        InlineKeyboardButton("📦 موجودی", callback_data=f"prod_stock:{sid}:{p['id']}"),
                    ],
                    [
                        InlineKeyboardButton("🔄 فعال/غیرفعال", callback_data=f"prod_toggle:{sid}:{p['id']}"),
                        InlineKeyboardButton("🔥 شگفت‌انگیز", callback_data=f"prod_amazing:{sid}:{p['id']}"),
                    ],
                    [InlineKeyboardButton("🖼 تعویض عکس", callback_data=f"prod_photo:{sid}:{p['id']}")],
                    [InlineKeyboardButton("⬅️ محصولات", callback_data=f"products:{sid}")],
                ]
            )
            return await q.edit_message_text(text, reply_markup=kb)

        if data.startswith("prod_toggle:") or data.startswith("prod_amazing:"):
            action, sid_s, pid_s = data.split(":")
            p = (await api(site, "product_detail", {"id": int(pid_s)}))["data"]
            field = "is_active" if action == "prod_toggle" else "is_amazing"
            await api(site, "product_update", {"id": p["id"], field: not p[field]})
            return await q.edit_message_text(
                "✅ ذخیره شد.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ محصول", callback_data=f"product:{sid}:{p['id']}")]]),
            )

        if data.startswith("prod_price:") or data.startswith("prod_stock:"):
            action, sid_s, pid_s = data.split(":")
            context.user_data.clear()
            context.user_data.update(
                flow="prod_price" if action == "prod_price" else "prod_stock",
                site_id=int(sid_s),
                product_id=int(pid_s),
            )
            return await q.edit_message_text("مقدار جدید را فقط به صورت عدد بفرستید:")

        if data.startswith("prod_photo:"):
            _, sid_s, pid_s = data.split(":")
            context.user_data.clear()
            context.user_data.update(flow="prod_photo", site_id=int(sid_s), product_id=int(pid_s))
            return await q.edit_message_text("عکس جدید محصول را ارسال کنید:")

        if data.startswith("product_add:"):
            rows = (await api(site, "categories"))["data"]
            if not rows:
                return await q.edit_message_text(
                    "ابتدا یک دسته بسازید.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🗂 دسته‌ها", callback_data=f"categories:{sid}")]]),
                )
            keys = [
                [InlineKeyboardButton(c["name"], callback_data=f"prod_new_cat:{sid}:{c['id']}")]
                for c in rows if c["is_active"]
            ]
            return await q.edit_message_text("دسته محصول را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(keys))

        if data.startswith("prod_new_cat:"):
            _, sid_s, cat_s = data.split(":")
            context.user_data.clear()
            context.user_data.update(flow="prod_new_name", site_id=int(sid_s), category_id=int(cat_s))
            return await q.edit_message_text("نام محصول را بفرستید:")

        if data.startswith("categories:"):
            rows = (await api(site, "categories"))["data"]
            keys = [
                [InlineKeyboardButton(
                    f"{'✅' if c['is_active'] else '⛔️'} {c['name']}",
                    callback_data=f"category:{sid}:{c['id']}",
                )]
                for c in rows[:50]
            ]
            keys.append([InlineKeyboardButton("➕ دسته جدید", callback_data=f"category_add:{sid}")])
            keys.append([InlineKeyboardButton("⬅️ پنل سایت", callback_data=f"site_info:{sid}")])
            return await q.edit_message_text("🗂 دسته‌بندی‌ها:", reply_markup=InlineKeyboardMarkup(keys))

        if data.startswith("category:"):
            _, sid_s, cid_s = data.split(":")
            c = (await api(site, "category_detail", {"id": int(cid_s)}))["data"]
            kb = InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("✏️ تغییر نام", callback_data=f"cat_name:{sid}:{c['id']}")],
                    [InlineKeyboardButton("🔄 فعال/غیرفعال", callback_data=f"cat_toggle:{sid}:{c['id']}")],
                    [InlineKeyboardButton("⬅️ دسته‌ها", callback_data=f"categories:{sid}")],
                ]
            )
            return await q.edit_message_text(
                f"🗂 {c['name']}\nمحصولات فعال: {c['product_count']}",
                reply_markup=kb,
            )

        if data.startswith("cat_toggle:"):
            _, sid_s, cid_s = data.split(":")
            c = (await api(site, "category_detail", {"id": int(cid_s)}))["data"]
            await api(site, "category_update", {"id": c["id"], "is_active": not c["is_active"]})
            return await q.edit_message_text(
                "✅ وضعیت دسته تغییر کرد.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ دسته", callback_data=f"category:{sid}:{c['id']}")]]),
            )

        if data.startswith("cat_name:"):
            _, sid_s, cid_s = data.split(":")
            context.user_data.clear()
            context.user_data.update(flow="cat_name", site_id=int(sid_s), category_id=int(cid_s))
            return await q.edit_message_text("نام جدید دسته را بفرستید:")

        if data.startswith("category_add:"):
            context.user_data.clear()
            context.user_data.update(flow="category_add", site_id=sid)
            return await q.edit_message_text("نام دسته جدید را بفرستید:")

        if data.startswith("orders:"):
            rows = (await api(site, "orders"))["data"]
            keys = [
                [InlineKeyboardButton(
                    f"{o['code']} | {o['total']:,} | {o['status']}",
                    callback_data=f"order:{sid}:{o['id']}",
                )]
                for o in rows[:40]
            ]
            keys.append([InlineKeyboardButton("⬅️ پنل سایت", callback_data=f"site_info:{sid}")])
            return await q.edit_message_text("🛒 سفارش‌ها:", reply_markup=InlineKeyboardMarkup(keys))

        if data.startswith("order:"):
            _, sid_s, oid_s = data.split(":")
            o = (await api(site, "order_detail", {"id": int(oid_s)}))["data"]
            text = (
                f"🛒 سفارش {o['code']}\n"
                f"{o['full_name']} | {o['mobile']}\n"
                f"{o['province']}، {o['city']}\n"
                f"{o['address']}\n"
                f"مبلغ: {o['total']:,} تومان\n"
                f"وضعیت: {o['status']}\n"
                f"رسید: {o.get('receipt_status') or '-'}\n"
                f"کد رهگیری: {o.get('tracking_code') or '-'}"
            )
            kb = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton("✅ پرداخت", callback_data=f"order_status:{sid}:{o['id']}:paid"),
                        InlineKeyboardButton("📦 آماده‌سازی", callback_data=f"order_status:{sid}:{o['id']}:processing"),
                    ],
                    [
                        InlineKeyboardButton("❌ لغو", callback_data=f"order_status:{sid}:{o['id']}:cancelled"),
                        InlineKeyboardButton("🚚 کد رهگیری", callback_data=f"order_track:{sid}:{o['id']}"),
                    ],
                    [InlineKeyboardButton("⬅️ سفارش‌ها", callback_data=f"orders:{sid}")],
                ]
            )
            return await q.edit_message_text(text, reply_markup=kb)

        if data.startswith("order_status:"):
            _, sid_s, oid_s, status = data.split(":")
            await api(site, "order_update", {"id": int(oid_s), "status": status})
            return await q.edit_message_text(
                "✅ وضعیت سفارش تغییر کرد.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ سفارش", callback_data=f"order:{sid}:{oid_s}")]]),
            )

        if data.startswith("order_track:"):
            _, sid_s, oid_s = data.split(":")
            context.user_data.clear()
            context.user_data.update(flow="order_track", site_id=int(sid_s), order_id=int(oid_s))
            return await q.edit_message_text("کد رهگیری را بفرستید:")

        if data.startswith("receipts:"):
            rows = (await api(site, "receipts"))["data"]
            keys = [
                [InlineKeyboardButton(
                    f"{r['order_code']} | {r['status']}",
                    callback_data=f"receipt:{sid}:{r['id']}",
                )]
                for r in rows[:40]
            ]
            keys.append([InlineKeyboardButton("⬅️ پنل سایت", callback_data=f"site_info:{sid}")])
            return await q.edit_message_text("🧾 رسیدها:", reply_markup=InlineKeyboardMarkup(keys))

        if data.startswith("receipt:"):
            _, sid_s, rid_s = data.split(":")
            r = (await api(site, "receipt_detail", {"id": int(rid_s)}))["data"]
            text = f"🧾 رسید سفارش {r['order_code']}\nمبلغ: {r['total']:,}\nوضعیت: {r['status']}"
            kb = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton("✅ تأیید", callback_data=f"receipt_set:{sid}:{r['id']}:approved"),
                        InlineKeyboardButton("❌ رد", callback_data=f"receipt_set:{sid}:{r['id']}:rejected"),
                    ],
                    [InlineKeyboardButton("⬅️ رسیدها", callback_data=f"receipts:{sid}")],
                ]
            )
            return await q.edit_message_text(text, reply_markup=kb)

        if data.startswith("receipt_set:"):
            _, sid_s, rid_s, status = data.split(":")
            await api(site, "receipt_update", {"id": int(rid_s), "status": status})
            return await q.edit_message_text(
                "✅ وضعیت رسید ذخیره شد.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ رسیدها", callback_data=f"receipts:{sid}")]]),
            )

        if data.startswith("users:"):
            rows = (await api(site, "users"))["data"]
            keys = [
                [InlineKeyboardButton(
                    f"{'✅' if u['is_active'] else '⛔️'} {u['email'] or u['id']}",
                    callback_data=f"user:{sid}:{u['id']}",
                )]
                for u in rows[:40]
            ]
            keys.append([InlineKeyboardButton("⬅️ پنل سایت", callback_data=f"site_info:{sid}")])
            return await q.edit_message_text("👥 کاربران:", reply_markup=InlineKeyboardMarkup(keys))

        if data.startswith("user:"):
            _, sid_s, user_s = data.split(":")
            u = (await api(site, "user_detail", {"id": int(user_s)}))["data"]
            name = (u.get("first_name") or "") + " " + (u.get("last_name") or "")
            kb = InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("🔄 فعال/غیرفعال", callback_data=f"user_toggle:{sid}:{u['id']}")],
                    [InlineKeyboardButton("⬅️ کاربران", callback_data=f"users:{sid}")],
                ]
            )
            return await q.edit_message_text(
                f"👤 {name.strip() or '-'}\nایمیل: {u.get('email') or '-'}\nوضعیت: {'فعال' if u['is_active'] else 'غیرفعال'}",
                reply_markup=kb,
            )

        if data.startswith("user_toggle:"):
            _, sid_s, user_s = data.split(":")
            u = (await api(site, "user_detail", {"id": int(user_s)}))["data"]
            await api(site, "user_update", {"id": u["id"], "is_active": not u["is_active"]})
            return await q.edit_message_text(
                "✅ وضعیت کاربر تغییر کرد.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ کاربر", callback_data=f"user:{sid}:{u['id']}")]]),
            )

        if data.startswith("banners:"):
            rows = (await api(site, "banners"))["data"]
            keys = [
                [InlineKeyboardButton(
                    f"{'✅' if x['is_active'] else '⛔️'} {x['title'] or 'بدون عنوان'}",
                    callback_data=f"banner_toggle:{sid}:{x['id']}",
                )]
                for x in rows[:30]
            ]
            keys.append([InlineKeyboardButton("➕ بنر جدید", callback_data=f"banner_add:{sid}")])
            keys.append([InlineKeyboardButton("⬅️ پنل سایت", callback_data=f"site_info:{sid}")])
            return await q.edit_message_text("🎞 بنرها (برای تغییر وضعیت روی بنر بزنید):", reply_markup=InlineKeyboardMarkup(keys))

        if data.startswith("banner_toggle:"):
            _, sid_s, bid_s = data.split(":")
            item = (await api(site, "banner_detail", {"id": int(bid_s)}))["data"]
            await api(site, "banner_update", {"id": item["id"], "is_active": not item["is_active"]})
            return await q.edit_message_text(
                "✅ وضعیت بنر تغییر کرد.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ بنرها", callback_data=f"banners:{sid}")]]),
            )

        if data.startswith("banner_add:"):
            context.user_data.clear()
            context.user_data.update(flow="banner_title", site_id=sid)
            return await q.edit_message_text("عنوان بنر را بفرستید؛ برای خالی - بفرستید:")

        if data.startswith("pages:"):
            rows = (await api(site, "pages"))["data"]
            keys = [
                [InlineKeyboardButton(
                    f"{'✅' if x['is_active'] else '⛔️'} {x['title']}",
                    callback_data=f"page_toggle:{sid}:{x['id']}",
                )]
                for x in rows[:40]
            ]
            keys.append([InlineKeyboardButton("➕ صفحه جدید", callback_data=f"page_add:{sid}")])
            keys.append([InlineKeyboardButton("⬅️ پنل سایت", callback_data=f"site_info:{sid}")])
            return await q.edit_message_text("📄 صفحات (برای تغییر وضعیت روی صفحه بزنید):", reply_markup=InlineKeyboardMarkup(keys))

        if data.startswith("page_toggle:"):
            _, sid_s, page_s = data.split(":")
            item = (await api(site, "page_detail", {"id": int(page_s)}))["data"]
            await api(site, "page_update", {"id": item["id"], "is_active": not item["is_active"]})
            return await q.edit_message_text(
                "✅ وضعیت صفحه تغییر کرد.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ صفحات", callback_data=f"pages:{sid}")]]),
            )

        if data.startswith("page_add:"):
            context.user_data.clear()
            context.user_data.update(flow="page_title", site_id=sid)
            return await q.edit_message_text("عنوان صفحه جدید را بفرستید:")

        if data.startswith("socials:"):
            rows = (await api(site, "socials"))["data"]
            keys = [
                [InlineKeyboardButton(
                    f"{'✅' if x['is_active'] else '⛔️'} {x['title']}",
                    callback_data=f"social_toggle:{sid}:{x['id']}",
                )]
                for x in rows[:40]
            ]
            keys.append([InlineKeyboardButton("➕ شبکه اجتماعی", callback_data=f"social_add:{sid}")])
            keys.append([InlineKeyboardButton("⬅️ پنل سایت", callback_data=f"site_info:{sid}")])
            return await q.edit_message_text("🔗 شبکه‌های اجتماعی:", reply_markup=InlineKeyboardMarkup(keys))

        if data.startswith("social_toggle:"):
            _, sid_s, social_s = data.split(":")
            item = (await api(site, "social_detail", {"id": int(social_s)}))["data"]
            await api(site, "social_update", {"id": item["id"], "is_active": not item["is_active"]})
            return await q.edit_message_text(
                "✅ وضعیت شبکه اجتماعی تغییر کرد.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ شبکه‌ها", callback_data=f"socials:{sid}")]]),
            )

        if data.startswith("social_add:"):
            context.user_data.clear()
            context.user_data.update(flow="social_title", site_id=sid)
            return await q.edit_message_text("نام شبکه اجتماعی را بفرستید:")

        if data.startswith("discounts:"):
            rows = (await api(site, "discounts"))["data"]
            keys = [
                [InlineKeyboardButton(
                    f"{'✅' if x['is_active'] else '⛔️'} {x['code']} | {x['percent']}%",
                    callback_data=f"discount_toggle:{sid}:{x['id']}",
                )]
                for x in rows[:40]
            ]
            keys.append([InlineKeyboardButton("➕ کد تخفیف", callback_data=f"discount_add:{sid}")])
            keys.append([InlineKeyboardButton("⬅️ پنل سایت", callback_data=f"site_info:{sid}")])
            return await q.edit_message_text("🎟 کدهای تخفیف:", reply_markup=InlineKeyboardMarkup(keys))

        if data.startswith("discount_toggle:"):
            _, sid_s, did_s = data.split(":")
            item = (await api(site, "discount_detail", {"id": int(did_s)}))["data"]
            await api(site, "discount_update", {"id": item["id"], "is_active": not item["is_active"]})
            return await q.edit_message_text(
                "✅ وضعیت کد تخفیف تغییر کرد.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ تخفیف‌ها", callback_data=f"discounts:{sid}")]]),
            )

        if data.startswith("discount_add:"):
            context.user_data.clear()
            context.user_data.update(flow="discount_code", site_id=sid)
            return await q.edit_message_text("کد تخفیف را بفرستید:")

        if data.startswith("settings:"):
            x = (await api(site, "settings_get"))["data"]
            text = (
                f"⚙️ تنظیمات\n"
                f"نام: {x['site_name']}\n"
                f"اعلان: {x['announcement'] or '-'}\n"
                f"ارسال: {x['shipping_fee']:,}\n"
                f"ارسال رایگان از: {x['free_shipping_threshold']:,}\n"
                f"پرداخت: {x['payment_mode']}"
            )
            kb = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton("✏️ نام", callback_data=f"set_name:{sid}"),
                        InlineKeyboardButton("📣 اعلان", callback_data=f"set_announcement:{sid}"),
                    ],
                    [
                        InlineKeyboardButton("🚚 هزینه ارسال", callback_data=f"set_shipping:{sid}"),
                        InlineKeyboardButton("🎁 ارسال رایگان", callback_data=f"set_free_shipping:{sid}"),
                    ],
                    [InlineKeyboardButton("💳 اطلاعات کارت", callback_data=f"set_card:{sid}")],
                    [InlineKeyboardButton("⬅️ پنل سایت", callback_data=f"site_info:{sid}")],
                ]
            )
            return await q.edit_message_text(text, reply_markup=kb)

        if data.startswith(("set_name:", "set_announcement:", "set_shipping:", "set_free_shipping:", "set_card:")):
            action, sid_s = data.split(":")
            prompts = {
                "set_name": "نام جدید فروشگاه را بفرستید:",
                "set_announcement": "متن اعلان را بفرستید:",
                "set_shipping": "هزینه ارسال را فقط به عدد تومان بفرستید:",
                "set_free_shipping": "حداقل مبلغ ارسال رایگان را فقط به عدد تومان بفرستید:",
                "set_card": "شماره کارت و نام صاحب کارت را با | جدا کنید.\nمثال:\n6037... | نام صاحب کارت",
            }
            context.user_data.clear()
            context.user_data.update(flow=action, site_id=int(sid_s))
            return await q.edit_message_text(prompts[action])

    except Exception as exc:
        return await q.edit_message_text(
            f"❌ خطا در ارتباط با سایت:\n{exc}",
            reply_markup=site_panel(site, uid),
        )


async def message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_authorized(uid):
        return await update.message.reply_text("⛔️ شما مجاز به استفاده از ربات نمی‌باشید.")

    flow = context.user_data.get("flow")
    text = (update.message.text or "").strip()

    if flow == "connect_url" and is_owner(uid):
        if not (text.startswith("https://") or text.startswith("http://")):
            return await update.message.reply_text("آدرس باید با https:// شروع شود.")
        context.user_data["url"] = text.rstrip("/")
        context.user_data["flow"] = "connect_key"
        return await update.message.reply_text("🔑 کلید SANASHOP_BOT_API_KEY سایت را بفرستید:")

    if flow == "connect_key" and is_owner(uid):
        url = context.user_data["url"]
        fake = {"base_url": url, "api_key": text}
        try:
            info = await api(fake, "ping")
        except Exception as exc:
            return await update.message.reply_text(
                f"❌ اتصال ناموفق:\n{exc}\n\nبعد از اصلاح، /start را بزنید و دوباره تلاش کنید."
            )
        name = info["site"]["name"]
        with db() as c:
            existing = c.execute("SELECT id FROM sites WHERE base_url=?", (url,)).fetchone()
            if existing:
                c.execute("UPDATE sites SET name=?, api_key=? WHERE id=?", (name, text, existing["id"]))
            else:
                c.execute("INSERT INTO sites(name, base_url, api_key) VALUES(?,?,?)", (name, url, text))
            c.commit()
        context.user_data.clear()
        return await update.message.reply_text(
            f"✅ سایت «{name}» به ربات متصل شد.\nبرای دسترسی مدیران از بخش «مدیران» استفاده کنید.",
            reply_markup=owner_home(),
        )

    if flow == "admin_add_id" and is_owner(uid):
        if not text.isdigit():
            return await update.message.reply_text("آیدی مدیر باید فقط عدد باشد.")
        admin_id = int(text)
        if admin_id == OWNER_ID:
            return await update.message.reply_text("این آیدی متعلق به مالک اصلی است.")
        with db() as c:
            sites = c.execute("SELECT * FROM sites ORDER BY id").fetchall()
        if not sites:
            return await update.message.reply_text("ابتدا حداقل یک سایت متصل کنید.", reply_markup=owner_home())
        context.user_data["pending_admin_id"] = admin_id
        context.user_data["flow"] = "admin_choose_site"
        keys = [
            [InlineKeyboardButton(s["name"], callback_data=f"admin_grant:{s['id']}")]
            for s in sites
        ]
        keys.append([InlineKeyboardButton("⬅️ انصراف", callback_data="admins")])
        return await update.message.reply_text(
            f"مدیر {admin_id} به کدام سایت دسترسی داشته باشد؟\nفقط همان سایت برای او باز خواهد بود:",
            reply_markup=InlineKeyboardMarkup(keys),
        )

    if flow == "admin_del" and is_owner(uid):
        if not text.isdigit():
            return await update.message.reply_text("آیدی باید فقط عدد باشد.")
        admin_id = int(text)
        with db() as c:
            c.execute("DELETE FROM site_admins WHERE telegram_id=?", (admin_id,))
            c.execute("DELETE FROM admins WHERE telegram_id=?", (admin_id,))
            c.commit()
        context.user_data.clear()
        return await update.message.reply_text("✅ دسترسی مدیر حذف شد.", reply_markup=owner_home())

    site_id = context.user_data.get("site_id")
    if site_id and not can_access(uid, int(site_id)):
        context.user_data.clear()
        return await update.message.reply_text("⛔️ دسترسی شما به این سایت لغو شده است.")

    site = get_site(int(site_id)) if site_id else None
    if not site:
        return

    try:
        if flow in ("prod_price", "prod_stock"):
            if not text.replace(",", "").isdigit():
                return await update.message.reply_text("فقط عدد بفرستید.")
            value = int(text.replace(",", ""))
            field = "price" if flow == "prod_price" else "stock"
            await api(site, "product_update", {"id": context.user_data["product_id"], field: value})
            pid = context.user_data["product_id"]
            context.user_data.clear()
            return await update.message.reply_text(
                "✅ ذخیره شد.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ محصول", callback_data=f"product:{site['id']}:{pid}")]]),
            )

        if flow == "prod_new_name" and text:
            context.user_data["name"] = text
            context.user_data["flow"] = "prod_new_price"
            return await update.message.reply_text("قیمت محصول به تومان:")

        if flow == "prod_new_price" and text.replace(",", "").isdigit():
            context.user_data["price"] = int(text.replace(",", ""))
            context.user_data["flow"] = "prod_new_stock"
            return await update.message.reply_text("موجودی اولیه:")

        if flow == "prod_new_stock" and text.isdigit():
            payload = {
                "category_id": context.user_data["category_id"],
                "name": context.user_data["name"],
                "price": context.user_data["price"],
                "stock": int(text),
            }
            product = (await api(site, "product_create", payload))["data"]
            context.user_data.clear()
            return await update.message.reply_text(
                f"✅ محصول ساخته شد.\nکد: {product['sku']}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("باز کردن محصول", callback_data=f"product:{site['id']}:{product['id']}")]]),
            )

        if flow == "cat_name" and text:
            cid = context.user_data["category_id"]
            await api(site, "category_update", {"id": cid, "name": text})
            context.user_data.clear()
            return await update.message.reply_text("✅ نام دسته تغییر کرد.", reply_markup=site_panel(site, uid))

        if flow == "category_add" and text:
            await api(site, "category_create", {"name": text})
            context.user_data.clear()
            return await update.message.reply_text("✅ دسته ساخته شد.", reply_markup=site_panel(site, uid))

        if flow == "order_track" and text:
            oid = context.user_data["order_id"]
            await api(site, "order_update", {"id": oid, "status": "shipped", "tracking_code": text})
            context.user_data.clear()
            return await update.message.reply_text("✅ کد رهگیری ثبت شد.", reply_markup=site_panel(site, uid))

        if flow == "banner_title":
            context.user_data["title"] = "" if text == "-" else text
            context.user_data["flow"] = "banner_subtitle"
            return await update.message.reply_text("متن کوتاه بنر را بفرستید؛ برای خالی -:")

        if flow == "banner_subtitle":
            context.user_data["subtitle"] = "" if text == "-" else text
            context.user_data["flow"] = "banner_link"
            return await update.message.reply_text("لینک بنر را بفرستید؛ مثال /products/")

        if flow == "banner_link":
            context.user_data["link"] = text or "/products/"
            context.user_data["flow"] = "banner_photo"
            return await update.message.reply_text("حالا عکس بنر را ارسال کنید:")

        if flow == "page_title":
            context.user_data["title"] = text
            context.user_data["flow"] = "page_body"
            return await update.message.reply_text("متن صفحه را بفرستید:")

        if flow == "page_body":
            context.user_data["body"] = text
            context.user_data["flow"] = "page_group"
            return await update.message.reply_text("گروه صفحه را بفرستید: guide یا contact یا other")

        if flow == "page_group" and text in ("guide", "contact", "other"):
            await api(site, "page_create", {
                "title": context.user_data["title"],
                "body": context.user_data["body"],
                "footer_group": text,
            })
            context.user_data.clear()
            return await update.message.reply_text("✅ صفحه ساخته شد.", reply_markup=site_panel(site, uid))

        if flow == "social_title":
            context.user_data["title"] = text
            context.user_data["flow"] = "social_url"
            return await update.message.reply_text("لینک شبکه اجتماعی را بفرستید:")

        if flow == "social_url":
            context.user_data["url"] = text
            context.user_data["flow"] = "social_photo"
            return await update.message.reply_text("حالا عکس/آیکن را ارسال کنید:")

        if flow == "discount_code":
            context.user_data["code"] = text.upper()
            context.user_data["flow"] = "discount_percent"
            return await update.message.reply_text("درصد تخفیف (1 تا 99):")

        if flow == "discount_percent" and text.isdigit() and 1 <= int(text) <= 99:
            context.user_data["percent"] = int(text)
            context.user_data["flow"] = "discount_min"
            return await update.message.reply_text("حداقل مبلغ سفارش؛ برای بدون حداقل 0:")

        if flow == "discount_min" and text.replace(",", "").isdigit():
            await api(site, "discount_create", {
                "code": context.user_data["code"],
                "percent": context.user_data["percent"],
                "min_order_amount": int(text.replace(",", "")),
            })
            context.user_data.clear()
            return await update.message.reply_text("✅ کد تخفیف ساخته شد.", reply_markup=site_panel(site, uid))

        if flow in ("set_name", "set_announcement"):
            field = "site_name" if flow == "set_name" else "announcement"
            await api(site, "settings_update", {field: text})
            context.user_data.clear()
            return await update.message.reply_text("✅ ذخیره شد.", reply_markup=site_panel(site, uid))

        if flow in ("set_shipping", "set_free_shipping") and text.replace(",", "").isdigit():
            field = "shipping_fee" if flow == "set_shipping" else "free_shipping_threshold"
            await api(site, "settings_update", {field: int(text.replace(",", ""))})
            context.user_data.clear()
            return await update.message.reply_text("✅ ذخیره شد.", reply_markup=site_panel(site, uid))

        if flow == "set_card" and "|" in text:
            card, owner = [x.strip() for x in text.split("|", 1)]
            await api(site, "settings_update", {"card_number": card, "card_owner": owner})
            context.user_data.clear()
            return await update.message.reply_text("✅ اطلاعات کارت ذخیره شد.", reply_markup=site_panel(site, uid))
    except Exception as exc:
        return await update.message.reply_text(f"❌ عملیات ناموفق بود:\n{exc}")


async def photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_authorized(uid):
        return await update.message.reply_text("⛔️ شما مجاز به استفاده از ربات نمی‌باشید.")
    flow = context.user_data.get("flow")
    if flow not in ("prod_photo", "banner_photo", "social_photo"):
        return
    site_id = context.user_data.get("site_id")
    if not site_id or not can_access(uid, int(site_id)):
        context.user_data.clear()
        return await update.message.reply_text("⛔️ دسترسی شما به این سایت لغو شده است.")
    site = get_site(int(site_id))
    tg_file = await update.message.photo[-1].get_file()
    raw = await tg_file.download_as_bytearray()
    encoded = base64.b64encode(bytes(raw)).decode("ascii")
    try:
        if flow == "prod_photo":
            pid = context.user_data["product_id"]
            await api(site, "product_image_set", {"id": pid, "image_b64": encoded, "filename": "product.jpg"}, timeout=45)
            context.user_data.clear()
            return await update.message.reply_text("✅ عکس محصول ذخیره شد.", reply_markup=site_panel(site, uid))
        if flow == "banner_photo":
            await api(site, "banner_create", {
                "title": context.user_data.get("title", ""),
                "subtitle": context.user_data.get("subtitle", ""),
                "link": context.user_data.get("link", "/products/"),
                "image_b64": encoded,
                "filename": "banner.jpg",
            }, timeout=45)
            context.user_data.clear()
            return await update.message.reply_text("✅ بنر ساخته شد.", reply_markup=site_panel(site, uid))
        if flow == "social_photo":
            await api(site, "social_create", {
                "title": context.user_data["title"],
                "url": context.user_data["url"],
                "image_b64": encoded,
                "filename": "social.jpg",
            }, timeout=45)
            context.user_data.clear()
            return await update.message.reply_text("✅ شبکه اجتماعی ساخته شد.", reply_markup=site_panel(site, uid))
    except Exception as exc:
        await update.message.reply_text(f"❌ آپلود ناموفق بود:\n{exc}")


def run():
    db()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.PHOTO, photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message))
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    run()
