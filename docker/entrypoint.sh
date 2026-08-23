#!/usr/bin/env sh
set -eu
if [ "${1:-}" = "gunicorn" ]; then
  python manage.py migrate --noinput
  python manage.py collectstatic --noinput
  python manage.py bootstrap_shop
fi
exec "$@"

