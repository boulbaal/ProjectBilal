"""Human approval of held drafts: signed single-use links, approval mails, approve/reject/edit handling."""
from __future__ import annotations

import hashlib
import hmac
import html
import json
import logging
import secrets
import time

from . import db, mail
from .config import settings

log = logging.getLogger("approval")
TOKEN_TTL_SECONDS = 72 * 3600


def new_token() -> str:
    return secrets.token_urlsafe(24)


def _sig(token: str, action: str, approver: str) -> str:
    msg = f"{token}:{action}:{approver}".encode()
    return hmac.new(settings.approval_secret.encode(), msg, hashlib.sha256).hexdigest()[:32]


def link(token: str, action: str, approver: str) -> str:
    return f"https://{settings.public_domain}/approval/{action}/{token}/{approver}/{_sig(token, action, approver)}"


def verify_link(token: str, action: str, approver: str, sig: str) -> bool:
    if not settings.approval_secret:
        return False
    return hmac.compare_digest(_sig(token, action, approver), sig)


def _mask(conversation: str, channel: str) -> str:
    if channel == "whatsapp":
        return "*" * max(0, len(conversation) - 4) + conversation[-4:]
    user, _, dom = conversation.partition("@")
    return (user[:2] + "***@" + dom) if dom else "***"


def notify_approvers(draft_id: int, reminder: bool = False) -> None:
    d = db.get_draft(draft_id)
    if not d:
        return
    m = db.get_message(d["message_id"])
    if not m:
        return
    reasons = json.loads(d["reasons"] or "[]")
    approvers = settings.approver_emails
    if not approvers:
        log.error("no APPROVER_EMAILS set; draft %s held with nobody to notify", draft_id)
        return
    for approver in approvers:
        a_link = link(d["token"], "approve", approver)
        r_link = link(d["token"], "reject", approver)
        e_link = link(d["token"], "edit", approver)
        subject = f"[{'REMINDER ' if reminder else ''}Reply needs your approval] {m['channel']} {_mask(m['conversation'], m['channel'])}"
        text = f"""A reply is waiting for approval.

Channel: {m['channel']}
Customer: {_mask(m['conversation'], m['channel'])}
Reasons: {', '.join(reasons) or '-'}
{'DRY RUN is on: approving will NOT send to the customer.' if settings.dry_run else ''}

--- Customer wrote ---
{(m['subject'] + chr(10)) if m['subject'] else ''}{m['body']}

--- Proposed reply ---
{d['text']}

Approve and send: {a_link}
Reject: {r_link}
Edit, then send: {e_link}

Links work once and expire in 72 hours.
"""
        body_html = f"""<p>A reply is waiting for approval.</p>
<p><b>Channel:</b> {html.escape(m['channel'])}<br><b>Customer:</b> {html.escape(_mask(m['conversation'], m['channel']))}<br>
<b>Reasons:</b> {html.escape(', '.join(reasons) or '-')}</p>
{'<p style="color:#b00"><b>DRY RUN is on: approving will NOT send to the customer.</b></p>' if settings.dry_run else ''}
<h4>Customer wrote</h4><pre style="white-space:pre-wrap">{html.escape((m['subject'] + chr(10)) if m['subject'] else '')}{html.escape(m['body'])}</pre>
<h4>Proposed reply</h4><pre style="white-space:pre-wrap;background:#f5f5f5;padding:8px">{html.escape(d['text'])}</pre>
<p><a href="{a_link}" style="background:#1a7f37;color:#fff;padding:10px 16px;text-decoration:none">Approve and send</a>
&nbsp; <a href="{r_link}" style="background:#b00;color:#fff;padding:10px 16px;text-decoration:none">Reject</a>
&nbsp; <a href="{e_link}" style="background:#555;color:#fff;padding:10px 16px;text-decoration:none">Edit, then send</a></p>
<p style="color:#777">Links work once and expire in 72 hours.</p>"""
        try:
            mail.send_plain([approver], subject, text, body_html)
        except Exception as e:  # noqa: BLE001
            log.exception("could not send approval mail to %s: %s", approver, e)
            db.event("approval_mail_failed", {"draft": draft_id, "approver": approver, "error": str(e)})
    db.event("approval_mail_sent", {"draft": draft_id, "reminder": reminder})


def alert(subject: str, body: str) -> None:
    """Operational alert to approvers (send failures, expiries)."""
    if not settings.approver_emails:
        return
    try:
        mail.send_plain(settings.approver_emails, f"[ProjectBilal] {subject}", body)
    except Exception as e:  # noqa: BLE001
        log.exception("alert mail failed: %s", e)


def expire_old() -> None:
    for d in db.held_drafts_older_than(TOKEN_TTL_SECONDS):
        db.update_draft(d["id"], status="expired", decided_at=time.time())
        db.event("draft_expired", {"draft": d["id"]})
        alert("A held reply expired without decision",
              f"Draft #{d['id']} was not approved or rejected within 72 hours. The customer did not get a reply.")


def remind_stale(after_seconds: int = 2 * 3600) -> None:
    for d in db.held_drafts_older_than(after_seconds):
        if not db.get_state(f"reminded:{d['id']}"):
            notify_approvers(d["id"], reminder=True)
            db.set_state(f"reminded:{d['id']}", True)
