#!/usr/bin/env python3
import os, sqlite3, logging
from pathlib import Path
import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
DB_PATH = Path(os.environ.get("BOT_DB_PATH", "/var/lib/sanashop-bot/bot.sqlite3"))
OWNER_ID = int(os.environ["TELEGRAM_OWNER_ID"])
TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]


def db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS admins(id INTEGER PRIMARY KEY, telegram_id INTEGER UNIQUE NOT NULL, added_by INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS sites(id INTEGER PRIMARY KEY, name TEXT NOT NULL, base_url TEXT NOT NULL UNIQUE, api_key TEXT NOT NULL, owner_id INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS site_admins(site_id INTEGER NOT NULL, telegram_id INTEGER NOT NULL, UNIQUE(site_id,telegram_id));
    CREATE TABLE IF NOT EXISTS active_site(telegram_id INTEGER PRIMARY KEY, site_id INTEGER NOT NULL);
    ''')
    conn.execute("INSERT OR IGNORE INTO admins(telegram_id,added_by) VALUES(?,?)", (OWNER_ID, OWNER_ID)); conn.commit()
    return conn


def is_admin(uid):
    with db() as c: return c.execute("SELECT 1 FROM admins WHERE telegram_id=?", (uid,)).fetchone() is not None

def is_owner(uid): return uid == OWNER_ID

def sites_for(uid):
    with db() as c:
        if is_owner(uid): return c.execute("SELECT * FROM sites ORDER BY id").fetchall()
        return c.execute("SELECT s.* FROM sites s JOIN site_admins a ON a.site_id=s.id WHERE a.telegram_id=? ORDER BY s.id", (uid,)).fetchall()

def active(uid):
    with db() as c:
        row=c.execute("SELECT s.* FROM sites s JOIN active_site a ON a.site_id=s.id WHERE a.telegram_id=?",(uid,)).fetchone()
        if row and (is_owner(uid) or c.execute("SELECT 1 FROM site_admins WHERE site_id=? AND telegram_id=?",(row['id'],uid)).fetchone()): return row
    ss=sites_for(uid); return ss[0] if ss else None

async def api(site, action, payload=None):
    url=site['base_url'].rstrip('/')+"/api/bot/v1/"
    async with httpx.AsyncClient(timeout=20) as client:
        r=await client.post(url, headers={"Authorization":f"Bearer {site['api_key']}"}, json={"action":action,"payload":payload or {}})
        r.raise_for_status(); return r.json()

def main_kb(uid):
    rows=[[InlineKeyboardButton("🏪 سایت‌ها",callback_data="sites"),InlineKeyboardButton("🔗 اتصال سایت",callback_data="connect")],
          [InlineKeyboardButton("📊 داشبورد",callback_data="dash"),InlineKeyboardButton("🛍 محصولات",callback_data="products")],
          [InlineKeyboardButton("🛒 سفارش‌ها",callback_data="orders"),InlineKeyboardButton("👥 کاربران",callback_data="users")],
          [InlineKeyboardButton("⚙️ تنظیمات",callback_data="settings")]]
    if is_owner(uid): rows.append([InlineKeyboardButton("👤 مدیران",callback_data="admins")])
    return InlineKeyboardMarkup(rows)

async def start(update:Update, context:ContextTypes.DEFAULT_TYPE):
    uid=update.effective_user.id
    if not is_admin(uid): return await update.message.reply_text("⛔️ دسترسی ندارید.")
    s=active(uid); name=s['name'] if s else "هیچ سایتی انتخاب نشده"
    await update.message.reply_text(f"💎 پنل مدیریت چندسایته\nسایت فعال: {name}",reply_markup=main_kb(uid))

async def cb(update:Update, context:ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; uid=q.from_user.id
    if not is_admin(uid): return await q.answer("عدم دسترسی",show_alert=True)
    await q.answer(); d=q.data
    if d=="connect":
        if not is_owner(uid): return await q.edit_message_text("فقط مالک اصلی می‌تواند سایت جدید متصل کند.",reply_markup=main_kb(uid))
        context.user_data.clear(); context.user_data['flow']='connect_url'; return await q.edit_message_text("آدرس کامل سایت را بفرستید؛ مثال https://shop.example.com")
    if d=="sites":
        ss=sites_for(uid); keys=[[InlineKeyboardButton(f"{'✅ ' if active(uid) and active(uid)['id']==s['id'] else ''}{s['name']}",callback_data=f"site:{s['id']}")] for s in ss]
        keys.append([InlineKeyboardButton("⬅️ منو",callback_data="home")]); return await q.edit_message_text("🏪 سایت‌های شما:",reply_markup=InlineKeyboardMarkup(keys))
    if d.startswith("site:"):
        sid=int(d.split(':')[1]); allowed={s['id'] for s in sites_for(uid)}
        if sid not in allowed:return
        with db() as c: c.execute("INSERT OR REPLACE INTO active_site(telegram_id,site_id) VALUES(?,?)",(uid,sid)); c.commit()
        return await q.edit_message_text("✅ سایت فعال تغییر کرد.",reply_markup=main_kb(uid))
    if d=="home": return await q.edit_message_text("💎 پنل مدیریت",reply_markup=main_kb(uid))
    if d=="admins":
        if not is_owner(uid): return
        with db() as c: rows=c.execute("SELECT telegram_id FROM admins ORDER BY telegram_id").fetchall()
        text="👤 مدیران:\n"+"\n".join(str(x['telegram_id']) for x in rows)
        kb=InlineKeyboardMarkup([[InlineKeyboardButton("➕ افزودن مدیر",callback_data="admin_add"),InlineKeyboardButton("➖ حذف مدیر",callback_data="admin_del")],[InlineKeyboardButton("⬅️ منو",callback_data="home")]])
        return await q.edit_message_text(text,reply_markup=kb)
    if d in ("admin_add","admin_del"):
        if not is_owner(uid): return
        context.user_data.clear();context.user_data['flow']=d;return await q.edit_message_text("آیدی عددی تلگرام را بفرستید:")
    s=active(uid)
    if not s:return await q.edit_message_text("ابتدا یک سایت متصل/انتخاب کنید.",reply_markup=main_kb(uid))
    try:
        if d=="dash":
            x=(await api(s,"dashboard"))['data']; txt=f"📊 {x['site_name']}\nمحصولات: {x['products']}\nسفارش‌ها: {x['orders']}\nدر انتظار بررسی: {x['pending_orders']}\nکاربران: {x['users']}"
        elif d=="products":
            rows=(await api(s,"products"))['data'];txt="🛍 محصولات:\n"+"\n".join(f"#{x['id']} {x['name']} | {x['price']:,} | موجودی {x['stock']}" for x in rows[:30])
        elif d=="orders":
            rows=(await api(s,"orders"))['data'];txt="🛒 سفارش‌ها:\n"+"\n".join(f"#{x['id']} {x['code']} | {x['full_name']} | {x['total']:,} | {x['status']}" for x in rows[:30])
        elif d=="users":
            rows=(await api(s,"users"))['data'];txt="👥 کاربران:\n"+"\n".join(f"#{x['id']} {x['email']} {'✅' if x['is_active'] else '⛔️'}" for x in rows[:30])
        elif d=="settings":
            x=(await api(s,"settings_get"))['data'];txt=f"⚙️ تنظیمات\nنام: {x['site_name']}\nارسال: {x['shipping_fee']:,}\nارسال رایگان از: {x['free_shipping_threshold']:,}\nپرداخت: {x['payment_mode']}"
        else:return
        await q.edit_message_text(txt,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ منو",callback_data="home")]]))
    except Exception as e: await q.edit_message_text(f"❌ ارتباط با سایت ناموفق بود:\n{e}",reply_markup=main_kb(uid))

async def msg(update:Update, context:ContextTypes.DEFAULT_TYPE):
    uid=update.effective_user.id
    if not is_admin(uid): return
    flow=context.user_data.get('flow'); text=(update.message.text or '').strip()
    if flow=='connect_url':
        context.user_data['url']=text.rstrip('/');context.user_data['flow']='connect_key';return await update.message.reply_text("کلید اتصال SANASHOP_BOT_API_KEY سایت را بفرستید:")
    if flow=='connect_key':
        url=context.user_data['url']; fake={'base_url':url,'api_key':text}
        try: info=await api(fake,'ping'); name=info['site']['name']
        except Exception as e:return await update.message.reply_text(f"❌ اتصال ناموفق: {e}\nآدرس/کلید را بررسی کنید و /start بزنید.")
        with db() as c:
            cur=c.execute("INSERT INTO sites(name,base_url,api_key,owner_id) VALUES(?,?,?,?)",(name,url,text,uid));sid=cur.lastrowid
            c.execute("INSERT OR IGNORE INTO site_admins(site_id,telegram_id) VALUES(?,?)",(sid,uid));c.execute("INSERT OR REPLACE INTO active_site VALUES(?,?)",(uid,sid));c.commit()
        context.user_data.clear();return await update.message.reply_text(f"✅ سایت {name} متصل شد.",reply_markup=main_kb(uid))
    if flow=='admin_add' and text.isdigit():
        aid=int(text)
        with db() as c:
            c.execute("INSERT OR IGNORE INTO admins(telegram_id,added_by) VALUES(?,?)",(aid,uid))
            for s in c.execute("SELECT id FROM sites").fetchall(): c.execute("INSERT OR IGNORE INTO site_admins VALUES(?,?)",(s['id'],aid))
            c.commit()
        context.user_data.clear();return await update.message.reply_text("✅ مدیر اضافه شد و به سایت‌های فعلی دسترسی گرفت.",reply_markup=main_kb(uid))
    if flow=='admin_del' and text.isdigit():
        aid=int(text)
        if aid==OWNER_ID:return await update.message.reply_text("مالک اصلی قابل حذف نیست.")
        with db() as c:c.execute("DELETE FROM admins WHERE telegram_id=?",(aid,));c.execute("DELETE FROM site_admins WHERE telegram_id=?",(aid,));c.execute("DELETE FROM active_site WHERE telegram_id=?",(aid,));c.commit()
        context.user_data.clear();return await update.message.reply_text("✅ دسترسی مدیر حذف شد.",reply_markup=main_kb(uid))


def run():
    db(); app=Application.builder().token(TOKEN).build();app.add_handler(CommandHandler("start",start));app.add_handler(CallbackQueryHandler(cb));app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,msg));app.run_polling(drop_pending_updates=True)

if __name__=='__main__':run()
