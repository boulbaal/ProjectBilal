# server/

The always-on service. Python 3.11+, FastAPI, SQLite. Runs on the VPS as a systemd unit behind Caddy (automatic HTTPS).

| File | Role |
|---|---|
| `app.py` | HTTP routes: `/health`, `/webhook/whatsapp` (GET verify, POST inbound), `/approval/...` links. Starts the mail poller and housekeeping threads. |
| `pipeline.py` | One message in: classify, quote, draft, self-check, gate, send or hold. |
| `llm.py` | Model calls. Knowledge files are injected; the model never computes prices or decides to send. |
| `pricing.py` | Quote engine from `knowledge/pricing/rules.yaml`. `python -m server.pricing --check knowledge/pricing/examples.md` |
| `gatekeeper.py` | Hold/auto decision from `knowledge/escalation.md`. `python -m server.gatekeeper --dry knowledge/escalation.md tests/fixtures/messages/` |
| `whatsapp.py` | Meta Cloud API: signature check, parsing, sending. |
| `mail.py` | IMAP polling with UID mark, automated-mail filter, threaded SMTP replies. |
| `approval.py` | Signed single-use approve/reject/edit links, approval mails, reminders, expiry. |
| `db.py` | SQLite schema and helpers. `python -m server.db show drafts --last 5` |
| `config.py` | `.env` loading and validation. |
| `deploy/` | `install.sh` (on the VPS, first time), `update.sh` (from your computer, every deploy), systemd unit, Caddyfile. |

Run locally (dry run, no real sends):

```
pip install -r server/requirements.txt
cp .env.example .env   # fill in
uvicorn server.app:app --port 8000
curl localhost:8000/health
```

Tests: `python -m pytest tests -q` from the repository root.

Design decisions:
- Webhook is acknowledged immediately and processed in the background; Meta disables slow webhooks.
- One uvicorn worker on purpose: the mail poller must run exactly once.
- `DRY_RUN=true` sends nothing to customers but still sends approval mails to approvers, so the full flow can be tested.
- Every currency amount in a draft must come from the pricing engine; otherwise the draft is held.
- The 24-hour WhatsApp window is re-checked at approval time, because approvals can come late.
