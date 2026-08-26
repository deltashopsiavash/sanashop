#!/usr/bin/env bash
set -Eeuo pipefail
if [[ ${EUID} -ne 0 ]]; then echo "Run with sudo/root"; exit 1; fi
APP_DIR=/opt/sanashop-bot
REPO_URL=https://github.com/deltashopsiavash/sanashop.git
read -r -p "Telegram bot token: " TELEGRAM_BOT_TOKEN
read -r -p "Owner numeric Telegram ID: " TELEGRAM_OWNER_ID
if [[ -z "$TELEGRAM_BOT_TOKEN" || -z "$TELEGRAM_OWNER_ID" ]]; then echo "Token and owner ID are required"; exit 1; fi
apt-get update
apt-get install -y ca-certificates git python3 python3-venv
rm -rf "$APP_DIR"
git clone --depth 1 "$REPO_URL" "$APP_DIR"
cd "$APP_DIR"
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install python-telegram-bot==22.3 httpx==0.28.1
mkdir -p /var/lib/sanashop-bot
cat > /etc/sanashop-bot.env <<EOF
TELEGRAM_BOT_TOKEN=$TELEGRAM_BOT_TOKEN
TELEGRAM_OWNER_ID=$TELEGRAM_OWNER_ID
BOT_DB_PATH=/var/lib/sanashop-bot/bot.sqlite3
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
ExecStart=$APP_DIR/.venv/bin/python $APP_DIR/external_bot.py
Restart=always
RestartSec=3
User=root

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now sanashop-bot
sleep 2
systemctl --no-pager --full status sanashop-bot || true
echo "Bot installed. Use: journalctl -u sanashop-bot -f"
