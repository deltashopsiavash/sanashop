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
