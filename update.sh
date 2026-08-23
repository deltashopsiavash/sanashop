#!/usr/bin/env bash
set -Eeuo pipefail

REPO_URL="${SANASHOP_REPO_URL:-https://github.com/deltashopsiavash/sanashop.git}"
BRANCH="${SANASHOP_BRANCH:-main}"
APP_DIR="${SANASHOP_DIR:-/opt/sanashop}"

say() { printf '\n\033[1;36m[SanaShop]\033[0m %s\n' "$*"; }
fail() { printf '\n\033[1;31m[ERROR]\033[0m %s\n' "$*" >&2; exit 1; }

[[ ${EUID} -eq 0 ]] || fail "این دستور باید با sudo/root اجرا شود."
command -v docker >/dev/null 2>&1 || fail "Docker نصب نیست. ابتدا install.sh را اجرا کنید."
docker compose version >/dev/null 2>&1 || fail "Docker Compose در دسترس نیست."

# نصب ابزارهای سبک مورد نیاز فقط در صورت نبودن آنها
NEED_PKGS=()
command -v git >/dev/null 2>&1 || NEED_PKGS+=(git)
command -v rsync >/dev/null 2>&1 || NEED_PKGS+=(rsync)
command -v curl >/dev/null 2>&1 || NEED_PKGS+=(curl)
if ((${#NEED_PKGS[@]})); then
  say "نصب ابزارهای موردنیاز: ${NEED_PKGS[*]}"
  apt-get update
  apt-get install -y ca-certificates "${NEED_PKGS[@]}"
fi

[[ -d "$APP_DIR" ]] || fail "مسیر $APP_DIR وجود ندارد. این اسکریپت برای آپدیت نصب موجود است."
[[ -f "$APP_DIR/.env" ]] || fail "فایل $APP_DIR/.env پیدا نشد؛ برای جلوگیری از حذف تنظیمات، آپدیت متوقف شد."

cd "$APP_DIR"
STAMP="$(date +%Y%m%d-%H%M%S)"
mkdir -p .update-backups
cp -a .env ".update-backups/env-$STAMP"
chmod 600 ".update-backups/env-$STAMP" || true

OLD_COMMIT=""
if [[ -d .git ]] && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  OLD_COMMIT="$(git rev-parse HEAD 2>/dev/null || true)"
  say "ریپو Git شناسایی شد؛ دریافت آخرین نسخه از $BRANCH"

  if git remote get-url origin >/dev/null 2>&1; then
    git remote set-url origin "$REPO_URL"
  else
    git remote add origin "$REPO_URL"
  fi

  git fetch --prune origin "$BRANCH"
  [[ -z "$OLD_COMMIT" ]] || printf '%s\n' "$OLD_COMMIT" > .last-version
  git reset --hard "origin/$BRANCH"
  # فایل‌های محلی حساس/عملیاتی را حذف نکن.
  git clean -fd -e .env -e backups/ -e .update-backups/ -e .last-version
else
  say "این نصب Git metadata ندارد (احتمالاً سورس دستی کپی شده). در حال تبدیل امن به نصب متصل به GitHub..."
  TMP_DIR="$(mktemp -d)"
  trap 'rm -rf "${TMP_DIR:-}"' EXIT
  git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$TMP_DIR/repo"

  # سورس را کامل با GitHub همگام می‌کنیم، ولی تنظیمات و بکاپ‌های سرور حفظ می‌شوند.
  rsync -a --delete \
    --exclude='.env' \
    --exclude='backups/' \
    --exclude='.update-backups/' \
    --exclude='.last-version' \
    "$TMP_DIR/repo/" "$APP_DIR/"
fi

cd "$APP_DIR"
chmod +x install.sh update.sh scripts/sanashop docker/entrypoint.sh 2>/dev/null || true
ln -sfn "$APP_DIR/scripts/sanashop" /usr/local/bin/sanashop

say "ساخت نسخه جدید Docker"
docker compose build --pull

say "راه‌اندازی سرویس‌ها بدون حذف دیتابیس و فایل‌های آپلودی"
docker compose up -d --remove-orphans

say "اجرای migration و collectstatic"
docker compose exec -T web python manage.py migrate --noinput
docker compose exec -T web python manage.py collectstatic --noinput

NEW_COMMIT="$(git rev-parse HEAD 2>/dev/null || echo unknown)"
printf '%s\n' "$NEW_COMMIT" > .installed-version

say "وضعیت سرویس‌ها"
docker compose ps

printf '\n✅ SanaShop با موفقیت آپدیت شد.\n'
printf 'نسخه نصب‌شده: %s\n' "$NEW_COMMIT"
printf 'تنظیمات .env، دیتابیس PostgreSQL، تصاویر و بکاپ‌ها حفظ شدند.\n'
printf 'از این به بعد برای آپدیت فقط بزنید: sudo sanashop update\n'
