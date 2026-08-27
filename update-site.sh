#!/usr/bin/env bash
set -Eeuo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "این دستور باید با sudo/root اجرا شود."
  exit 1
fi

APP_DIR="${SANASHOP_DIR:-/opt/sanashop}"
REPO_URL="https://github.com/deltashopsiavash/sanashop.git"

if [[ ! -d "$APP_DIR/.git" || ! -f "$APP_DIR/.env" ]]; then
  echo "❌ نصب SanaShop در $APP_DIR پیدا نشد. ابتدا install-site.sh را اجرا کنید."
  exit 1
fi

command -v docker >/dev/null 2>&1 || { echo "❌ Docker نصب نیست."; exit 1; }

cd "$APP_DIR"
OLD_COMMIT="$(git rev-parse HEAD)"

echo "[1/9] دریافت آخرین نسخه از GitHub..."
git remote set-url origin "$REPO_URL"
git fetch --prune origin main
git reset --hard origin/main
printf '%s\n' "$OLD_COMMIT" > .last-version
ln -sf "$APP_DIR/scripts/sanashop" /usr/local/bin/sanashop

echo "[2/9] ساخت مجدد image سایت..."
docker compose build --pull --no-cache web

echo "[3/9] بالا آوردن دیتابیس..."
docker compose up -d db

echo "[4/9] بازسازی web و Caddy..."
docker compose up -d --force-recreate --remove-orphans web caddy

echo "[5/9] بررسی و اعمال migrationهای دیتابیس..."
docker compose exec -T web python manage.py migrate --noinput --verbosity 0
echo "✅ دیتابیس آماده است."

echo "[6/9] بروزرسانی فایل‌های static..."
docker compose exec -T web python manage.py collectstatic --noinput --clear --verbosity 0
echo "✅ فایل‌های static آماده‌اند."

echo "[7/9] بررسی سلامت Django..."
docker compose exec -T web python manage.py check

echo "[8/9] اعتبارسنجی Caddy..."
docker compose exec -T caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile

echo "[9/9] راه‌اندازی مجدد Caddy..."
docker compose restart caddy

echo
echo "✅ سایت ایران با موفقیت آپدیت شد."
echo "نسخه: $(git rev-parse --short HEAD)"
docker compose ps
