#!/usr/bin/env bash
set -Eeuo pipefail

REPO_URL="${SANASHOP_REPO_URL:-https://github.com/deltashopsiavash/sanashop.git}"
APP_DIR="${SANASHOP_DIR:-/opt/sanashop}"

if [[ ${EUID} -ne 0 ]]; then
  echo "این دستور باید با sudo/root اجرا شود."
  exit 1
fi

DOMAIN="${DOMAIN:-}"
ACME_EMAIL="${ACME_EMAIL:-}"
DEFAULT_SITE_NAME="${DEFAULT_SITE_NAME:-}"
DEFAULT_CARD_NUMBER="${DEFAULT_CARD_NUMBER:-}"
DEFAULT_CARD_OWNER="${DEFAULT_CARD_OWNER:-}"
ZARINPAL_MERCHANT_ID="${ZARINPAL_MERCHANT_ID:-}"
DJANGO_SUPERUSER_USERNAME="${DJANGO_SUPERUSER_USERNAME:-}"
DJANGO_SUPERUSER_PASSWORD="${DJANGO_SUPERUSER_PASSWORD:-}"
RESEND_DOMAIN="${RESEND_DOMAIN:-}"
RESEND_API_KEY="${RESEND_API_KEY:-}"
RESEND_FROM_EMAIL="${RESEND_FROM_EMAIL:-}"

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
read_value ACME_EMAIL "ایمیل SSL: "
read_value DEFAULT_SITE_NAME "نام فروشگاه [سنا]: " "سنا"
read_value DEFAULT_CARD_NUMBER "شماره کارت (اختیاری): "
read_value DEFAULT_CARD_OWNER "نام صاحب کارت (اختیاری): "
read_value ZARINPAL_MERCHANT_ID "مرچنت زرین‌پال (اختیاری): "
read_value DJANGO_SUPERUSER_USERNAME "نام کاربری پنل [admin]: " "admin"
read_value DJANGO_SUPERUSER_PASSWORD "رمز پنل وب: " "" 1

echo
echo "📧 تنظیم ایمیل تراکنشی با Resend"
echo "قبل از ادامه، دامنه ارسال را در Resend اضافه و DNS آن را در Cloudflare تا وضعیت Verified تنظیم کن."
read_value RESEND_DOMAIN "دامنه تأییدشده Resend [mail.$DOMAIN]: " "mail.$DOMAIN"
read_value RESEND_API_KEY "Resend API Key (re_...): " "" 1
read_value RESEND_FROM_EMAIL "آدرس فرستنده [support@$RESEND_DOMAIN]: " "support@$RESEND_DOMAIN"

if [[ -z "$DOMAIN" || -z "$ACME_EMAIL" || -z "$DJANGO_SUPERUSER_PASSWORD" || -z "$RESEND_DOMAIN" || -z "$RESEND_API_KEY" || -z "$RESEND_FROM_EMAIL" ]]; then
  echo "فیلدهای الزامی کامل نیستند."
  exit 1
fi
if [[ ! "$DOMAIN" =~ ^[A-Za-z0-9.-]+$ ]]; then
  echo "دامنه معتبر نیست؛ فقط نام دامنه را بدون http/https یا مسیر وارد کنید."
  exit 1
fi
if [[ ! "$RESEND_DOMAIN" =~ ^[A-Za-z0-9.-]+$ ]]; then
  echo "دامنه Resend معتبر نیست. نمونه صحیح: mail.example.com"
  exit 1
fi
if [[ ! "$RESEND_FROM_EMAIL" =~ ^[^[:space:]@]+@[^[:space:]@]+$ ]]; then
  echo "آدرس فرستنده معتبر نیست. نمونه صحیح: support@mail.example.com"
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl git openssl

echo "✅ اطلاعات دامنه و Resend دریافت شد؛ بررسی اجباری A/AAAA انجام نمی‌شود."

if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker

if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
  ufw allow 80/tcp >/dev/null || true
  ufw allow 443/tcp >/dev/null || true
fi

# Removing /opt/sanashop does NOT remove Docker named volumes. Without this guard,
# a user asking for a completely fresh install could silently get the previous
# database and media back, including old product/category/logo images.
if [[ ! -e "$APP_DIR" ]]; then
  stale_volumes=()
  for volume in sanashop_postgres_data sanashop_media_data sanashop_static_data sanashop_caddy_data sanashop_caddy_config; do
    if docker volume inspect "$volume" >/dev/null 2>&1; then
      stale_volumes+=("$volume")
    fi
  done
  if (( ${#stale_volumes[@]} > 0 )); then
    echo
    echo "⚠️ داده‌های Docker از نصب قبلی SanaShop پیدا شد:"
    printf '  - %s\n' "${stale_volumes[@]}"
    echo "اگر ادامه بدهیم بدون پاکسازی، دیتابیس و عکس‌های قدیمی دوباره استفاده می‌شوند."
    confirm=""
    if [[ "${SANASHOP_FRESH_WIPE:-0}" == "1" ]]; then
      confirm="DELETE"
    elif [[ -r /dev/tty ]]; then
      read -r -p "برای نصب واقعاً خام و حذف کامل داده‌های قبلی، دقیقاً DELETE را بنویسید؛ برای توقف Enter بزنید: " confirm < /dev/tty || true
    fi
    if [[ "$confirm" != "DELETE" ]]; then
      echo "نصب متوقف شد و هیچ volume قدیمی پاک نشد."
      exit 1
    fi
    old_containers="$(docker ps -aq --filter label=com.docker.compose.project=sanashop || true)"
    if [[ -n "$old_containers" ]]; then
      docker rm -f $old_containers >/dev/null 2>&1 || true
    fi
    for volume in "${stale_volumes[@]}"; do
      docker volume rm -f "$volume" >/dev/null
    done
    echo "✅ دیتابیس، media، static و داده Caddy نصب قبلی پاک شدند؛ نصب واقعاً خام ادامه پیدا می‌کند."
  fi
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
SMTP_HOST=smtp.resend.com
SMTP_PORT=587
SMTP_USER=resend
SMTP_PASSWORD=$RESEND_API_KEY
SMTP_USE_TLS=1
DEFAULT_FROM_EMAIL="$DEFAULT_SITE_NAME <$RESEND_FROM_EMAIL>"
EOF
chmod 600 .env
printf '%s\n' "$SANASHOP_BOT_API_KEY" > /root/sanashop-bot-api-key.txt
chmod 600 /root/sanashop-bot-api-key.txt
ln -sf "$APP_DIR/scripts/sanashop" /usr/local/bin/sanashop

echo
echo "🔑 کلید اتصال ربات ساخته شد و ذخیره شد:"
echo "$SANASHOP_BOT_API_KEY"
echo "بازیابی بعدی: sudo sanashop bot-key"
echo "فایل پشتیبان کلید: /root/sanashop-bot-api-key.txt"
echo

echo "در حال بررسی تنظیم Caddy..."
docker compose run --rm --no-deps -T caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile </dev/null

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
echo "✅ ایمیل سایت روی Resend تنظیم شد: $RESEND_FROM_EMAIL"
echo "🌐 سایت: https://$DOMAIN"
echo "👤 پنل وب: https://$DOMAIN/admin/"
echo "🔐 API مدیریت با کلید اختصاصی SANASHOP_BOT_API_KEY محافظت می‌شود."
echo
echo "🔑 کلید اتصال ربات:"
echo "$SANASHOP_BOT_API_KEY"
echo "برای دیدن دوباره: sudo sanashop bot-key"
echo
echo "اگر SSL یا DNS هنوز آماده نباشد، وضعیت Caddy را با این دستور ببین:"
echo "cd $APP_DIR && docker compose logs -f caddy"
