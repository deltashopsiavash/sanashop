#!/usr/bin/env bash
set -Eeuo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "این دستور باید با sudo/root اجرا شود."
  exit 1
fi

echo "SanaShop اکنون سایت ایران و ربات خارجی را جدا نصب می‌کند."
echo "در حال اجرای نصب‌کننده سایت ایران..."
exec bash <(curl -fsSL https://raw.githubusercontent.com/deltashopsiavash/sanashop/main/install-site.sh)
