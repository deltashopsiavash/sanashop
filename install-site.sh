#!/usr/bin/env bash
set -Eeuo pipefail

REPO_URL="${SANASHOP_REPO_URL:-https://github.com/deltashopsiavash/sanashop.git}"
APP_DIR="${SANASHOP_DIR:-/opt/sanashop}"

if [[ ${EUID} -ne 0 ]]; then
  echo "این دستور باید با sudo/root اجرا شود."
  exit 1
fi

# Predeclare variables so set -u never trips on interactive defaults.
DOMAIN="${DOMAIN:-}"
ACME_EMAIL="${ACME_EMAIL:-}"
DEFAULT_SITE_NAME="${DEFAULT_SITE_NAME:-}"
DEFAULT_CARD_NUMBER="${DEFAULT_CARD_NUMBER:-}"
DEFAULT_CARD_OWNER="${DEFAULT_CARD_OWNER:-}"
ZARINPAL_MERCHANT_ID="${ZARINPAL_MERCHANT_ID:-}"
DJANGO_SUPERUSER_USERNAME="${DJANGO_SUPERUSER_USERNAME:-}"
DJANGO_SUPERUSER_PASSWORD="${DJANGO_SUPERUSER_PASSWORD:-}"
SMTP_HOST="${SMTP_HOST:-}"
SMTP_PORT="${SMTP_PORT:-}"
SMTP_USER="${SMTP_USER:-}"
SMTP_PASSWORD="${SMTP_PASSWORD:-}"
DEFAULT_FROM_EMAIL="${DEFAULT_FROM_EMAIL:-}"

read_value() {
  local key="$1" prompt="$2" default="${3:-}" secret="${4:-0}" current value
  current="${!key:-}"
  value="$current"
  if [[ -z "$value" ]]; then
    if [[ -r /dev/tty ]]; then
      if [[ "$secret" == "1" ]]; then
        read -r -s -p "$prompt" value < /dev/tty
        echo > /dev/tty
      else
        read -r -p "$prompt" value < /dev/tty
      fi
    fi
  fi
  value="${value:-$default}"
  printf -v "$key" '%s' "$value"
}

read_value DOMAIN "دامنه سایت بدون https:// : "
read_value ACME_EMAIL "ایمیل SSL: "
read_value DEFAULT_SITE_NAME "نام فروشگاه [سنا]: " "سنا"
read_value DEFAULT_CARD_NUMBER "شماره کارت (اختیاری): "
read_value DEFAULT_CARD_OWNER "نام صاحب کارت (اختیاری): "
read_value ZARINPAL_MERCHANT_ID "مرچنت زرین‌پال (اختیاری): "
read_value DJANGO_SUPERUSER_USERNAME "نام کاربری پنل [admin]: " "admin"
read_value DJANGO_SUPERUSER_PASSWORD "رمز پنل وب: " "" 1
read_value SMTP_HOST "SMTP Host: "
read_value SMTP_PORT "SMTP Port [587]: " "587"
read_value SMTP_USER "SMTP username: " "$ACME_EMAIL"
read_value SMTP_PASSWORD "SMTP password/App Password: " "" 1
read_value DEFAULT_FROM_EMAIL "ایمیل فرستنده: " "$ACME_EMAIL"

if [[ -z "$DOMAIN" || -z "$ACME_EMAIL" || -z "$DJANGO_SUPERUSER_PASSWORD" || -z "$SMTP_HOST" || -z "$SMTP_USER" || -z "$SMTP_PASSWORD" ]]; then
  echo "فیلدهای الزامی کامل نیستند."
  exit 1
fi

if [[ ! "$DOMAIN" =~ ^[A-Za-z0-9.-]+$ ]]; then
  echo "دامنه معتبر نیست؛ فقط نام دامنه را بدون http/https یا مسیر وارد کنید."
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
  echo "$APP_DIR از قبل وجود دارد. چون نصب قبلی قبل از clone متوقف شده بود، اگر این مسیر واقعاً خالی/نامربوط نیست آن را بررسی کنید."
  exit 1
fi

git clone --depth 1 "$REPO_URL" "$APP_DIR"
cd "$APP_DIR"

DB_PASSWORD="$(openssl rand -hex 24)"
DJANGO_SECRET_KEY="$(openssl rand -base64 48 | tr -d '\n')"
SANASHOP_BOT_API_KEY="$(openssl rand -hex 32)"

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
SANASHOP_BOT_API_KEY=$SANASHOP_BOT_API_KEY
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

docker compose up -d --build db web caddy

echo
echo "✅ سایت نصب شد: https://$DOMAIN"
echo "پنل: https://$DOMAIN/admin/"
echo
echo "🔑 کلید اتصال ربات (ذخیره کن):"
echo "$SANASHOP_BOT_API_KEY"
echo
echo "در ربات خارج: اتصال سایت → https://$DOMAIN → همین کلید"
