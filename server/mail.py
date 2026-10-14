"""Mailbox: IMAP polling with a UID high-water mark, automated-mail filtering, SMTP sending with correct threading."""
from __future__ import annotations

import email
import email.utils
import imaplib
import logging
import re
import smtplib
import ssl
import time
from dataclasses import dataclass
from email.header import decode_header, make_header
from email.message import EmailMessage, Message
from typing import Any

from .config import settings

log = logging.getLogger("mail")

_AUTOMATED_FROM = re.compile(r"(no-?reply|mailer-daemon|postmaster|notification|donotreply|bounce)", re.I)
_QUOTE_MARKERS = [
    re.compile(r"(?m)^On .{3,200}wrote:\s*$"),
    re.compile(r"(?m)^Op .{3,200}schreef.*:\s*$"),
    re.compile(r"(?m)^Le .{3,200}a écrit\s*:\s*$"),
    re.compile(r"(?m)^-{2,}\s*Original Message\s*-{2,}"),
    re.compile(r"(?m)^From: .*\nSent: .*\nTo: .*"),
]


def _hdr(msg: Message, name: str) -> str:
    v = msg.get(name)
    if not v:
        return ""
    try:
        return str(make_header(decode_header(v)))
    except Exception:
        return str(v)


def is_automated(msg: Message, own_address: str) -> bool:
    """True for auto-replies, bounces, lists, newsletters and our own mail. Never reply to these."""
    auto = (msg.get("Auto-Submitted") or "").strip().lower()
    if auto and auto != "no":
        return True
    prec = (msg.get("Precedence") or "").strip().lower()
    if prec in ("bulk", "list", "junk", "auto_reply"):
        return True
    for h in ("List-Unsubscribe", "List-Id", "X-Autoreply", "X-Autorespond", "X-Auto-Response-Suppress"):
        if msg.get(h):
            return True
    if msg.get_content_type() == "multipart/report":
        return True
    frm = email.utils.parseaddr(_hdr(msg, "From"))[1].lower()
    if not frm or _AUTOMATED_FROM.search(frm):
        return True
    if own_address and frm == own_address.lower():
        return True
    return False


def _html_to_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style).*?</\1>", "", html)
    html = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>", "\n", html)
    text = re.sub(r"<[^>]+>", "", html)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def body_text(msg: Message) -> tuple[str, bool]:
    """Plain text body (HTML converted if needed) and whether there are attachments."""
    plain, html, attach = "", "", False
    for part in msg.walk():
        if part.is_multipart():
            continue
        disp = (part.get("Content-Disposition") or "").lower()
        if "attachment" in disp or part.get_filename():
            attach = True
            continue
        ct = part.get_content_type()
        try:
            payload = part.get_payload(decode=True) or b""
            charset = part.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="replace")
        except Exception:
            continue
        if ct == "text/plain" and not plain:
            plain = text
        elif ct == "text/html" and not html:
            html = text
    text = plain or _html_to_text(html)
    return strip_quoted(text), attach


def strip_quoted(text: str) -> str:
    """Remove quoted history so the model sees only the new part."""
    cut = len(text)
    for rx in _QUOTE_MARKERS:
        m = rx.search(text)
        if m and m.start() < cut:
            cut = m.start()
    text = text[:cut]
    lines = [ln for ln in text.splitlines() if not ln.lstrip().startswith(">")]
    return "\n".join(lines).strip()


@dataclass
class InboundMail:
    uid: str
    message_id: str
    sender: str
    reply_to: str
    subject: str
    text: str
    has_attachment: bool
    received_at: float
    references: str


def _imap() -> imaplib.IMAP4_SSL:
    ctx = ssl.create_default_context()
    con = imaplib.IMAP4_SSL(settings.mail_imap_host, settings.mail_imap_port, ssl_context=ctx)
    con.login(settings.mail_address, settings.mail_password)
    return con


def check_login() -> dict[str, Any]:
    """Phase 2 check. Returns folder count, INBOX message count and UIDVALIDITY."""
    con = _imap()
    try:
        typ, folders = con.list()
        typ, data = con.select("INBOX", readonly=True)
        count = int(data[0]) if data and data[0] else 0
        typ, uv = con.response("UIDVALIDITY")
        return {"folders": len(folders or []), "inbox_messages": count,
                "uidvalidity": uv[0].decode() if uv and uv[0] else None}
    finally:
        try:
            con.logout()
        except Exception:
            pass


def fetch_new(last_uid: int, last_uidvalidity: str | None) -> tuple[list[InboundMail], int, str]:
    """Fetch messages with UID > last_uid in INBOX. Returns (mails, new_last_uid, uidvalidity).
    If UIDVALIDITY changed, the mark is reset and only messages from now on are considered."""
    con = _imap()
    try:
        con.select("INBOX", readonly=True)
        typ, uv = con.response("UIDVALIDITY")
        uidvalidity = uv[0].decode() if uv and uv[0] else ""
        if last_uidvalidity and uidvalidity != last_uidvalidity:
            log.warning("UIDVALIDITY changed %s -> %s, resetting mark", last_uidvalidity, uidvalidity)
            last_uid = 0
        if last_uid == 0:
            # First run: do not process the whole history. Start from the current highest UID.
            typ, data = con.uid("search", None, "ALL")
            uids = [int(u) for u in (data[0].split() if data and data[0] else [])]
            return [], (max(uids) if uids else 0), uidvalidity
        typ, data = con.uid("search", None, f"UID {last_uid + 1}:*")
        uids = [int(u) for u in (data[0].split() if data and data[0] else []) if int(u) > last_uid]
        out: list[InboundMail] = []
        for uid in sorted(uids):
            typ, msgdata = con.uid("fetch", str(uid), "(RFC822)")
            raw = next((p[1] for p in msgdata if isinstance(p, tuple)), None)
            if not raw:
                continue
            msg = email.message_from_bytes(raw)
            if is_automated(msg, settings.mail_address):
                log.info("automated mail skipped uid=%s from=%s", uid, _hdr(msg, "From")[:80])
                continue
            text, attach = body_text(msg)
            sender = email.utils.parseaddr(_hdr(msg, "From"))[1].lower()
            reply_to = email.utils.parseaddr(_hdr(msg, "Reply-To"))[1].lower() or sender
            date_tuple = email.utils.parsedate_tz(msg.get("Date") or "")
            received = email.utils.mktime_tz(date_tuple) if date_tuple else time.time()
            out.append(InboundMail(
                uid=str(uid), message_id=(msg.get("Message-ID") or f"<uid-{uid}@{settings.mail_imap_host}>").strip(),
                sender=sender, reply_to=reply_to, subject=_hdr(msg, "Subject"), text=text,
                has_attachment=attach, received_at=received, references=(msg.get("References") or "").strip()))
        return out, (max(uids) if uids else last_uid), uidvalidity
    finally:
        try:
            con.logout()
        except Exception:
            pass


def send_reply(to: str, subject: str, body: str, in_reply_to: str | None, references: str | None) -> str:
    """Send a threaded reply. Returns our Message-ID. Honours DRY_RUN."""
    msg = EmailMessage()
    msg["From"] = settings.mail_address
    msg["To"] = to
    msg["Subject"] = subject if subject.lower().startswith("re:") else f"Re: {subject}"
    msg["Date"] = email.utils.formatdate(localtime=True)
    mid = email.utils.make_msgid(domain=settings.mail_address.split("@")[-1])
    msg["Message-ID"] = mid
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = f"{references} {in_reply_to}".strip() if references else in_reply_to
    msg.set_content(body)
    if settings.dry_run:
        log.info("DRY RUN: would send mail to %s subject %r", to, msg["Subject"])
        return mid
    _smtp_send(msg)
    return mid


def send_plain(to: list[str], subject: str, body: str, html: str | None = None) -> None:
    """Internal mail (approval requests, alerts). Always sent, even in dry run: approvers must see drafts."""
    msg = EmailMessage()
    msg["From"] = settings.mail_address
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject
    msg["Date"] = email.utils.formatdate(localtime=True)
    msg["Message-ID"] = email.utils.make_msgid(domain=settings.mail_address.split("@")[-1])
    msg["Auto-Submitted"] = "auto-generated"
    msg.set_content(body)
    if html:
        msg.add_alternative(html, subtype="html")
    _smtp_send(msg)


def _smtp_send(msg: EmailMessage) -> None:
    ctx = ssl.create_default_context()
    if settings.mail_smtp_port == 465:
        with smtplib.SMTP_SSL(settings.mail_smtp_host, 465, context=ctx, timeout=30) as s:
            s.login(settings.mail_address, settings.mail_password)
            s.send_message(msg)
    else:
        with smtplib.SMTP(settings.mail_smtp_host, settings.mail_smtp_port, timeout=30) as s:
            s.ehlo()
            s.starttls(context=ctx)
            s.login(settings.mail_address, settings.mail_password)
            s.send_message(msg)
    log.info("mail sent to %s subject %r", msg["To"], msg["Subject"])
