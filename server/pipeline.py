"""One inbound message in, one decision out: classify, quote, draft, self-check, gate, send or hold."""
from __future__ import annotations

import json
import logging
import time

from . import approval, db, gatekeeper, llm, mail, pricing, whatsapp
from .config import settings

log = logging.getLogger("pipeline")


def _history_lines(conversation: str) -> list[str]:
    out = []
    for r in db.conversation_history(conversation, limit=5):
        who = "Customer" if r["direction"] == "in" else "Us"
        out.append(f"{who}: {r['body'][:600]}")
    return out


def handle_message(message_id: int) -> int | None:
    """Process a stored inbound message. Returns the draft id, or None if nothing was drafted."""
    m = db.get_message(message_id)
    if not m or m["direction"] != "in":
        return None
    rules = gatekeeper.load_rules()
    try:
        pricing_rules = pricing.load_rules()
        product_ids = [p["id"] for p in pricing_rules["products"]]
    except Exception as e:  # noqa: BLE001
        log.warning("pricing rules unreadable: %s", e)
        pricing_rules, product_ids = None, []

    history = _history_lines(m["conversation"])[:-1]  # exclude the message itself (stored already)
    cls = llm.classify(m["body"], history, product_ids)
    if cls.intents.get("spam", 0) >= 0.8:
        db.event("spam_ignored", {"message": message_id})
        return None

    quote_dict = None
    quote_amounts: set[str] = set()
    if cls.wants_quote and pricing_rules:
        q = pricing.quote(cls.product, cls.quantity, cls.options, cls.postcode, rules=pricing_rules)
        quote_dict = q.as_dict()
        quote_amounts = q.amounts() if not q.missing_inputs else set()

    text = llm.draft(m["body"], m["channel"], history, quote_dict, cls)
    unsupported = llm.self_check(text, llm.context_for_check(m["channel"], m["body"], quote_dict))

    last_in = db.last_inbound_at(m["conversation"], m["channel"])
    decision = gatekeeper.evaluate(
        text, channel=m["channel"], language=cls.language, intents=cls.intents,
        has_attachment=bool(m["has_attachment"]), quote=quote_dict, quote_amounts=quote_amounts,
        last_inbound_at=last_in, rules=rules, inbound_text=m["body"])
    reasons = list(decision.reasons)
    for u in unsupported:
        reasons.append(f"unsupported_claim:{u[:80]}")

    if reasons:
        token = approval.new_token()
        draft_id = db.insert_draft(message_id, text, cls.language, cls.intents, quote_dict, "held", reasons, token)
        db.event("draft_held", {"draft": draft_id, "reasons": reasons})
        approval.notify_approvers(draft_id)
        return draft_id

    draft_id = db.insert_draft(message_id, text, cls.language, cls.intents, quote_dict, "pending", [], None)
    send_draft(draft_id, approver=None)
    return draft_id


def send_draft(draft_id: int, approver: str | None) -> None:
    d = db.get_draft(draft_id)
    m = db.get_message(d["message_id"])
    rules = gatekeeper.load_rules()
    recheck = gatekeeper.recheck_before_send(m["channel"], db.last_inbound_at(m["conversation"], m["channel"]), rules)
    if recheck:
        db.update_draft(draft_id, status="held", reasons=json.loads(d["reasons"] or "[]") + recheck)
        approval.alert("Reply could not be sent", f"Draft #{draft_id}: {', '.join(recheck)}. "
                       "The WhatsApp 24-hour window has closed; the customer must write again first.")
        return
    try:
        if m["channel"] == "whatsapp":
            whatsapp.send_text(m["conversation"], d["text"])
            whatsapp.mark_read(m["external_id"])
            ext = f"out-{draft_id}-{int(time.time())}"
        else:
            raw = json.loads(m["raw"] or "{}")
            ext = mail.send_reply(raw.get("reply_to") or m["conversation"], m["subject"] or "",
                                  d["text"], m["external_id"], raw.get("references"))
        status = "approved_dry" if (settings.dry_run and approver) else ("approved_sent" if approver else "sent")
        if settings.dry_run and not approver:
            status = "sent_dry"
        db.update_draft(draft_id, status=status, approver=approver, sent_at=time.time(), decided_at=time.time())
        if not settings.dry_run:
            db.insert_message(m["channel"], ext, m["conversation"], "out", d["text"], m["subject"])
        db.event("draft_sent", {"draft": draft_id, "status": status})
    except Exception as e:  # noqa: BLE001
        log.exception("send failed for draft %s", draft_id)
        db.update_draft(draft_id, status="failed", error=str(e)[:1000], decided_at=time.time())
        approval.alert("Reply failed to send", f"Draft #{draft_id} could not be sent: {e}")
