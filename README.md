# ProjectBilal

An always-on customer reply assistant for a small business, built and installed with Claude Cowork (or Claude Code) from this repository.

It listens to WhatsApp (Meta Cloud API) and a mailbox, writes replies in the business's own style from a knowledge folder, calculates quotes with explicit rules, and holds anything risky for a human to approve before it goes out.

This repository is generic. It contains no company data. Everything specific to a business lives in `knowledge/` and `.env`, which you fill in locally.

## What you get

```
ProjectBilal/
  PROMPT.md            The one prompt you paste into Claude Cowork. Start here.
  CLAUDE.md            Rules for the AI during setup and maintenance.
  INTAKE.md            Everything the setup asks you for, with explanations.
  .claude/agents/      Specialist agents the AI uses (integration, training, pricing, testing, ...).
  knowledge/           Templates for your company facts, FAQ, pricing rules, style and escalation criteria.
  server/              The service that runs 24/7 on your VPS.
  tests/               The step-by-step test plan and automated tests.
```

## How it works

1. A customer sends a WhatsApp message or an email.
2. Meta (or the mail poller) delivers it to the service on your VPS within seconds.
3. The service loads your knowledge files, lets Claude write a reply, and checks the reply against your escalation criteria.
4. Safe replies are sent automatically. Risky ones are held, and a person gets an email with the draft and an approve link.
5. Every message, reply and decision is logged.

## Hard facts you must accept before starting

- Claude Cowork is a workbench, not a service. It builds and maintains this system. The system itself runs on a VPS that is always on.
- Meta requires a public HTTPS address with a valid certificate. You need a VPS and a subdomain pointing to it.
- A phone number on the WhatsApp Cloud API cannot be used in the normal WhatsApp app at the same time.
- The assistant only knows what you put in `knowledge/`. No knowledge, no answers, only forwarding.
- You test it yourself, step by step, with `tests/TEST_PLAN.md`. The author of this repository cannot test against your Meta app, your mailbox or your VPS.

## Quick start

1. Clone this repository on the computer where you run Claude Cowork or Claude Code.
2. Open `PROMPT.md`, copy the prompt, paste it into Cowork with this folder open.
3. Answer its questions. It writes `.env`, fills `knowledge/`, installs the service on your VPS and walks you through the tests.

## Costs (yours)

- VPS: roughly 5 to 10 euro per month.
- Anthropic API: per message. Small at a few dozen messages per day.
- Meta WhatsApp Cloud API: per conversation. Check Meta's current pricing for your country.

## License

MIT. Use it, change it, no warranty.
