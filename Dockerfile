FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

# Iranian PyPI mirrors first: PyPI itself is often unreachable from Iranian VPSs.
# Override the first mirror using: docker compose build --build-arg PIP_PRIMARY_INDEX_URL=https://... web
ARG PIP_PRIMARY_INDEX_URL=https://mirror.novin.cloud/artifactory/api/pypi/pypi/simple/
ARG PIP_FALLBACK_INDEX_URLS="https://package-mirror.liara.ir/repository/pypi/simple https://mirror-pypi.runflare.com/simple https://mirrors.aliyun.com/pypi/simple/ https://pypi.org/simple/"
COPY requirements.txt .
RUN set -eu; \
    for index in "$PIP_PRIMARY_INDEX_URL" $PIP_FALLBACK_INDEX_URLS; do \
        [ -n "$index" ] || continue; \
        echo "Attempting Python dependencies using index: $index"; \
        if python -m pip install --no-cache-dir --prefer-binary --disable-pip-version-check \
            --timeout 25 --retries 1 --index-url "$index" -r requirements.txt; then \
            echo "Python dependencies installed successfully from $index"; \
            exit 0; \
        fi; \
        echo "PyPI mirror failed: $index; trying next mirror..." >&2; \
    done; \
    echo "ERROR: All configured PyPI mirrors failed; check outbound HTTPS/DNS on this server." >&2; \
    exit 1

COPY . .
RUN chmod +x docker/entrypoint.sh scripts/sanashop install.sh
ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "60", "--access-logfile", "-"]
