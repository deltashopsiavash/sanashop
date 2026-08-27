#!/usr/bin/env bash
set -Eeuo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "این دستور باید با sudo/root اجرا شود."
  exit 1
fi

APP_DIR="/opt/sanashop-bot"
REPO_URL="https://github.com/deltashopsiavash/sanashop.git"
TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
TELEGRAM_OWNER_ID="${TELEGRAM_OWNER_ID:-}"

read_tty() {
  local prompt="$1" var_name="$2" secret="${3:-0}" value="${!2:-}"
  if [[ -z "$value" ]]; then
    if [[ ! -r /dev/tty ]]; then
      echo "ترمینال تعاملی در دسترس نیست."
      exit 1
    fi
    if [[ "$secret" == "1" ]]; then
      read -r -s -p "$prompt" value < /dev/tty
      echo > /dev/tty
    else
      read -r -p "$prompt" value < /dev/tty
    fi
  fi
  printf -v "$var_name" '%s' "$value"
}

read_tty "Telegram bot token: " TELEGRAM_BOT_TOKEN 1
read_tty "Owner numeric Telegram ID: " TELEGRAM_OWNER_ID

if [[ -z "$TELEGRAM_BOT_TOKEN" || -z "$TELEGRAM_OWNER_ID" ]]; then
  echo "توکن و آیدی مالک الزامی هستند."
  exit 1
fi
if [[ ! "$TELEGRAM_OWNER_ID" =~ ^[0-9]+$ ]]; then
  echo "آیدی مالک باید فقط عدد باشد."
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl git python3 python3-venv procps

if ! curl -fsS --max-time 15 "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getMe" | grep -q '"ok":true'; then
  echo "❌ توکن ربات معتبر نیست یا این سرور به Telegram API دسترسی ندارد."
  exit 1
fi

systemctl disable --now sanashop-bot 2>/dev/null || true
pkill -TERM -f "$APP_DIR/external_bot(_v[0-9]+)?\.py" 2>/dev/null || true
sleep 2
pkill -KILL -f "$APP_DIR/external_bot(_v[0-9]+)?\.py" 2>/dev/null || true
rm -rf "$APP_DIR"
git clone --depth 1 "$REPO_URL" "$APP_DIR"
cd "$APP_DIR"
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install python-telegram-bot==22.3 httpx==0.28.1
install -d -m 700 /var/lib/sanashop-bot
rm -f /var/lib/sanashop-bot/runtime.lock

cat > /etc/sanashop-bot.env <<EOF
TELEGRAM_BOT_TOKEN=$TELEGRAM_BOT_TOKEN
TELEGRAM_OWNER_ID=$TELEGRAM_OWNER_ID
BOT_DB_PATH=/var/lib/sanashop-bot/bot.sqlite3
BOT_LOCK_PATH=/var/lib/sanashop-bot/runtime.lock
EOF
chmod 600 /etc/sanashop-bot.env

cat > /etc/systemd/system/sanashop-bot.service <<EOF
[Unit]
Description=SanaShop Multi-site Telegram Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$APP_DIR
EnvironmentFile=/etc/sanashop-bot.env
ExecStart=$APP_DIR/.venv/bin/python $APP_DIR/external_bot_v11.py
Restart=always
RestartSec=3
User=root
UMask=0077

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now sanashop-bot
sleep 4
if ! systemctl is-active --quiet sanashop-bot; then
  echo "❌ سرویس ربات بالا نیامد."
  journalctl -u sanashop-bot -n 100 --no-pager
  exit 1
fi

echo
echo "✅ ربات خارجی v11 نصب و اتصال Telegram تست شد."
echo "✅ اجرای هم‌زمان بیش از یک نمونه روی همین سرور مسدود است."
echo "✅ اتصال سایت‌ها دارای keep-alive، retry و backoff خودکار است."
echo "وضعیت: systemctl status sanashop-bot"
echo "لاگ:    journalctl -u sanashop-bot -f"
