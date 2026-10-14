"""Meta WhatsApp Cloud API: signature verification, inbound parsing, sending."""
from __future__ import annotations

import hashlib
import hmac
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from .config import settings

log = logging.getLogger("whatsapp")
GRAPH = "https://graph.facebook.com"


def verify_signature(raw_body: bytes, header: str | None, app_secret: str | None = None) -> bool:
    """X-Hub-Signature-256: sha256=<hex hmac of raw body with app secret>."""
    secret = app_secret if app_secret is not None else settings.meta_app_secret
    if not header or not header.startswith("sha256=") or not secret:
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header[len("sha256="):])


def sign(raw_body: bytes, app_secret: str) -> str:
    return "sha256=" + hmac.new(app_secret.encode(), raw_body, hashlib.sha256).hexdigest()


@dataclass
class Inbound:
    message_id: str
    sender: str          # phone number in international format without '+'
    text: str
    has_attachment: bool
    timestamp: float
    raw: dict[str, Any]


def parse_inbound(payload: dict[str, Any]) -> tuple[list[Inbound], list[dict[str, Any]]]:
    """Returns (messages, statuses). Status updates (sent/delivered/read) are not customer messages."""
    messages: list[Inbound] = []
    statuses: list[dict[str, Any]] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            statuses.extend(value.get("statuses", []) or [])
            for m in value.get("messages", []) or []:
                mtype = m.get("type")
                text = ""
                attach = False
                if mtype == "text":
                    text = m.get("text", {}).get("body", "")
                elif mtype == "button":
                    text = m.get("button", {}).get("text", "")
                elif mtype == "interactive":
                    i = m.get("interactive", {})
                    text = (i.get("button_reply") or i.get("list_reply") or {}).get("title", "")
                elif mtype in ("image", "document", "audio", "video", "sticker"):
                    attach = True
                    text = (m.get(mtype, {}) or {}).get("caption", "") or f"[{mtype}]"
                elif mtype == "location":
                    loc = m.get("location", {})
                    text = f"[location {loc.get('latitude')},{loc.get('longitude')}]"
                else:
                    text = f"[{mtype}]"
                messages.append(Inbound(
                    message_id=m.get("id", ""), sender=m.get("from", ""), text=text,
                    has_attachment=attach, timestamp=float(m.get("timestamp", 0) or 0), raw=m))
    return messages, statuses


def _url(path: str) -> str:
    return f"{GRAPH}/{settings.meta_api_version}/{path}"


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.meta_access_token}", "Content-Type": "application/json"}


def send_text(to: str, body: str) -> dict[str, Any]:
    """Send a free-form text. Only valid within 24h of the customer's last message. Raises on 4xx/5xx."""
    if settings.dry_run:
        log.info("DRY RUN: would send WhatsApp to %s: %r", to, body[:200])
        return {"dry_run": True}
    payload = {"messaging_product": "whatsapp", "recipient_type": "individual", "to": to,
               "type": "text", "text": {"preview_url": False, "body": body[:4096]}}
    with httpx.Client(timeout=20) as c:
        r = c.post(_url(f"{settings.meta_phone_number_id}/messages"), headers=_headers(), json=payload)
    if r.status_code >= 400:
        log.error("WhatsApp send failed %s: %s", r.status_code, r.text)
        raise RuntimeError(f"whatsapp send failed {r.status_code}: {r.text}")
    return r.json()


def mark_read(message_id: str) -> None:
    if settings.dry_run:
        return
    payload = {"messaging_product": "whatsapp", "status": "read", "message_id": message_id}
    with httpx.Client(timeout=20) as c:
        r = c.post(_url(f"{settings.meta_phone_number_id}/messages"), headers=_headers(), json=payload)
    if r.status_code >= 400:
        log.warning("mark_read failed %s: %s", r.status_code, r.text)


def check_phone_number() -> dict[str, Any]:
    """Phase 2 check: token and phone number id are valid."""
    with httpx.Client(timeout=20) as c:
        r = c.get(_url(f"{settings.meta_phone_number_id}"),
                  params={"fields": "display_phone_number,verified_name,quality_rating"}, headers=_headers())
    r.raise_for_status()
    return r.json()
