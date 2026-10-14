import time
from pathlib import Path

from server import gatekeeper

ROOT = Path(__file__).resolve().parent.parent
RULES = gatekeeper.load_rules(ROOT / "knowledge/escalation.md")


def _auto_rules():
    r = gatekeeper.load_rules(ROOT / "knowledge/escalation.md")
    r.mode = "auto"
    return r


def _eval(draft, **kw):
    base = dict(channel="whatsapp", language="nl", intents={}, has_attachment=False, quote=None,
                quote_amounts=set(), last_inbound_at=time.time(), rules=_auto_rules(), inbound_text="")
    base.update(kw)
    return gatekeeper.evaluate(draft, **base)


def test_template_parses():
    assert RULES.mode == "review_all"
    assert RULES.quote_total_above == 50000
    assert "nl" in RULES.languages_allowed
    assert "klacht" in RULES.hold_on_keywords
    assert RULES.intent_thresholds["complaint"] == 0.6
    assert any("garanderen" in n for n in RULES.never)


def test_review_all_holds_everything():
    d = gatekeeper.evaluate("Hallo", channel="whatsapp", language="nl", intents={}, has_attachment=False,
                            quote=None, quote_amounts=set(), last_inbound_at=time.time(), rules=RULES)
    assert d.hold and "mode:review_all" in d.reasons


def test_auto_clean_draft_passes():
    d = _eval("Goedemiddag, ja we zijn zaterdag open van 9 tot 13.")
    assert not d.hold, d.reasons


def test_forbidden_phrase():
    d = _eval("Wij garanderen levering volgende week.")
    assert any(r.startswith("forbidden_phrase") for r in d.reasons)


def test_language_not_allowed():
    d = _eval("Guten Tag", language="de")
    assert "language:de" in d.reasons


def test_keyword_in_inbound():
    d = _eval("We bekijken het.", inbound_text="Ik heb een klacht over de levering")
    assert "keyword:klacht" in d.reasons


def test_attachment():
    d = _eval("Bedankt", has_attachment=True)
    assert "attachment" in d.reasons


def test_number_without_quote_is_held():
    d = _eval("Dat kost ongeveer € 120 per m2.")
    assert any(r.startswith("number_without_quote") for r in d.reasons)


def test_number_from_quote_is_allowed():
    d = _eval("Totaal: 453,75 EUR incl. btw.", quote={"total": "453.75", "missing_inputs": []},
              quote_amounts={"453.75", "375.00", "78.75"})
    assert not any(r.startswith("number_without_quote") for r in d.reasons), d.reasons


def test_quote_above_threshold():
    d = _eval("Totaal 60000 EUR", quote={"total": "60000.00", "missing_inputs": []}, quote_amounts={"60000.00"})
    assert any(r.startswith("quote_total_above") for r in d.reasons)


def test_window_closed_whatsapp_only():
    old = time.time() - 25 * 3600
    assert "window_closed" in _eval("Hoi", last_inbound_at=old).reasons
    assert "window_closed" not in _eval("Hoi", channel="email", last_inbound_at=old).reasons


def test_intent_threshold():
    d = _eval("Sorry daarvoor.", intents={"complaint": 0.7})
    assert any(r.startswith("intent:complaint") for r in d.reasons)
    d2 = _eval("Sorry daarvoor.", intents={"complaint": 0.3})
    assert not any(r.startswith("intent:complaint") for r in d2.reasons)


def test_recheck_before_send():
    r = _auto_rules()
    assert gatekeeper.recheck_before_send("whatsapp", time.time() - 25 * 3600, r) == ["window_closed"]
    assert gatekeeper.recheck_before_send("whatsapp", time.time() - 3600, r) == []
