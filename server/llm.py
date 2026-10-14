"""Model calls. Three steps per inbound message: classify, draft, self_check.

The model only ever sees knowledge/ and the conversation. It never computes prices (pricing.py does) and
never decides whether a reply is sent (gatekeeper.py does).
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import anthropic

from .config import KNOWLEDGE_DIR, settings

log = logging.getLogger("llm")

INTENTS = ["price_request", "availability", "delivery_time", "appointment", "complaint",
           "discount_or_special_terms", "existing_order_or_appointment", "legal_or_warranty",
           "human_requested", "unknown_or_cannot_answer", "spam", "greeting_only"]

_client: anthropic.Anthropic | None = None


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    return _client


def _read(name: str) -> str:
    p = KNOWLEDGE_DIR / name
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _strip_comments(md: str) -> str:
    return re.sub(r"<!--.*?-->", "", md, flags=re.S).strip()


@dataclass
class Classification:
    language: str = "unknown"
    intents: dict[str, float] = field(default_factory=dict)
    wants_quote: bool = False
    product: str | None = None
    quantity: str | None = None
    options: list[str] = field(default_factory=list)
    postcode: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


def _json_from(text: str) -> dict[str, Any]:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}


def classify(message: str, history: list[str], product_names: list[str]) -> Classification:
    company = _strip_comments(_read("company.md"))
    prompt = f"""You label a customer message for a small business. Reply with JSON only.

Business facts (for context):
{company}

Known products (ids): {", ".join(product_names) or "none"}

Previous messages in this conversation (oldest first):
{chr(10).join(history) or "(none)"}

Customer message:
\"\"\"{message}\"\"\"

Return exactly this JSON:
{{
 "language": "<ISO 639-1 code of the customer's language, e.g. nl, fr, en, or unknown>",
 "intents": {{<intent>: <confidence 0..1>, ...}}   // only from: {", ".join(INTENTS)}
 "wants_quote": <true|false>,
 "product": "<product id from the known list, or null>",
 "quantity": "<number as written, in the product's unit, or null>",
 "options": ["<option ids mentioned>"],
 "postcode": "<postcode if mentioned, else null>"
}}
Do not invent a product that is not in the list. Do not guess a quantity that is not stated."""
    resp = client().messages.create(model=settings.anthropic_model, max_tokens=400, temperature=0,
                                    messages=[{"role": "user", "content": prompt}])
    data = _json_from("".join(b.text for b in resp.content if getattr(b, "type", "") == "text"))
    c = Classification(raw=data)
    c.language = str(data.get("language") or "unknown").lower()[:5]
    c.intents = {k: float(v) for k, v in (data.get("intents") or {}).items() if k in INTENTS}
    c.wants_quote = bool(data.get("wants_quote"))
    c.product = data.get("product") or None
    c.quantity = str(data["quantity"]) if data.get("quantity") not in (None, "") else None
    c.options = [str(o) for o in (data.get("options") or [])]
    c.postcode = str(data["postcode"]) if data.get("postcode") else None
    return c


def _faq_entries(faq: str) -> list[str]:
    parts = re.split(r"(?m)^### ", faq)
    return ["### " + p.strip() for p in parts[1:] if p.strip()]


def retrieve_faq(message: str, faq: str, top: int = 8) -> str:
    """Simple keyword overlap. Good enough for a few dozen entries; the whole file if it is small."""
    if len(faq) < 6000:
        return faq
    words = {w for w in re.findall(r"\w{3,}", message.lower())}
    scored = []
    for e in _faq_entries(faq):
        ew = set(re.findall(r"\w{3,}", e.lower()))
        scored.append((len(words & ew), e))
    scored.sort(key=lambda x: -x[0])
    return "\n\n".join(e for s, e in scored[:top] if s > 0)


def _system_blocks(channel: str) -> list[dict[str, Any]]:
    company = _strip_comments(_read("company.md"))
    style = _strip_comments(_read("style.md"))
    never = _strip_comments(_read("escalation.md"))
    never_section = never.split("## Never", 1)[1].split("## ", 1)[0] if "## Never" in never else ""
    rules = f"""You write replies to customers on behalf of a small business, on the channel: {channel}.

Hard rules:
1. Use ONLY the facts in the knowledge below. If the customer asks something not covered, say politely that a colleague will come back to them. Never guess, never say "usually" or "typically".
2. NEVER state a price, amount or delivery time unless it appears in the QUOTE section of the user message. If a quote is given, copy its numbers exactly as written, do not round or reformat.
3. Write in the customer's language if it is one the business uses (see company facts). Otherwise write one short sentence in the main language saying a colleague will reply.
4. Follow the style guide: same greeting, formality, length and sign-off as the examples, per channel. WhatsApp replies are short.
5. Never produce any of these phrases: {never_section.strip() or "(none)"}
6. Answer the question asked. At most one helpful addition the business normally makes. No upselling.
7. Output the reply text only. No preamble, no explanation, no subject line.

Company facts:
{company}

Style guide:
{style}
"""
    return [{"type": "text", "text": rules, "cache_control": {"type": "ephemeral"}}]


def _now_str() -> str:
    company = _read("company.md")
    m = re.search(r"Timezone:\s*([\w/]+)", company)
    tz = ZoneInfo(m.group(1)) if m else ZoneInfo("UTC")
    return datetime.now(tz).strftime("%A %Y-%m-%d %H:%M %Z")


def draft(message: str, channel: str, history: list[str], quote: dict[str, Any] | None,
          classification: Classification) -> str:
    faq = retrieve_faq(message, _strip_comments(_read("faq.md")))
    quote_text = "(no quote requested or computed)"
    if quote:
        if quote.get("missing_inputs"):
            quote_text = ("QUOTE NOT POSSIBLE. Missing inputs: " + ", ".join(quote["missing_inputs"]) +
                          ". Ask the customer for exactly these, nothing else. Do not mention any price.")
        else:
            quote_text = "QUOTE (copy numbers exactly):\n" + json.dumps(quote, indent=1, ensure_ascii=False)
    user = f"""Current date/time: {_now_str()}
Detected customer language: {classification.language}

Relevant FAQ entries:
{faq or "(none)"}

{quote_text}

Previous messages in this conversation (oldest first):
{chr(10).join(history) or "(none)"}

Customer message:
\"\"\"{message}\"\"\"

Write the reply."""
    resp = client().messages.create(model=settings.anthropic_model, max_tokens=700, temperature=0.3,
                                    system=_system_blocks(channel),
                                    messages=[{"role": "user", "content": user}])
    return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()


def self_check(draft_text: str, context_text: str) -> list[str]:
    """Ask the model to list claims in the draft that are not supported by the context. Returns unsupported claims."""
    prompt = f"""Below is a draft reply and the only context the writer was allowed to use.
List every factual claim, number, date or promise in the draft that is NOT directly supported by the context.
Reply with JSON: {{"unsupported": ["<claim>", ...]}}. If everything is supported, return {{"unsupported": []}}.

CONTEXT:
{context_text}

DRAFT:
{draft_text}"""
    resp = client().messages.create(model=settings.anthropic_model, max_tokens=400, temperature=0,
                                    messages=[{"role": "user", "content": prompt}])
    data = _json_from("".join(b.text for b in resp.content if getattr(b, "type", "") == "text"))
    return [str(x) for x in (data.get("unsupported") or [])]


def context_for_check(channel: str, message: str, quote: dict[str, Any] | None) -> str:
    return "\n\n".join([
        _strip_comments(_read("company.md")),
        retrieve_faq(message, _strip_comments(_read("faq.md"))),
        "QUOTE:\n" + json.dumps(quote, ensure_ascii=False) if quote else "QUOTE: none",
    ])
