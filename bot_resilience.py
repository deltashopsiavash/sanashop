import asyncio
import logging
import time

import httpx

logger = logging.getLogger(__name__)

_client = None
_failures = {}


def _http_client():
    global _client
    if _client is None or _client.is_closed:
        transport = httpx.AsyncHTTPTransport(retries=2)
        limits = httpx.Limits(
            max_connections=30,
            max_keepalive_connections=15,
            keepalive_expiry=90.0,
        )
        _client = httpx.AsyncClient(
            transport=transport,
            limits=limits,
            follow_redirects=True,
            headers={"User-Agent": "SanaShopBot/6"},
        )
    return _client


async def resilient_api(site, action, payload=None, timeout=25):
    """Call a SanaShop API without tearing down DNS/TLS state on every request."""
    url = site["base_url"].rstrip("/") + "/api/bot/v1/"
    client = _http_client()
    last_exc = None

    # User-triggered calls deserve a few quick retries. Event polling uses the same
    # function but its outer loop also backs off, so transient outages never remove a site.
    for attempt in range(3):
        try:
            request_timeout = httpx.Timeout(
                timeout=max(float(timeout), 10.0),
                connect=min(max(float(timeout), 10.0), 12.0),
            )
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {site['api_key']}"},
                json={"action": action, "payload": payload or {}},
                timeout=request_timeout,
            )

            if response.status_code in (502, 503, 504) and attempt < 2:
                await asyncio.sleep(1.0 + attempt * 1.5)
                continue

            if response.status_code == 401:
                raise RuntimeError("کلید اتصال سایت اشتباه است یا روی سایت تغییر کرده است.")
            if response.status_code == 403:
                raise RuntimeError("دسترسی API توسط پروکسی/Caddy رد شده است؛ نسخه سایت را به آخرین main آپدیت کنید.")
            if response.status_code == 404:
                raise RuntimeError("API مدیریت روی سایت پیدا نشد؛ نسخه سایت را بررسی کنید.")

            try:
                data = response.json()
            except Exception as exc:
                raise RuntimeError(f"پاسخ نامعتبر از سایت (HTTP {response.status_code}).") from exc

            if response.status_code >= 400 or not data.get("ok", False):
                raise RuntimeError(data.get("error") or f"HTTP {response.status_code}")
            return data

        except RuntimeError:
            raise
        except (httpx.ConnectTimeout, httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout) as exc:
            last_exc = exc
            logger.warning(
                "SanaShop API temporary network failure site=%s action=%s attempt=%s: %r",
                site.get("base_url") if hasattr(site, "get") else site["base_url"],
                action,
                attempt + 1,
                exc,
            )
            if attempt < 2:
                await asyncio.sleep(1.0 + attempt * 2.0)
                continue

    if isinstance(last_exc, httpx.ConnectTimeout):
        raise RuntimeError("اتصال به سایت موقتاً timeout شد؛ ربات ۳ بار تلاش کرد. سایت از ربات حذف نشده است.") from last_exc
    if isinstance(last_exc, httpx.ConnectError):
        raise RuntimeError("ارتباط شبکه/DNS با سایت موقتاً برقرار نشد؛ سایت از ربات حذف نشده است.") from last_exc
    raise RuntimeError("سایت موقتاً پاسخ نداد؛ اتصال ذخیره شده و ربات دوباره تلاش می‌کند.") from last_exc


async def resilient_notification_loop(application, core, plus):
    """Poll events without hammering an unhealthy site or mutating saved connections."""
    await asyncio.sleep(5)
    while True:
        now = time.monotonic()
        try:
            with core.db() as conn:
                sites = conn.execute("SELECT * FROM sites ORDER BY id").fetchall()

            for site in sites:
                sid = int(site["id"])
                state = _failures.get(sid, {"count": 0, "next": 0.0})
                if now < state["next"]:
                    continue

                try:
                    events = (await resilient_api(site, "events_poll", {"limit": 20}, timeout=18))["data"]
                    _failures.pop(sid, None)
                except Exception as exc:
                    count = int(state.get("count", 0)) + 1
                    delay = min(15 * (2 ** min(count - 1, 4)), 300)
                    _failures[sid] = {"count": count, "next": time.monotonic() + delay}
                    logger.warning(
                        "Event poll failed for site %s; retry in %ss; saved connection preserved: %s",
                        sid,
                        delay,
                        exc,
                    )
                    continue

                ack = []
                for event in events:
                    try:
                        if await plus.send_event(application, site, event):
                            ack.append(event["id"])
                    except Exception:
                        logger.exception("Could not deliver event %s for site %s", event.get("id"), sid)

                if ack:
                    try:
                        await resilient_api(site, "events_ack", {"ids": ack}, timeout=18)
                    except Exception:
                        logger.exception("Could not ack events for site %s", sid)
        except Exception:
            logger.exception("Resilient notification loop error")

        await asyncio.sleep(15)
