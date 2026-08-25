#!/usr/bin/env bash
set -Eeuo pipefail

REPO_URL="${SANASHOP_REPO_URL:-https://github.com/deltashopsiavash/sanashop.git}"
APP_DIR="${SANASHOP_DIR:-/opt/sanashop}"

if [[ ${EUID} -ne 0 ]]; then
  echo "این دستور باید با sudo اجرا شود."
  exit 1
fi
if ! grep -qE 'Ubuntu 24\.04|Ubuntu 24' /etc/os-release 2>/dev/null; then
  echo "هشدار: این نصب‌کننده برای Ubuntu 24.04 تست شده است."
fi

read_value() {
  local key="$1" prompt="$2" default="${3:-}" secret="${4:-0}" value
  value="$(printenv "$key" 2>/dev/null || true)"
  if [[ -z "$value" ]] && tty -s 2>/dev/null < /dev/tty; then
    if [[ "$secret" == "1" ]]; then read -r -s -p "$prompt" value < /dev/tty; echo > /dev/tty; else read -r -p "$prompt" value < /dev/tty; fi
  fi
  value="${value:-$default}"
  printf -v "$key" '%s' "$value"
}

read_value DOMAIN "دامنه‌ای که DNS آن به این سرور وصل شده (مثال shop.example.com): "
read_value ACME_EMAIL "ایمیل برای گواهی SSL: "
read_value TELEGRAM_BOT_TOKEN "توکن ربات تلگرام: " "" 1
read_value TELEGRAM_ADMIN_IDS "آیدی عددی مدیر تلگرام: "
read_value TELEGRAM_PROXY_URL "پروکسی HTTP تلگرام (اختیاری، مثال http://user:pass@IP:3128): "
read_value DEFAULT_SITE_NAME "نام اولیه فروشگاه [سنا]: " "سنا"
read_value DEFAULT_CARD_NUMBER "شماره کارت (می‌توان بعداً از ربات تغییر داد): "
read_value DEFAULT_CARD_OWNER "نام صاحب کارت: "
read_value ZARINPAL_MERCHANT_ID "مرچنت زرین‌پال (اختیاری): "
read_value DJANGO_SUPERUSER_USERNAME "نام کاربری پنل وب [admin]: " "admin"
read_value DJANGO_SUPERUSER_PASSWORD "رمز پنل وب: " "" 1
read_value SMTP_HOST "آدرس SMTP ایمیل (مثال smtp.gmail.com): "
read_value SMTP_PORT "پورت SMTP [587]: " "587"
read_value SMTP_USER "نام کاربری SMTP (معمولاً ایمیل): " "$ACME_EMAIL"
read_value SMTP_PASSWORD "رمز SMTP یا App Password: " "" 1
read_value DEFAULT_FROM_EMAIL "ایمیل فرستنده ثبت‌نام و بازیابی: " "$ACME_EMAIL"

if [[ -z "$DOMAIN" || -z "$ACME_EMAIL" || -z "$TELEGRAM_BOT_TOKEN" || -z "$TELEGRAM_ADMIN_IDS" || -z "$DJANGO_SUPERUSER_PASSWORD" || -z "$SMTP_HOST" || -z "$SMTP_USER" || -z "$SMTP_PASSWORD" ]]; then
  echo "دامنه، ایمیل، توکن ربات، آیدی مدیر، رمز پنل و اطلاعات SMTP الزامی هستند."
  exit 1
fi
if [[ ! "$DOMAIN" =~ ^[A-Za-z0-9.-]+$ ]]; then
  echo "دامنه معتبر نیست؛ فقط نام دامنه را بدون http یا مسیر وارد کنید."
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl git openssl
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker

if [[ -e "$APP_DIR" ]]; then
  echo "مسیر $APP_DIR از قبل وجود دارد؛ برای آپدیت از sudo sanashop update استفاده کنید."
  exit 1
fi
git clone --depth 1 "$REPO_URL" "$APP_DIR"
cd "$APP_DIR"

DB_PASSWORD="$(openssl rand -hex 24)"
DJANGO_SECRET_KEY="$(openssl rand -base64 48 | tr -d '\n')"
cat > .env <<EOF
DOMAIN=$DOMAIN
ACME_EMAIL=$ACME_EMAIL
DJANGO_SECRET_KEY=$DJANGO_SECRET_KEY
DJANGO_DEBUG=0
DJANGO_ALLOWED_HOSTS=$DOMAIN,localhost,127.0.0.1
CSRF_TRUSTED_ORIGINS=https://$DOMAIN
POSTGRES_DB=sanashop
POSTGRES_USER=sanashop
POSTGRES_PASSWORD=$DB_PASSWORD
DATABASE_URL=postgresql://sanashop:$DB_PASSWORD@db:5432/sanashop
TELEGRAM_BOT_TOKEN=$TELEGRAM_BOT_TOKEN
TELEGRAM_ADMIN_IDS=$TELEGRAM_ADMIN_IDS
TELEGRAM_PROXY_URL=$TELEGRAM_PROXY_URL
ZARINPAL_MERCHANT_ID=$ZARINPAL_MERCHANT_ID
ZARINPAL_SANDBOX=0
DEFAULT_SITE_NAME=$DEFAULT_SITE_NAME
DEFAULT_CARD_NUMBER=$DEFAULT_CARD_NUMBER
DEFAULT_CARD_OWNER=$DEFAULT_CARD_OWNER
DJANGO_SUPERUSER_USERNAME=$DJANGO_SUPERUSER_USERNAME
DJANGO_SUPERUSER_PASSWORD=$DJANGO_SUPERUSER_PASSWORD
DJANGO_SUPERUSER_EMAIL=$ACME_EMAIL
SMTP_HOST=$SMTP_HOST
SMTP_PORT=$SMTP_PORT
SMTP_USER=$SMTP_USER
SMTP_PASSWORD=$SMTP_PASSWORD
SMTP_USE_TLS=1
DEFAULT_FROM_EMAIL=$DEFAULT_FROM_EMAIL
EOF
chmod 600 .env
ln -sf "$APP_DIR/scripts/sanashop" /usr/local/bin/sanashop
docker compose up -d --build
echo
echo "نصب کامل شد: https://$DOMAIN"
echo "پنل وب: https://$DOMAIN/admin/"
echo "برای آپدیت‌های بعدی: sudo sanashop update"
