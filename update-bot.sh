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

if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
fi
.venv/bin/pip install --upgrade pip
.venv/bin/pip install python-telegram-bot==22.3 httpx==0.28.1
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
ExecStart=$APP_DIR/.venv/bin/python $APP_DIR/external_bot_v13.py
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

BOT_PROCESSES="$(pgrep -fc "$APP_DIR/external_bot(_v[0-9]+)?\.py" || true)"
if [[ "$BOT_PROCESSES" -gt 1 ]]; then
  echo "❌ بیش از یک پردازش SanaShop bot روی این سرور پیدا شد."
  pgrep -af "$APP_DIR/external_bot(_v[0-9]+)?\.py" || true
  exit 1
fi

echo "✅ ربات خارجی به نسخه v13 آپدیت شد."
echo "✅ خطای یک بخش دیگر اتصال ذخیره‌شده سایت را از پنل خارج نمی‌کند."
echo "✅ بکاپ روی نسخه قدیمی سایت پیام آپدیت می‌دهد و اتصال سایت حفظ می‌شود."
echo "✅ اتصال‌های ذخیره‌شده، مدیرها و API Keyها در /var/lib/sanashop-bot حفظ شده‌اند."
echo "وضعیت: systemctl status sanashop-bot --no-pager"
echo "لاگ:    journalctl -u sanashop-bot -f"
