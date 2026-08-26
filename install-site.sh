#!/usr/bin/env bash
set -Eeuo pipefail

REPO_URL="${SANASHOP_REPO_URL:-https://github.com/deltashopsiavash/sanashop.git}"
APP_DIR="${SANASHOP_DIR:-/opt/sanashop}"

if [[ ${EUID} -ne 0 ]]; then
  echo "این دستور باید با sudo/root اجرا شود."
  exit 1
fi

DOMAIN="${DOMAIN:-}"
BOT_SERVER_IP="${BOT_SERVER_IP:-}"
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
  value="${value:-$default}"
  printf -v "$key" '%s' "$value"
}

read_value DOMAIN "دامنه سایت بدون https:// : "
read_value BOT_SERVER_IP "IP عمومی سرور خارجی ربات: "
read_value ACME_EMAIL "ایمیل SSL: "
read_value DEFAULT_SITE_NAME "نام فروشگاه [سنا]: " "سنا"
read_value DEFAULT_CARD_NUMBER "شماره کارت (اختیاری): "
read_value DEFAULT_CARD_OWNER "نام صاحب کارت (اختیاری): "
read_value ZARINPAL_MERCHANT_ID "مرچنت زرین‌پال (اختیاری): "
read_value DJANGO_SUPERUSER_USERNAME "نام کاربری پنل [admin]: " "admin"
read_value DJANGO_SUPERUSER_PASSWORD "رمز پنل وب: " "" 1
read_value SMTP_HOST "SMTP Host (برای Gmail: smtp.gmail.com): "
read_value SMTP_PORT "SMTP Port [587]: " "587"
read_value SMTP_USER "SMTP username: " "$ACME_EMAIL"
read_value SMTP_PASSWORD "SMTP password/App Password: " "" 1
read_value DEFAULT_FROM_EMAIL "ایمیل فرستنده: " "$ACME_EMAIL"

if [[ -z "$DOMAIN" || -z "$BOT_SERVER_IP" || -z "$ACME_EMAIL" || -z "$DJANGO_SUPERUSER_PASSWORD" || -z "$SMTP_HOST" || -z "$SMTP_USER" || -z "$SMTP_PASSWORD" ]]; then
  echo "فیلدهای الزامی کامل نیستند."
  exit 1
fi
if [[ ! "$DOMAIN" =~ ^[A-Za-z0-9.-]+$ ]]; then
  echo "دامنه معتبر نیست؛ فقط نام دامنه را بدون http/https یا مسیر وارد کنید."
  exit 1
fi
if [[ ! "$BOT_SERVER_IP" =~ ^[0-9A-Fa-f:.]+$ ]]; then
  echo "IP سرور ربات معتبر نیست."
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl git openssl

# عمداً هیچ بررسی یا مقایسه‌ای بین DNS دامنه و IP عمومی سرور انجام نمی‌شود.
# دامنه می‌تواند پشت CDN/Proxy/DNS واسط باشد. Caddy در زمان اجرا وضعیت واقعی HTTPS را مدیریت می‌کند.
echo "✅ اطلاعات دامنه دریافت شد؛ بررسی اجباری A/AAAA انجام نمی‌شود."

if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker

if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
  ufw allow 80/tcp >/dev/null || true
  ufw allow 443/tcp >/dev/null || true
fi

if [[ -e "$APP_DIR" ]]; then
  echo "مسیر $APP_DIR از قبل وجود دارد. اگر نصب قبلی ناقص بوده و اطلاعاتی داخلش نداری، آن را حذف کن: rm -rf $APP_DIR"
  exit 1
fi

git clone --depth 1 "$REPO_URL" "$APP_DIR"
cd "$APP_DIR"

DB_PASSWORD="$(openssl rand -hex 24)"
DJANGO_SECRET_KEY="$(openssl rand -base64 48 | tr -d '\n')"
SANASHOP_BOT_API_KEY="$(openssl rand -hex 32)"

cat > .env <<EOF
DOMAIN=$DOMAIN
BOT_SERVER_IP=$BOT_SERVER_IP
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

echo "در حال بررسی تنظیم Caddy..."
docker compose run --rm --no-deps caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile

echo "در حال ساخت و اجرای سایت..."
docker compose up -d --build db web caddy

WEB_OK=0
for _ in $(seq 1 30); do
  if docker compose exec -T web curl -fsS http://127.0.0.1:8000/health/ >/dev/null 2>&1; then
    WEB_OK=1
    break
  fi
  sleep 2
done
if [[ "$WEB_OK" != "1" ]]; then
  echo "❌ سرویس Django سالم نشد."
  docker compose logs --tail=120 web
  exit 1
fi

API_OK=0
for _ in $(seq 1 10); do
  if docker compose exec -T web curl -fsS -X POST \
    -H "Authorization: Bearer $SANASHOP_BOT_API_KEY" \
    -H "Content-Type: application/json" \
    -d '{"action":"ping","payload":{}}' \
    http://127.0.0.1:8000/api/bot/v1/ | grep -q '"ok": true'; then
    API_OK=1
    break
  fi
  sleep 1
done
if [[ "$API_OK" != "1" ]]; then
  echo "❌ API داخلی سایت پاسخ صحیح نداد."
  docker compose logs --tail=120 web
  exit 1
fi

echo
echo "✅ نصب داخلی سایت و API با موفقیت تست شد."
echo "🌐 سایت: https://$DOMAIN"
echo "👤 پنل وب: https://$DOMAIN/admin/"
echo "🔒 API مدیریت فقط برای IP سرور ربات باز است: $BOT_SERVER_IP"
echo
echo "🔑 کلید اتصال ربات (این مقدار را در ربات وارد کن):"
echo "$SANASHOP_BOT_API_KEY"
echo
echo "اگر SSL یا DNS هنوز آماده نباشد، نصب متوقف نمی‌شود؛ وضعیت Caddy را با این دستور ببین:"
echo "cd $APP_DIR && docker compose logs -f caddy"
