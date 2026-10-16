#!/usr/bin/env bash
set -Eeuo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "این دستور باید با sudo/root اجرا شود."
  exit 1
fi

APP_DIR="${SANASHOP_BOT_DIR:-/opt/sanashop-bot}"
REPO_URL="https://github.com/deltashopsiavash/sanashop.git"

if [[ ! -f /etc/sanashop-bot.env ]]; then
  echo "❌ فایل /etc/sanashop-bot.env پیدا نشد؛ ربات باید قبلاً نصب شده باشد."
  exit 1
fi

if [[ ! -d "$APP_DIR/.git" ]]; then
  echo "❌ ریپوی ربات در $APP_DIR پیدا نشد."
  exit 1
fi

stop_old_pollers() {
  systemctl stop sanashop-bot 2>/dev/null || true
  pkill -TERM -f "$APP_DIR/external_bot(_v[0-9]+)?\.py" 2>/dev/null || true
  sleep 2
  pkill -KILL -f "$APP_DIR/external_bot(_v[0-9]+)?\.py" 2>/dev/null || true
}

apt-get update
apt-get install -y ca-certificates git python3 python3-venv procps
stop_old_pollers

cd "$APP_DIR"
git remote set-url origin "$REPO_URL"
git fetch origin main
git reset --hard origin/main

# Verify the checked-out code really includes the production gallery menus.
grep -q 'BOT_FEATURE_VERSION = "SanaShop multi-site / product-gallery-v18"' external_bot_v16.py || {
  echo "❌ نسخه جدید گالری در فایل ربات موجود نیست."; exit 1;
}
grep -q 'prod_gallery_v17' external_bot_v15.py || {
  echo "❌ دکمه گالری در منوی محصول موجود نیست."; exit 1;
}
grep -q 'galleries_v18' external_bot_plus.py || {
  echo "❌ ورودی گالری در پنل سایت‌ها موجود نیست."; exit 1;
}

if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
fi
.venv/bin/pip install --upgrade pip
.venv/bin/pip install python-telegram-bot==22.3 httpx==0.28.1
.venv/bin/python -m py_compile external_bot_v16.py external_bot_v15.py external_bot_gallery.py
install -d -m 700 /var/lib/sanashop-bot
rm -f /var/lib/sanashop-bot/runtime.lock

cat > /etc/systemd/system/sanashop-bot.service <<EOF
[Unit]
Description=SanaShop Multi-site Telegram Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$APP_DIR
EnvironmentFile=/etc/sanashop-bot.env
ExecStart=$APP_DIR/.venv/bin/python $APP_DIR/external_bot_v16.py
Restart=always
RestartSec=3
User=root
UMask=0077

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable sanashop-bot >/dev/null 2>&1 || true
systemctl restart sanashop-bot
sleep 4

if ! systemctl is-active --quiet sanashop-bot; then
  echo "❌ ربات بعد از آپدیت بالا نیامد."
  journalctl -u sanashop-bot -n 120 --no-pager
  exit 1
fi

SERVICE_PID="$(systemctl show -p MainPID --value sanashop-bot)"
if [[ ! "$SERVICE_PID" =~ ^[1-9][0-9]*$ || ! -r "/proc/$SERVICE_PID/cmdline" ]]; then
  echo "❌ پردازش فعال ربات قابل شناسایی نیست."
  exit 1
fi
ACTIVE_COMMAND="$(tr '\0' ' ' < "/proc/$SERVICE_PID/cmdline")"
if [[ "$ACTIVE_COMMAND" != *"$APP_DIR/external_bot_v16.py"* ]]; then
  echo "❌ سرویس از مسیر سورس جدید ربات چندسایتی اجرا نمی‌شود."
  echo "فرمان سرویس: $ACTIVE_COMMAND"
  exit 1
fi

BOT_PROCESSES="$(pgrep -fc "$APP_DIR/external_bot(_v[0-9]+)?\.py" || true)"
if [[ "$BOT_PROCESSES" -gt 1 ]]; then
  echo "❌ بیش از یک پردازش SanaShop bot روی این سرور پیدا شد."
  pgrep -af "$APP_DIR/external_bot(_v[0-9]+)?\.py" || true
  exit 1
fi

echo "✅ ربات چندسایتی با گالری محصولات (product-gallery-v18) آپدیت شد."
echo "🔖 کامیت سرور خارج: $(git rev-parse --short HEAD)"
echo "✅ برنامه فعال: $ACTIVE_COMMAND"
echo "🧪 در تلگرام /version را بفرست تا نسخه در حال اجرای ربات مشخص شود."
echo "✅ حذف کامل دسته و تعویض مطمئن عکس دسته فعال است."
echo "✅ قیمت اصلی، تخفیف و شگفت‌انگیز مستقل مدیریت می‌شوند."
echo "✅ دکمه‌ها با پردازش هم‌زمان و connection pool بزرگ‌تر سریع پاسخ می‌دهند."
echo "✅ اتصال‌های ذخیره‌شده، مدیرها و API Keyها در /var/lib/sanashop-bot حفظ شده‌اند."
echo "وضعیت: systemctl status sanashop-bot --no-pager"
echo "لاگ:    journalctl -u sanashop-bot -f"
