#!/usr/bin/env python3
import asyncio
import json
import re
import shlex
import sqlite3
import uuid
from pathlib import Path

import paramiko

import external_bot as core
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes


ORIGINAL_DB = core.db
ORIGINAL_CALLBACK = core.callback
ORIGINAL_MESSAGE = core.message


def db():
    conn = ORIGINAL_DB()
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(sites)").fetchall()}
    additions = {
        "ssh_host": "TEXT",
        "ssh_port": "INTEGER DEFAULT 22",
        "ssh_user": "TEXT DEFAULT 'root'",
        "ssh_password": "TEXT",
    }
    for name, decl in additions.items():
        if name not in cols:
            conn.execute(f"ALTER TABLE sites ADD COLUMN {name} {decl}")
    conn.commit()
    return conn


core.db = db


def _client(host, port, user, password, timeout=15):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=host,
        port=int(port),
        username=user,
        password=password,
        timeout=timeout,
        banner_timeout=timeout,
        auth_timeout=timeout,
        look_for_keys=False,
        allow_agent=False,
    )
    return client


def _read_channel(stdout, timeout=60):
    channel = stdout.channel
    channel.set_combine_stderr(True)
    channel.settimeout(timeout)
    data = stdout.read()
    status = channel.recv_exit_status()
    return status, data.decode("utf-8", errors="replace")


def ssh_exec_raw(host, port, user, password, command, timeout=60):
    client = _client(host, port, user, password, timeout=min(timeout, 30))
    try:
        _, stdout, _ = client.exec_command(command, timeout=timeout, get_pty=False)
        status, output = _read_channel(stdout, timeout=timeout)
        if status != 0:
            raise RuntimeError(output.strip() or f"SSH command failed ({status})")
        return output
    finally:
        client.close()


def ssh_exec_site(site, command, timeout=60):
    host = site["ssh_host"]
    port = site["ssh_port"] or 22
    user = site["ssh_user"] or "root"
    password = site["ssh_password"]
    if not host or not password:
        raise RuntimeError("این سایت با روش قدیمی متصل شده؛ آن را دوباره با SSH متصل کنید.")
    return ssh_exec_raw(host, port, user, password, command, timeout=timeout)


def ssh_api_call(site, action, payload=None, timeout=60):
    host = site["ssh_host"]
    port = site["ssh_port"] or 22
    user = site["ssh_user"] or "root"
    password = site["ssh_password"]
    api_key = site["api_key"]
    if not host or not password or not api_key:
        raise RuntimeError("اطلاعات SSH این سایت کامل نیست؛ دوباره متصلش کنید.")

    body = json.dumps({"action": action, "payload": payload or {}}, ensure_ascii=False)
    remote_file = f"/tmp/sanashop-bot-{uuid.uuid4().hex}.json"
    client = _client(host, port, user, password, timeout=min(timeout, 30))
    try:
        sftp = client.open_sftp()
        try:
            with sftp.open(remote_file, "w") as handle:
                handle.write(body)
        finally:
            sftp.close()

        command = (
            "cd /opt/sanashop && "
            f"cat {shlex.quote(remote_file)} | "
            "docker compose exec -T web curl -fsS -X POST "
            f"-H {shlex.quote('Authorization: Bearer ' + api_key)} "
            "-H 'Content-Type: application/json' --data-binary @- "
            "http://127.0.0.1:8000/api/bot/v1/"
        )
        _, stdout, _ = client.exec_command(command, timeout=timeout, get_pty=False)
        status, output = _read_channel(stdout, timeout=timeout)
        try:
            client.exec_command(f"rm -f {shlex.quote(remote_file)}", timeout=10)
        except Exception:
            pass
        if status != 0:
            raise RuntimeError(output.strip() or "اجرای API محلی سایت از طریق SSH ناموفق بود.")
        try:
            data = json.loads(output)
        except Exception as exc:
            raise RuntimeError(f"پاسخ نامعتبر از سایت: {output[:500]}") from exc
        if not data.get("ok", False):
            raise RuntimeError(data.get("error") or "عملیات سایت ناموفق بود.")
        return data
    finally:
        client.close()


async def api(site, action, payload=None, timeout=60):
    try:
        return await asyncio.to_thread(ssh_api_call, site, action, payload, timeout)
    except paramiko.AuthenticationException as exc:
        raise RuntimeError("رمز SSH سرور ایران اشتباه است.") from exc
    except paramiko.SSHException as exc:
        raise RuntimeError(f"خطای SSH: {exc}") from exc
    except TimeoutError as exc:
        raise RuntimeError("اتصال SSH به سرور ایران Timeout شد.") from exc
    except OSError as exc:
        raise RuntimeError(f"اتصال SSH به سرور ایران برقرار نشد: {exc}") from exc


core.api = api


def _conn_from_context(context):
    return {
        "host": context.user_data["ssh_host"],
        "port": int(context.user_data.get("ssh_port") or 22),
        "user": "root",
        "password": context.user_data["ssh_password"],
    }


def _test_ssh(conn):
    output = ssh_exec_raw(
        conn["host"], conn["port"], conn["user"], conn["password"],
        "printf 'OK:'; id -u; printf ':'; hostname",
        timeout=20,
    ).strip()
    if not output.startswith("OK:0:"):
        raise RuntimeError("اتصال برقرار شد ولی کاربر SSH باید root باشد.")
    return output


def _discover_existing(conn):
    check = ssh_exec_raw(
        conn["host"], conn["port"], conn["user"], conn["password"],
        "test -f /opt/sanashop/.env && echo INSTALLED || echo EMPTY",
        timeout=20,
    ).strip()
    if "INSTALLED" not in check:
        return None

    ssh_exec_raw(
        conn["host"], conn["port"], conn["user"], conn["password"],
        "cd /opt/sanashop && docker compose up -d db web caddy >/dev/null 2>&1 || true",
        timeout=180,
    )
    raw = ssh_exec_raw(
        conn["host"], conn["port"], conn["user"], conn["password"],
        "cd /opt/sanashop && "
        "printf 'DOMAIN='; sed -n 's/^DOMAIN=//p' .env | head -n1; "
        "printf 'KEY='; sed -n 's/^SANASHOP_BOT_API_KEY=//p' .env | head -n1",
        timeout=30,
    )
    vals = {}
    for line in raw.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            vals[k.strip()] = v.strip()
    if not vals.get("KEY"):
        raise RuntimeError("سایت پیدا شد ولی SANASHOP_BOT_API_KEY داخل .env وجود ندارد.")
    site = {
        "ssh_host": conn["host"],
        "ssh_port": conn["port"],
        "ssh_user": conn["user"],
        "ssh_password": conn["password"],
        "api_key": vals["KEY"],
        "base_url": f"https://{vals.get('DOMAIN') or conn['host']}",
    }
    info = ssh_api_call(site, "ping", {}, timeout=30)
    return {
        "name": info["site"]["name"],
        "domain": info["site"].get("domain") or vals.get("DOMAIN") or conn["host"],
        "api_key": vals["KEY"],
    }


def _save_site(conn, info):
    base_url = f"https://{info['domain']}" if info.get("domain") else f"ssh://{conn['host']}:{conn['port']}"
    with db() as c:
        existing = c.execute(
            "SELECT id FROM sites WHERE ssh_host=? OR base_url=?",
            (conn["host"], base_url),
        ).fetchone()
        values = (
            info["name"], base_url, info["api_key"],
            conn["host"], int(conn["port"]), conn["user"], conn["password"],
        )
        if existing:
            c.execute(
                "UPDATE sites SET name=?,base_url=?,api_key=?,ssh_host=?,ssh_port=?,ssh_user=?,ssh_password=? WHERE id=?",
                values + (existing["id"],),
            )
            site_id = existing["id"]
        else:
            cur = c.execute(
                "INSERT INTO sites(name,base_url,api_key,ssh_host,ssh_port,ssh_user,ssh_password) VALUES(?,?,?,?,?,?,?)",
                values,
            )
            site_id = cur.lastrowid
        c.commit()
    return site_id


def _remote_install(conn, cfg):
    env = {
        "DOMAIN": cfg["domain"],
        "ACME_EMAIL": cfg["email"],
        "DEFAULT_SITE_NAME": cfg["site_name"],
        "DJANGO_SUPERUSER_USERNAME": "admin",
        "DJANGO_SUPERUSER_PASSWORD": cfg["admin_password"],
        "SMTP_HOST": "smtp.gmail.com",
        "SMTP_PORT": "587",
        "SMTP_USER": cfg["email"],
        "SMTP_PASSWORD": cfg["smtp_password"],
        "DEFAULT_FROM_EMAIL": cfg["email"],
    }
    exports = " ".join(f"{k}={shlex.quote(v)}" for k, v in env.items())
    command = (
        "rm -rf /opt/sanashop; "
        f"{exports} bash -c \"curl -fsSL https://raw.githubusercontent.com/deltashopsiavash/sanashop/main/install-site.sh | bash\" "
        ">/tmp/sanashop-telegram-install.log 2>&1; "
        "code=$?; tail -n 120 /tmp/sanashop-telegram-install.log; exit $code"
    )
    return ssh_exec_raw(
        conn["host"], conn["port"], conn["user"], conn["password"],
        command,
        timeout=1200,
    )


async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    data = q.data or ""
    if data == "connect":
        if not core.is_owner(uid):
            return await q.answer("فقط مالک اصلی می‌تواند سایت اضافه کند.", show_alert=True)
        await q.answer()
        context.user_data.clear()
        context.user_data["flow"] = "ssh_host"
        return await q.edit_message_text(
            "🔌 اتصال سایت با SSH\n\nIP سرور ایران را بفرستید.\nمثال: 31.171.101.211"
        )
    return await ORIGINAL_CALLBACK(update, context)


async def message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    flow = context.user_data.get("flow")
    text = (update.message.text or "").strip()

    if core.is_owner(uid) and flow == "ssh_host":
        if not re.fullmatch(r"[A-Za-z0-9.:-]+", text):
            return await update.message.reply_text("IP/Host معتبر بفرستید.")
        context.user_data["ssh_host"] = text
        context.user_data["flow"] = "ssh_port"
        return await update.message.reply_text("پورت SSH را بفرستید. اگر تغییرش ندادی عدد 22 را بفرست:")

    if core.is_owner(uid) and flow == "ssh_port":
        if not text.isdigit() or not 1 <= int(text) <= 65535:
            return await update.message.reply_text("پورت معتبر بفرستید؛ معمولاً 22 است.")
        context.user_data["ssh_port"] = int(text)
        context.user_data["flow"] = "ssh_password"
        return await update.message.reply_text("🔐 رمز root سرور ایران را بفرستید:")

    if core.is_owner(uid) and flow == "ssh_password":
        context.user_data["ssh_password"] = text
        try:
            await update.message.delete()
        except Exception:
            pass
        status = await update.effective_chat.send_message("⏳ در حال تست SSH سرور ایران...")
        conn = _conn_from_context(context)
        try:
            await asyncio.to_thread(_test_ssh, conn)
            existing = await asyncio.to_thread(_discover_existing, conn)
        except Exception as exc:
            context.user_data["flow"] = "ssh_password"
            return await status.edit_text(f"❌ اتصال SSH ناموفق بود:\n{exc}\n\nرمز root را دوباره بفرستید.")
        if existing:
            _save_site(conn, existing)
            context.user_data.clear()
            return await status.edit_text(
                f"✅ سایت «{existing['name']}» از روی سرور ایران پیدا و متصل شد.\n"
                "از این به بعد مدیریت سایت فقط از داخل SSH انجام می‌شود.",
                reply_markup=core.owner_home(),
            )
        context.user_data["flow"] = "install_domain"
        return await status.edit_text(
            "✅ SSH برقرار شد و سرور خام است.\n\nدامنه سایت را بدون https:// بفرستید:"
        )

    if core.is_owner(uid) and flow == "install_domain":
        domain = text.lower().replace("https://", "").replace("http://", "").strip("/")
        if not re.fullmatch(r"[A-Za-z0-9.-]+", domain):
            return await update.message.reply_text("دامنه معتبر نیست.")
        context.user_data["domain"] = domain
        context.user_data["flow"] = "install_site_name"
        return await update.message.reply_text("نام فروشگاه را بفرستید؛ مثال VELORA:")

    if core.is_owner(uid) and flow == "install_site_name":
        if not text:
            return await update.message.reply_text("نام فروشگاه خالی نباشد.")
        context.user_data["site_name"] = text
        context.user_data["flow"] = "install_email"
        return await update.message.reply_text(
            "ایمیل Gmail را بفرستید. همین ایمیل برای SSL و ایمیل‌های سایت استفاده می‌شود:"
        )

    if core.is_owner(uid) and flow == "install_email":
        if "@" not in text:
            return await update.message.reply_text("ایمیل معتبر بفرستید.")
        context.user_data["email"] = text
        context.user_data["flow"] = "install_admin_password"
        return await update.message.reply_text("رمز پنل /admin سایت را بفرستید:")

    if core.is_owner(uid) and flow == "install_admin_password":
        if len(text) < 6:
            return await update.message.reply_text("رمز حداقل 6 کاراکتر باشد.")
        context.user_data["admin_password"] = text
        try:
            await update.message.delete()
        except Exception:
            pass
        context.user_data["flow"] = "install_smtp_password"
        return await update.effective_chat.send_message("App Password جیمیل را بفرستید:")

    if core.is_owner(uid) and flow == "install_smtp_password":
        context.user_data["smtp_password"] = text.replace(" ", "")
        try:
            await update.message.delete()
        except Exception:
            pass
        conn = _conn_from_context(context)
        cfg = {
            "domain": context.user_data["domain"],
            "site_name": context.user_data["site_name"],
            "email": context.user_data["email"],
            "admin_password": context.user_data["admin_password"],
            "smtp_password": context.user_data["smtp_password"],
        }
        status = await update.effective_chat.send_message(
            "⏳ نصب کامل سایت روی سرور ایران شروع شد. ممکن است چند دقیقه طول بکشد..."
        )
        try:
            await asyncio.to_thread(_remote_install, conn, cfg)
            existing = await asyncio.to_thread(_discover_existing, conn)
            if not existing:
                raise RuntimeError("نصب تمام شد ولی سایت قابل شناسایی نیست.")
            _save_site(conn, existing)
        except Exception as exc:
            context.user_data.clear()
            return await status.edit_text(
                f"❌ نصب خودکار ناموفق بود:\n{exc}\n\n"
                "برای دیدن لاگ روی سرور ایران:\ncat /tmp/sanashop-telegram-install.log"
            )
        context.user_data.clear()
        return await status.edit_text(
            f"✅ سایت «{existing['name']}» نصب و با SSH به ربات متصل شد.\n"
            "حالا از «سایت‌های متصل شده» وارد پنلش شو.",
            reply_markup=core.owner_home(),
        )

    return await ORIGINAL_MESSAGE(update, context)


core.callback = callback
core.message = message


if __name__ == "__main__":
    core.run()
