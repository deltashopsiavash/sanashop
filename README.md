# SanaShop

## نصب

### سرور ایران — سایت

```bash
curl -fsSL https://raw.githubusercontent.com/deltashopsiavash/sanashop/main/install-site.sh | sudo bash
```

### سرور خارج — ربات

```bash
curl -fsSL https://raw.githubusercontent.com/deltashopsiavash/sanashop/main/install-bot.sh | sudo bash
```

## تصاویر چندگانه محصولات (سایت ایران + ربات خارج)

نسخه‌های سایت و ربات باید هر دو آپدیت شوند؛ ابتدا **سایت ایران** و بعد **ربات خارج**.
فقط کدهای مربوط به گالری تغییر کرده‌اند؛ اطلاعات محصولات قبلی محفوظ است.

از پنل ربات: «محصولات» → انتخاب محصول → «گالری و عکس‌ها».
در این بخش می‌توانی تا ۲۰ عکس برای هر محصول اضافه کنی، هر عکس را ببینی،
جایگزین یا حذف کنی، توضیح تصویر را تغییر بدهی، جای تصویرها را عوض کنی
و هر عکس را به عنوان عکس اصلی انتخاب کنی. عکس اصلی روی کارت محصول در سایت
استفاده می‌شود و تصاویر دیگر در گالری صفحه محصول قابل انتخاب هستند.

در صورت حذف عکس اصلی، نخستین عکس گالری جای آن را می‌گیرد.
آپلود به‌صورت عکس تلگرامی یا فایل JPG/PNG/WEBP/GIF با حجم حداکثر ۱۰ مگابایت
پشتیبانی می‌شود. API گالری همان کلید Bearer قبلی سایت را استفاده می‌کند؛
نیازی به تنظیم کلید تازه نیست. بکاپ سایت نیز فایل‌های گالری را پوشش می‌دهد.

### ترتیب آپدیت سرورها

سرور ایران:

```bash
curl -fsSL https://raw.githubusercontent.com/deltashopsiavash/sanashop/main/update-site.sh | sudo bash
```

سرور خارج (پس از آپدیت سایت):

```bash
curl -fsSL https://raw.githubusercontent.com/deltashopsiavash/sanashop/main/update-bot.sh | sudo bash
```

هر دو اسکریپت اطلاعات موجود را حفظ می‌کنند؛ برای این قابلیت نصب خام
یا پاک‌کردن Volumeهای Docker و دیتابیس ربات لازم نیست.

## تشخیص نسخه فعال ربات چندسایتی

اگر دکمه گالری را نمی‌بینی، صرفاً آپدیت کردن سورس کافی نیست؛ باید
**پردازش فعالِ سرویس ربات خارج** نیز نسخه جدید را اجرا کند. پس از آپدیت
سایت ایران و بعد ربات خارج، در چت تلگرام با همان ربات این دستور را بفرست:

```text
/version
```

پاسخ صحیح باید `SanaShop multi-site / product-gallery-v18` باشد.
مدیر هر سایت وضعیت **فقط سایت خودش** را نیز می‌بیند.
برای دیدن دکمه تازه، `/start` را دوباره اجرا کن و وارد پنل سایت شو؛
در پنل هر سایت «🖼 گالری تصاویر محصولات» وجود دارد و داخل صفحه هر محصول
نیز «🖼 گالری و عکس‌ها» نمایش داده می‌شود.

اگر `/version` هیچ پاسخی نمی‌دهد، یا برچسب بالا دیده نمی‌شود،
وضعیت سرور **ربات خارج** را با این دستورات فقط برای تشخیص بررسی کن
(هیچ کلید API، فایل `.env` یا توکن تلگرام را به اشتراک نگذار):

```bash
cd /opt/sanashop-bot
git rev-parse --short HEAD
systemctl status sanashop-bot --no-pager
systemctl show -p MainPID -p ExecStart sanashop-bot
journalctl -u sanashop-bot -n 40 --no-pager
```

نسخه جدید `update-bot.sh` از وجود دکمه گالری در کد،
مسیر پردازش فعال و اجرای فایل `external_bot_v16.py` اطمینان می‌گیرد.
دیتابیس اختصاصی ربات (`/var/lib/sanashop-bot`) با آپدیت حذف نمی‌شود.

## آپدیت

### سرور ایران — سایت

```bash
curl -fsSL https://raw.githubusercontent.com/deltashopsiavash/sanashop/main/update-site.sh | sudo bash
```

### سرور خارج — ربات

```bash
curl -fsSL https://raw.githubusercontent.com/deltashopsiavash/sanashop/main/update-bot.sh | sudo bash
```

## Docker Hub 403 on Iranian servers

The Iranian site stack defaults to a Docker Hub mirror for **all three** Docker images:
Python, PostgreSQL, and Caddy. No Docker daemon configuration or Docker Hub login is needed.
Python packages also use mirrored PyPI repositories.

If Docker Hub returns `403 Forbidden` or `auth.docker.io/token` errors during an
existing installation, **do not delete `/opt/sanashop` or any Docker volumes**.
Recover without rerunning the installer:

```bash
cd /opt/sanashop
git fetch origin main
git restore --source=origin/main -- Dockerfile docker-compose.yml
docker compose up -d --build db web caddy
docker compose ps
```

On a new installation, the normal `install-site.sh` command uses the same mirror automatically.

If the default mirror cannot be reached from the server, choose another **trusted**
Docker registry mirror and override the three image references in your local
`/opt/sanashop/.env` (these variables are Compose image settings and must
point to complete image references):

```dotenv
SANASHOP_PYTHON_IMAGE=docker.arvancloud.ir/library/python:3.12-slim
SANASHOP_POSTGRES_IMAGE=docker.arvancloud.ir/library/postgres:16-alpine
SANASHOP_CADDY_IMAGE=docker.arvancloud.ir/library/caddy:2.10-alpine
```

Then run `docker compose up -d --build db web caddy`. This does **not** reset the
database, media files, the site domain, or API secrets. Image registries are a
supply-chain dependency; only select trusted mirror operators.


## Iran: install curl 403, contact/footer, Resend mail

`install-site.sh` itself only uses `curl` to install Docker when Docker is absent.
When `curl -fSL raw.githubusercontent.com` returns HTTP 403 **before the script starts**,
the failure comes from fetching the script. On a fresh server, bypass that bootstrap
request via a git clone:

```bash
sudo apt-get update && sudo apt-get install -y git
INSTALL_DIR="$(mktemp -d /root/sanashop-installer.XXXXXX)"
git clone --depth 1 https://github.com/deltashopsiavash/sanashop.git "$INSTALL_DIR"
sudo bash "$INSTALL_DIR/install-site.sh"
```

This command is for **fresh installations only**; do not rerun the installer
on `/opt/sanashop` if the previous run already created `.env` or started containers.

For image registry errors, distinguish Docker mirror failures from the initial
GitHub curl. After an installation attempt that created `/opt/sanashop`:

```bash
cd /opt/sanashop
docker compose config --images
docker compose ps
docker compose logs --tail=60 web caddy
```

The chosen `SANASHOP_POSTGRES_IMAGE`, `SANASHOP_CADDY_IMAGE`,
`SANASHOP_PYTHON_IMAGE` and `PIP_PRIMARY_INDEX_URL` are persisted into
the new site's `.env` so future updates use the same mirror.
Never delete Docker volumes to fix HTTP 403.

### Footer and phone

In the site footer, expand «راهنمای خرید و اطلاعات فروشگاه» to open
قوانین و مقررات, تماس با ما, سؤالات متداول.
The 3 pages are auto-created on migration only when missing and can be edited
in Django admin under Content pages. Pre-existing content is not replaced.
Both the `phone` and `contact_phone` Telegram setting update the same public
contact number used in footer, contact page and header, and an admin change
in SiteSetting syncs the same value.

### Resend email and verification codes

The domain in Resend must be **Verified** and the From address must be on that
exact verified domain, e.g. if `mail.example.com` is verified, use
`support@mail.example.com` as sender. Verification alone does not prove
that an Iranian server can reach Resend or that the API key permits sending.

New installs use Resend's HTTPS Email API on port 443, rather than outbound
SMTP port 587 that can be blocked by the VPS network.
The installer writes `EMAIL_PROVIDER=resend_api`, `RESEND_API_KEY`, and
`DEFAULT_FROM_EMAIL` to the site's private `.env`.
Existing installations stay on SMTP unless changed explicitly.

Run exactly one explicit test email after installation, substituting a
mailbox you control:

```bash
cd /opt/sanashop
docker compose exec -T web python manage.py test_store_email --to your-email@example.com
```

Check the recipient inbox/spam and the Resend Dashboard Emails/Logs: successful
API submission is **not** proof of final delivery.
If the test returns HTTP 403, inspect API key sending permissions and
Resend account restrictions; also test outbound HTTPS 443 from the Iranian
server. Do not share the API key or contents of `.env`.

If Resend HTTPS API is unreachable in your network, SMTP remains an explicit
fallback. In `.env` set:
```dotenv
EMAIL_PROVIDER=smtp
SMTP_HOST=smtp.resend.com
SMTP_PORT=465
SMTP_USER=resend
SMTP_USE_SSL=1
SMTP_USE_TLS=0
```
Keep `SMTP_PASSWORD` as the existing Resend API key, and restart only the
site web container using `docker compose up -d --no-deps web`.
Another SSL port is 2465 if outbound 465 is blocked. Resend SMTP authentication
uses username `resend` and a sending-permission API key.

DNS records such as SPF, DKIM, and bounce MX are for sender verification.
An email sender address is **not** automatically a receiving mailbox; use
a separate inbox provider if you need to receive support replies.
