"""Decides whether a draft may be sent automatically or must be held for a human.

Two layers: deterministic rules from knowledge/escalation.md (cannot be overridden by the model), and intent
labels from the classifier with per-intent confidence thresholds. Every reason is returned so it can be logged
and shown to the approver.
"""
from __future__ import annotations

import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import KNOWLEDGE_DIR

ESCALATION_PATH = KNOWLEDGE_DIR / "escalation.md"
WHATSAPP_WINDOW_SECONDS = 24 * 3600

# matches "1.234,56", "1234.56", "€ 120", "120 eur", "120€"
_AMOUNT = re.compile(r"(?:€\s?\d[\d.,]*|\d[\d.,]*\s?(?:€|eur\b|euro\b))", re.I)
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


@dataclass
class Rules:
    mode: str = "review_all"
    approvers: list[str] = field(default_factory=list)
    quote_total_above: float | None = None
    languages_allowed: list[str] = field(default_factory=list)
    hold_on_attachment: bool = True
    hold_on_keywords: list[str] = field(default_factory=list)
    hold_on_number_without_quote: bool = True
    hold_on_window_closed: bool = True
    intent_thresholds: dict[str, float] = field(default_factory=dict)
    never: list[str] = field(default_factory=list)
    reply_after_hours: bool = True
    after_hours_message: str = ""


def _kv(line: str) -> tuple[str, str] | None:
    m = re.match(r"^\s*([a-z_]+)\s*:\s*(.*?)\s*$", line)
    return (m.group(1), m.group(2)) if m else None


def load_rules(path: Path = ESCALATION_PATH) -> Rules:
    r = Rules()
    section = ""
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = re.sub(r"<!--.*?-->", "", raw).rstrip()
        if not line.strip():
            continue
        if line.startswith("## "):
            section = line[3:].strip().lower()
            continue
        if section == "approvers" and line.strip().startswith("-"):
            v = line.strip("- ").strip()
            if v:
                r.approvers.append(v)
            continue
        if section == "never" and line.strip().startswith("-"):
            v = line.strip("- ").strip()
            if v:
                r.never.append(v)
            continue
        kv = _kv(line)
        if not kv:
            continue
        k, v = kv
        if section == "mode" and k == "mode":
            r.mode = v
        elif section.startswith("hold when (deterministic)"):
            if k == "quote_total_above":
                r.quote_total_above = float(v) if v else None
            elif k == "languages_allowed":
                r.languages_allowed = [x.strip().lower() for x in v.split(",") if x.strip()]
            elif k == "hold_on_attachment":
                r.hold_on_attachment = v.lower() in ("yes", "true", "1")
            elif k == "hold_on_keywords":
                r.hold_on_keywords = [x.strip().lower() for x in v.split(",") if x.strip()]
            elif k == "hold_on_number_without_quote":
                r.hold_on_number_without_quote = v.lower() in ("yes", "true", "1")
            elif k == "hold_on_window_closed":
                r.hold_on_window_closed = v.lower() in ("yes", "true", "1")
        elif section.startswith("hold when (classified"):
            try:
                r.intent_thresholds[k] = float(v)
            except ValueError:
                pass
        elif section == "after hours":
            if k == "reply_after_hours":
                r.reply_after_hours = v.lower() in ("yes", "true", "1")
            elif k == "after_hours_message":
                r.after_hours_message = v
    if r.mode not in ("auto", "review_all"):
        r.mode = "review_all"
    return r


@dataclass
class Decision:
    hold: bool
    reasons: list[str]


def _numbers_in(text: str) -> set[str]:
    """Numeric tokens normalised to a decimal string with '.' separator and no thousands separators."""
    out = set()
    for m in _NUMBER.finditer(text):
        s = m.group(0)
        if "," in s and "." in s:
            s = s.replace(".", "").replace(",", ".")
        elif "," in s:
            s = s.replace(",", ".")
        try:
            out.add(str(float(s)))
        except ValueError:
            pass
    return out


def evaluate(draft_text: str, *, channel: str, language: str | None, intents: dict[str, float],
             has_attachment: bool, quote: dict[str, Any] | None, quote_amounts: set[str],
             last_inbound_at: float | None, rules: Rules, now: float | None = None,
             inbound_text: str = "") -> Decision:
    reasons: list[str] = []
    now = now or time.time()

    if rules.mode == "review_all":
        reasons.append("mode:review_all")

    low = draft_text.lower()
    for phrase in rules.never:
        if phrase.lower() in low:
            reasons.append(f"forbidden_phrase:{phrase}")

    if rules.languages_allowed and (not language or language.lower() not in rules.languages_allowed):
        reasons.append(f"language:{language or 'unknown'}")

    if rules.hold_on_attachment and has_attachment:
        reasons.append("attachment")

    inbound_low = inbound_text.lower()
    for kw in rules.hold_on_keywords:
        if re.search(rf"\b{re.escape(kw)}\b", inbound_low) or re.search(rf"\b{re.escape(kw)}\b", low):
            reasons.append(f"keyword:{kw}")

    if rules.quote_total_above is not None and quote and not quote.get("missing_inputs"):
        try:
            if float(quote["total"]) > rules.quote_total_above:
                reasons.append(f"quote_total_above:{rules.quote_total_above}")
        except (KeyError, ValueError, TypeError):
            reasons.append("quote_total_unreadable")

    if rules.hold_on_number_without_quote:
        # Any currency amount in the draft must be one the pricing engine produced.
        allowed = {str(float(a)) for a in quote_amounts} if quote_amounts else set()
        for m in _AMOUNT.finditer(draft_text):
            for n in _numbers_in(m.group(0)):
                if n not in allowed:
                    reasons.append(f"number_without_quote:{m.group(0).strip()}")
                    break

    if channel == "whatsapp" and rules.hold_on_window_closed and last_inbound_at is not None:
        if now - last_inbound_at > WHATSAPP_WINDOW_SECONDS:
            reasons.append("window_closed")

    for intent, score in (intents or {}).items():
        thr = rules.intent_thresholds.get(intent)
        if thr is not None and score >= thr:
            reasons.append(f"intent:{intent}:{score:.2f}")

    return Decision(hold=bool(reasons), reasons=reasons)


def recheck_before_send(channel: str, last_inbound_at: float | None, rules: Rules, now: float | None = None) -> list[str]:
    """Deterministic checks that can change between hold and approval."""
    now = now or time.time()
    if channel == "whatsapp" and rules.hold_on_window_closed and last_inbound_at is not None \
            and now - last_inbound_at > WHATSAPP_WINDOW_SECONDS:
        return ["window_closed"]
    return []


if __name__ == "__main__":
    # python -m server.gatekeeper --dry knowledge/escalation.md tests/fixtures/messages/
    if len(sys.argv) >= 4 and sys.argv[1] == "--dry":
        rules = load_rules(Path(sys.argv[2]))
        folder = Path(sys.argv[3])
        for f in sorted(folder.glob("*.txt")):
            text = f.read_text(encoding="utf-8")
            d = evaluate("", channel="whatsapp", language="nl", intents={}, has_attachment=False, quote=None,
                         quote_amounts=set(), last_inbound_at=None, rules=rules, inbound_text=text)
            print(f"{'HOLD' if d.hold else 'auto'} {f.name}: {', '.join(d.reasons) or '-'}")
    else:
        print("usage: python -m server.gatekeeper --dry knowledge/escalation.md tests/fixtures/messages/")
