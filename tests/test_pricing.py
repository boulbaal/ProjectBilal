from decimal import Decimal
from pathlib import Path

import pytest

from server import pricing

ROOT = Path(__file__).resolve().parent.parent
RULES = pricing.load_rules(ROOT / "knowledge/pricing/rules.yaml")


def test_template_example_matches():
    q = pricing.quote("example_panel", 3, ["installation"], "3500", rules=RULES)
    assert not q.missing_inputs
    assert q.subtotal == Decimal("375.00")
    assert q.vat == Decimal("78.75")
    assert q.total == Decimal("453.75")


def test_examples_file_all_match():
    res = pricing.check_examples(ROOT / "knowledge/pricing/examples.md")
    assert res, "examples.md has no yaml blocks"
    for name, exp, got, ok in res:
        assert ok, f"{name}: expected {exp}, got {got}"


def test_missing_inputs_reported_not_guessed():
    q = pricing.quote(None, None, None, None, rules=RULES)
    assert set(q.missing_inputs) == {"product", "quantity", "postcode"}
    assert q.total == Decimal("0")
    assert q.lines == []


def test_unknown_product_is_missing():
    q = pricing.quote("something we do not sell", 2, [], "3500", rules=RULES)
    assert "product" in q.missing_inputs


def test_alias_matching_in_sentence():
    assert pricing.find_product(RULES, "ik wil graag een paneel kopen")["id"] == "example_panel"
    assert pricing.find_product(RULES, "un panneau svp")["id"] == "example_panel"


def test_small_order_surcharge_and_national_delivery():
    q = pricing.quote("example_panel", 1, [], "1000", rules=RULES)
    names = [s.name for s in q.surcharges]
    assert "Small order surcharge" in names
    assert q.delivery is not None and q.delivery.total == Decimal("75.00")
    # 100 + 35 + 75 = 210 ; VAT 44.10 ; total 254.10
    assert q.total == Decimal("254.10")


def test_min_quantity_applied():
    q = pricing.quote("example_panel", "0.2", [], "3500", rules=RULES)
    assert q.lines[0].quantity == Decimal("0.5")
    assert any("minimum quantity" in n for n in q.notes)


def test_percent_option():
    q = pricing.quote("example_panel", 2, ["premium_finish"], "3500", rules=RULES)
    assert q.lines[1].total == Decimal("30.00")  # 15% of 200


def test_applies_when_expressions():
    ctx = {"quantity": Decimal("3"), "total_before_surcharges": Decimal("300"), "product.id": "x", "delivery.zone": "local"}
    assert pricing.applies("total_before_surcharges < 500", ctx)
    assert not pricing.applies("total_before_surcharges < 100", ctx)
    assert pricing.applies("quantity >= 3 and delivery.zone == 'local'", ctx)
    assert pricing.applies("quantity > 10 or product.id == x", ctx)
    with pytest.raises(pricing.RulesError):
        pricing.applies("__import__('os')", ctx)
    with pytest.raises(pricing.RulesError):
        pricing.applies("unknown_field > 1", ctx)


def test_amounts_set_for_gatekeeper():
    q = pricing.quote("example_panel", 3, ["installation"], "3500", rules=RULES)
    assert "453.75" in q.amounts()
    assert "375.00" in q.amounts()
