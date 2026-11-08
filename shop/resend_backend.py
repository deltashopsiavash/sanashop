"""Django email backend for Resend HTTPS API, avoiding outbound SMTP port blocks.

Supports OTP, HTML password resets, and privacy-preserving BCC newsletters.
Never log authorization headers or recipient payloads.
"""
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend


class ResendDeliveryError(RuntimeError):
    """API/transport failure without leaking the credential."""


class ResendAPIEmailBackend(BaseEmailBackend):
    api_url = "https://api.resend.com/emails"

    def _post(self, url, payload):
        key = str(getattr(settings, "RESEND_API_KEY", "") or "").strip()
        if not key:
            raise ResendDeliveryError("Resend API key is missing. Check RESEND_API_KEY.")
        request = Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": "Bearer " + key,
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "SanaShop-Store/1.0",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=18) as response:
                data = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            try:
                response = json.loads(exc.read(2048).decode("utf-8"))
                detail = str(response.get("name") or response.get("error") or "request_rejected")[:100]
                # Do not print any response text or API credentials; use safe
                # diagnostics and the HTTP status for on-server troubleshooting.
                detail = "".join(ch for ch in detail if ch.isascii() and (ch.isalnum() or ch in "_-")) or "request_rejected"
            except Exception:
                detail = "request_rejected"
            raise ResendDeliveryError(f"Resend API rejected request (HTTP {exc.code}: {detail})") from None
        except (URLError, TimeoutError, OSError) as exc:
            raise ResendDeliveryError("Resend HTTPS connection failed; check server connectivity to api.resend.com:443") from exc
        except (ValueError, UnicodeError) as exc:
            raise ResendDeliveryError("Invalid JSON response from Resend") from exc
        if not isinstance(data, (dict, list)):
            raise ResendDeliveryError("Unexpected response from Resend API")
        if isinstance(data, dict) and "id" not in data and not (
            isinstance(data.get("data"), list)
            and all(isinstance(item, dict) and item.get("id") for item in data["data"])
        ):
            raise ResendDeliveryError("Resend returned no message ID; submission was not confirmed")
        return data

    @staticmethod
    def _payload(message):
        payload = {
            "from": message.from_email or settings.DEFAULT_FROM_EMAIL,
            "to": list(message.to or []),
            "subject": message.subject,
        }
        if getattr(message, "content_subtype", "plain") == "html":
            payload["html"] = str(message.body or "")
        else:
            payload["text"] = str(message.body or "")
        for part in getattr(message, "alternatives", ()):
            content = part.content if hasattr(part, "content") else part[0]
            mimetype = part.mimetype if hasattr(part, "mimetype") else part[1]
            if mimetype == "text/html":
                payload["html"] = str(content)
            elif mimetype == "text/plain":
                payload["text"] = str(content)
        if message.cc:
            payload["cc"] = list(message.cc)
        if message.bcc:
            payload["bcc"] = list(message.bcc)
        if message.reply_to:
            payload["reply_to"] = list(message.reply_to)
        if message.attachments:
            raise ResendDeliveryError("Email attachments are not supported by this backend")
        return payload

    def _send(self, message):
        payload = self._payload(message)
        # Legacy broadcast calls Django with no 'to' and all recipients in BCC.
        # Resend requires a real 'to'. Use the batch endpoint with an individual
        # message per recipient instead of revealing one recipient to the others.
        if not payload["to"] and payload.get("bcc"):
            recipients = payload.pop("bcc")
            for offset in range(0, len(recipients), 100):
                batch = [{**payload, "to": [email]} for email in recipients[offset:offset + 100]]
                self._post(self.api_url + "/batch", batch)
            return
        if not payload["to"]:
            raise ResendDeliveryError("Email recipient is missing")
        self._post(self.api_url, payload)

    def send_messages(self, email_messages):
        if not email_messages:
            return 0
        sent = 0
        for message in email_messages:
            try:
                self._send(message)
            except Exception:
                if not self.fail_silently:
                    raise
            else:
                sent += 1
        return sent
