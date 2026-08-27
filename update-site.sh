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
git remote set-url origin "$REPO_URL"
git fetch --prune origin main
git reset --hard origin/main
printf '%s\n' "$OLD_COMMIT" > .last-version
ln -sf "$APP_DIR/scripts/sanashop" /usr/local/bin/sanashop

docker compose build --pull --no-cache web
docker compose up -d db
docker compose up -d --force-recreate --remove-orphans web caddy

docker compose exec -T web python manage.py migrate --noinput
docker compose exec -T web python manage.py collectstatic --noinput --clear
docker compose exec -T web python manage.py check

docker compose exec -T caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
docker compose restart caddy

echo
echo "✅ سایت ایران با موفقیت آپدیت شد."
echo "نسخه: $(git rev-parse --short HEAD)"
docker compose ps
