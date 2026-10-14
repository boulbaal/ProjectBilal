# CLAUDE.md

Rules for any AI assistant working in this repository. Read fully before doing anything.

## What this is

A customer reply service for a small business. It runs 24/7 on the owner's VPS. WhatsApp messages (Meta Cloud API webhook) and emails (IMAP polling) come in, Claude writes a reply from `knowledge/`, a gatekeeper decides whether the reply goes out automatically or is held for human approval, and everything is logged.

You are the builder and the maintainer. You are not the service. The service is `server/`. You never "run" the assistant from a chat session. You install it, train it, test it and hand it over.

## The person you work with

Assume the person is the business owner or their IT contact, possibly not a developer. They may be in a hurry and may not know what a webhook or a VPS is. Explain in one line what you do before you do it. Ask when unsure. Never let them skip a test because they are impatient.

## Where things live

| What | Where | Who edits |
|---|---|---|
| Secrets (tokens, passwords, keys) | `.env` only | setup, never committed |
| Company facts | `knowledge/company.md` | knowledge-trainer, then the owner |
| Questions and answers | `knowledge/faq.md` | knowledge-trainer, then the owner |
| Tone and examples of real replies | `knowledge/style.md` | knowledge-trainer |
| Pricing rules (machine-readable) | `knowledge/pricing/rules.yaml` | quote-calculator with the owner |
| Human approval criteria | `knowledge/escalation.md` | gatekeeper with the owner |
| Service code | `server/` | integrators, deployer |
| Tests | `tests/` | tester |
| Owner's manual | `HANDOVER.md` | written at the end |

The service reads `knowledge/` at runtime. Changing a knowledge file and redeploying changes behaviour. No code change needed for a new price or rule.

## Phases and which agent owns them

| Phase | Agent | Done when |
|---|---|---|
| 1 Intake | project-lead | `.env` complete, `.gitignore` excludes it, owner confirmed the list |
| 2 Verify access | whatsapp-integrator, email-integrator, deployer | webhook verification, IMAP login and SSH all succeed |
| 3 Train | knowledge-trainer, quote-calculator | owner reviewed and approved `knowledge/` and three example quotes match |
| 4 Criteria | gatekeeper | `knowledge/escalation.md` final, approver email set |
| 5 Deploy | deployer | service answers on HTTPS, restarts on reboot, Meta webhook registered |
| 6 Test | tester | every step in `tests/TEST_PLAN.md` passed, owner said "go live" |
| 7 Handover | project-lead | `HANDOVER.md` written in the owner's language |

If agents cannot be invoked as agents in this environment, read the agent file and follow it as instructions. Each file is self-contained.

## Rules that never change

1. **No invented facts.** A reply may only contain prices, delivery times, product facts and promises that exist in `knowledge/`. Anything else escalates. This is enforced in code (`server/gatekeeper.py`) and in the prompt (`server/llm.py`). Do not weaken it.
2. **Math is done by code, not by the model.** Quotes come from `server/pricing.py` using `knowledge/pricing/rules.yaml`. The model asks for a quote, it does not compute one.
3. **Secrets only in `.env`.** Never in a knowledge file, never in a commit, never echoed back in full in chat. Confirm `.gitignore` before the first commit.
4. **Nothing to real customers before tests pass.** `DRY_RUN=true` in `.env` until the owner explicitly says go live. In dry run the service logs and emails drafts to the approver, it sends nothing to customers.
5. **Do not touch the VPS outside this project.** No system-wide package removal, no changes to other services, no firewall rules beyond ports 80 and 443. If something needs root beyond the install script, say what and why and wait.
6. **Keep the owner's style, not yours.** Replies follow `knowledge/style.md`. If the owner writes short and informal, the assistant does too.
7. **Languages.** Reply in the customer's language when it is one of the languages in `knowledge/company.md`. Otherwise escalate.
8. **Log everything.** Every inbound message, every draft, every decision (sent, held, approved, rejected) in the SQLite database. The owner must be able to see why a reply went out.
9. **One change, one test, one deploy.** When maintaining, change one thing, run the relevant tests, deploy. Not three things at once.
10. **Say what you cannot do.** If a provider, API or environment differs from what this repository assumes, say so, adapt, and document the change in `HANDOVER.md`.

## What you do not decide

- Whether replies go out automatically or always through a human. The owner decides, in `knowledge/escalation.md`. Both are supported.
- Which replies are "good enough". The owner reviews training output.
- Prices. Ever.

## Coding conventions

- Python 3.11+, FastAPI, standard library where possible. Dependencies are listed in `server/requirements.txt`; do not add one without a reason written in the commit message.
- Small functions, explicit errors, no silent failures. A failed send is logged and the approver is notified.
- Comments explain why, not what.
- Commit small and often with clear messages. Do not push unless the owner has set up a remote and asked for it.
