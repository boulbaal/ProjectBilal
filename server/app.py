"""FastAPI service: WhatsApp webhook, mail poller, approval links, health. Run: uvicorn server.app:app"""
from __future__ import annotations

import html
import json
import logging
import threading
import time
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, Form, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

from . import approval, db, gatekeeper, mail, pipeline, whatsapp
from .config import settings

logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")

_stop = threading.Event()


def _mail_loop() -> None:
    while not _stop.is_set():
        try:
            last_uid = int(db.get_state("mail:last_uid", 0))
            last_uv = db.get_state("mail:uidvalidity")
            mails, new_uid, uv = mail.fetch_new(last_uid, last_uv)
            db.set_state("mail:last_uid", new_uid)
            db.set_state("mail:uidvalidity", uv)
            db.set_state("mail:last_poll", time.time())
            for im in mails:
                mid = db.insert_message("email", im.message_id, im.sender, "in", im.text, im.subject,
                                        raw={"reply_to": im.reply_to, "references": im.references, "uid": im.uid},
                                        has_attachment=im.has_attachment, received_at=im.received_at)
                if mid is None:
                    log.info("duplicate mail ignored %s", im.message_id)
                    continue
                try:
                    pipeline.handle_message(mid)
                except Exception as e:  # noqa: BLE001
                    log.exception("pipeline failed for mail %s", mid)
                    approval.alert("Processing failed", f"Mail message #{mid} could not be processed: {e}")
        except Exception as e:  # noqa: BLE001
            log.exception("mail poll failed: %s", e)
            db.set_state("mail:last_error", f"{time.strftime('%Y-%m-%d %H:%M:%S')} {e}")
        _stop.wait(settings.mail_poll_seconds)


def _housekeeping_loop() -> None:
    while not _stop.is_set():
        try:
            approval.expire_old()
            approval.remind_stale()
        except Exception as e:  # noqa: BLE001
            log.exception("housekeeping failed: %s", e)
        _stop.wait(600)


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init()
    missing = settings.missing_required()
    if missing:
        log.error("missing required settings: %s", ", ".join(missing))
    threads = [threading.Thread(target=_mail_loop, daemon=True, name="mail"),
               threading.Thread(target=_housekeeping_loop, daemon=True, name="housekeeping")]
    for t in threads:
        t.start()
    log.info("started, dry_run=%s", settings.dry_run)
    yield
    _stop.set()


app = FastAPI(title="ProjectBilal", lifespan=lifespan, docs_url=None, redoc_url=None)


@app.get("/health")
def health() -> JSONResponse:
    rules = gatekeeper.load_rules()
    last_poll = db.get_state("mail:last_poll")
    return JSONResponse({
        "ok": True,
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "dry_run": settings.dry_run,
        "mode": rules.mode,
        "approvers": len(settings.approver_emails),
        "last_whatsapp_webhook": db.get_state("wa:last_webhook"),
        "last_mail_poll": last_poll,
        "mail_poll_stale": bool(last_poll and time.time() - float(last_poll) > 5 * settings.mail_poll_seconds),
        "mail_last_error": db.get_state("mail:last_error"),
        "missing_settings": settings.missing_required(),
    })


@app.get("/webhook/whatsapp")
def whatsapp_verify(request: Request) -> Response:
    q = request.query_params
    if q.get("hub.mode") == "subscribe" and q.get("hub.verify_token") == settings.meta_verify_token:
        log.info("webhook verified by Meta")
        return PlainTextResponse(q.get("hub.challenge", ""))
    return PlainTextResponse("forbidden", status_code=403)


def _process_whatsapp(payload: dict) -> None:
    messages, statuses = whatsapp.parse_inbound(payload)
    for s in statuses:
        db.event("wa_status", {"id": s.get("id"), "status": s.get("status"), "errors": s.get("errors")})
    for im in messages:
        mid = db.insert_message("whatsapp", im.message_id, im.sender, "in", im.text, None, raw=im.raw,
                                has_attachment=im.has_attachment, received_at=im.timestamp or time.time())
        if mid is None:
            log.info("duplicate message id ignored %s", im.message_id)
            continue
        try:
            pipeline.handle_message(mid)
        except Exception as e:  # noqa: BLE001
            log.exception("pipeline failed for whatsapp %s", mid)
            approval.alert("Processing failed", f"WhatsApp message #{mid} could not be processed: {e}")


@app.post("/webhook/whatsapp")
async def whatsapp_webhook(request: Request, background: BackgroundTasks) -> Response:
    raw = await request.body()
    if not whatsapp.verify_signature(raw, request.headers.get("X-Hub-Signature-256")):
        log.warning("webhook with bad signature rejected")
        return PlainTextResponse("bad signature", status_code=403)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return PlainTextResponse("bad json", status_code=400)
    db.set_state("wa:last_webhook", time.time())
    # Acknowledge immediately; Meta retries and eventually disables the webhook if we are slow.
    background.add_task(_process_whatsapp, payload)
    return PlainTextResponse("ok")


def _page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(f"""<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><body style="font-family:sans-serif;max-width:640px;margin:40px auto;padding:0 16px">
<h2>{html.escape(title)}</h2>{body}</body>""")


def _load_for_action(token: str, action: str, approver: str, sig: str):
    if not approval.verify_link(token, action, approver, sig):
        return None, _page("Invalid link", "<p>This link is not valid.</p>")
    d = db.get_draft_by_token(token)
    if not d:
        return None, _page("Not found", "<p>No draft for this link.</p>")
    if d["token_used"]:
        return None, _page("Already used", f"<p>This draft was already handled (status: {html.escape(d['status'])}).</p>")
    if d["status"] != "held":
        return None, _page("Not pending", f"<p>This draft is no longer waiting (status: {html.escape(d['status'])}).</p>")
    return d, None


@app.get("/approval/approve/{token}/{approver}/{sig}")
def approve(token: str, approver: str, sig: str) -> HTMLResponse:
    d, err = _load_for_action(token, "approve", approver, sig)
    if err:
        return err
    db.update_draft(d["id"], token_used=1, approver=approver, decided_at=time.time())
    db.event("draft_approved", {"draft": d["id"], "approver": approver})
    pipeline.send_draft(d["id"], approver=approver)
    d2 = db.get_draft(d["id"])
    note = " (dry run: nothing was sent to the customer)" if settings.dry_run else ""
    return _page("Approved", f"<p>Status: {html.escape(d2['status'])}{note}</p>")


@app.get("/approval/reject/{token}/{approver}/{sig}")
def reject(token: str, approver: str, sig: str) -> HTMLResponse:
    d, err = _load_for_action(token, "reject", approver, sig)
    if err:
        return err
    db.update_draft(d["id"], token_used=1, status="rejected", approver=approver, decided_at=time.time())
    db.event("draft_rejected", {"draft": d["id"], "approver": approver})
    return _page("Rejected", "<p>Nothing was sent. The customer is waiting for a human reply.</p>")


@app.get("/approval/edit/{token}/{approver}/{sig}")
def edit_form(token: str, approver: str, sig: str) -> HTMLResponse:
    d, err = _load_for_action(token, "edit", approver, sig)
    if err:
        return err
    m = db.get_message(d["message_id"])
    return _page("Edit and send", f"""
<h4>Customer wrote</h4><pre style="white-space:pre-wrap">{html.escape(m['body'])}</pre>
<form method=post>
<textarea name=text rows=12 style="width:100%;font-size:15px">{html.escape(d['text'])}</textarea>
<p><button type=submit style="padding:10px 16px">Send this reply</button></p></form>""")


@app.post("/approval/edit/{token}/{approver}/{sig}")
def edit_submit(token: str, approver: str, sig: str, text: str = Form(...)) -> HTMLResponse:
    d, err = _load_for_action(token, "edit", approver, sig)
    if err:
        return err
    text = text.strip()
    if not text:
        return _page("Empty", "<p>The reply is empty. Go back and write something, or use the reject link.</p>")
    db.update_draft(d["id"], text=text, token_used=1, approver=approver, decided_at=time.time())
    db.event("draft_edited", {"draft": d["id"], "approver": approver})
    pipeline.send_draft(d["id"], approver=approver)
    d2 = db.get_draft(d["id"])
    note = " (dry run: nothing was sent to the customer)" if settings.dry_run else ""
    return _page("Sent", f"<p>Status: {html.escape(d2['status'])}{note}</p>")
