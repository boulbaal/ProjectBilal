"""Quote engine. Every number a customer sees comes from here, computed from knowledge/pricing/rules.yaml.

The language model extracts inputs (product, quantity, options, postcode) and calls quote(). It never does arithmetic.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field, asdict
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

import yaml

from .config import KNOWLEDGE_DIR

RULES_PATH = KNOWLEDGE_DIR / "pricing" / "rules.yaml"


@dataclass
class Line:
    name: str
    quantity: Decimal
    unit: str
    unit_price: Decimal
    total: Decimal


@dataclass
class Quote:
    currency: str
    lines: list[Line] = field(default_factory=list)
    surcharges: list[Line] = field(default_factory=list)
    delivery: Line | None = None
    subtotal: Decimal = Decimal("0")
    vat_percent: Decimal = Decimal("0")
    vat: Decimal = Decimal("0")
    total: Decimal = Decimal("0")
    prices_include_vat: bool = False
    valid_until: str = ""
    missing_inputs: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Decimals to strings so JSON and the model see exact values
        def conv(x: Any) -> Any:
            if isinstance(x, Decimal):
                return str(x)
            if isinstance(x, dict):
                return {k: conv(v) for k, v in x.items()}
            if isinstance(x, list):
                return [conv(v) for v in x]
            return x
        return conv(d)

    def amounts(self) -> set[str]:
        """All monetary amounts in this quote, as strings, for the gatekeeper's number check."""
        out: set[str] = set()
        for ln in [*self.lines, *self.surcharges, *( [self.delivery] if self.delivery else [])]:
            out.add(str(ln.unit_price)); out.add(str(ln.total))
        out.update({str(self.subtotal), str(self.vat), str(self.total)})
        return out


class RulesError(Exception):
    pass


def load_rules(path: Path = RULES_PATH) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        rules = yaml.safe_load(f)
    for key in ("currency", "vat_percent", "products"):
        if key not in rules:
            raise RulesError(f"rules.yaml missing '{key}'")
    return rules


def _d(x: Any) -> Decimal:
    return Decimal(str(x))


def _round(x: Decimal, step: Decimal) -> Decimal:
    return (x / step).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * step


def find_product(rules: dict[str, Any], text: str) -> dict[str, Any] | None:
    """Match a product by id or alias, case-insensitive, whole word."""
    t = text.lower().strip()
    for p in rules["products"]:
        names = [p["id"], p.get("name", ""), *p.get("aliases", [])]
        for n in names:
            if n and (t == n.lower() or re.search(rf"\b{re.escape(n.lower())}\b", t)):
                return p
    return None


def delivery_zone(rules: dict[str, Any], postcode: str | None) -> dict[str, Any] | None:
    zones = rules.get("delivery") or []
    if not zones:
        return None
    pc = (postcode or "").strip()
    wildcard = None
    for z in zones:
        for prefix in z.get("postcodes", []):
            if prefix == "*":
                wildcard = z
            elif pc and pc.startswith(str(prefix)):
                return z
    return wildcard


# applies_when: tiny whitelisted expression language. No eval.
_TOKEN = re.compile(r"\s*(?:(and|or)|([a-z_][a-z_.]*)\s*(<=|>=|==|!=|<|>)\s*(\"[^\"]*\"|'[^']*'|[0-9.]+|[a-z_]+))\s*", re.I)


def applies(expr: str, ctx: dict[str, Any]) -> bool:
    if not expr or not expr.strip():
        return True
    pos, result, op = 0, None, None
    while pos < len(expr):
        m = _TOKEN.match(expr, pos)
        if not m:
            raise RulesError(f"cannot parse applies_when: {expr!r} at {pos}")
        pos = m.end()
        if m.group(1):
            op = m.group(1).lower()
            continue
        key, cmp, rhs = m.group(2), m.group(3), m.group(4)
        if key not in ctx:
            raise RulesError(f"unknown field {key!r} in applies_when")
        lhs = ctx[key]
        rhs_v: Any = rhs.strip("\"'") if rhs[0] in "\"'" else (_d(rhs) if re.fullmatch(r"[0-9.]+", rhs) else rhs)
        if isinstance(lhs, Decimal) and not isinstance(rhs_v, Decimal):
            rhs_v = _d(rhs_v)
        if isinstance(lhs, bool):
            rhs_v = str(rhs_v).lower() in ("true", "1", "yes")
        val = {"<": lhs < rhs_v, "<=": lhs <= rhs_v, ">": lhs > rhs_v, ">=": lhs >= rhs_v,
               "==": lhs == rhs_v, "!=": lhs != rhs_v}[cmp]
        if result is None:
            result = val
        elif op == "and":
            result = result and val
        elif op == "or":
            result = result or val
        else:
            raise RulesError(f"missing and/or in applies_when: {expr!r}")
    return bool(result)


def quote(product: str | None, quantity: Any, options: list[str] | None = None, postcode: str | None = None,
          rules: dict[str, Any] | None = None, today: date | None = None) -> Quote:
    rules = rules or load_rules()
    q = Quote(currency=rules["currency"], vat_percent=_d(rules.get("vat_percent", 0)),
              prices_include_vat=bool(rules.get("prices_include_vat", False)))
    step = _d(rules.get("rounding", "0.01"))
    today = today or date.today()
    q.valid_until = (today + timedelta(days=int(rules.get("quote_validity_days", 30)))).isoformat()

    p = find_product(rules, product) if product else None
    if not p:
        q.missing_inputs.append("product")
    try:
        qty = _d(quantity) if quantity not in (None, "") else None
    except Exception:
        qty = None
    if qty is None or qty <= 0:
        q.missing_inputs.append("quantity")
    if rules.get("delivery") and not postcode:
        q.missing_inputs.append("postcode")
    if q.missing_inputs:
        return q

    assert p is not None and qty is not None
    if p.get("min_quantity") and qty < _d(p["min_quantity"]):
        q.notes.append(f"minimum quantity {p['min_quantity']} {p['unit']} applied")
        qty = _d(p["min_quantity"])

    unit_price = _d(p["price_per_unit"])
    line_total = _round(unit_price * qty, step)
    q.lines.append(Line(p.get("name", p["id"]), qty, p["unit"], unit_price, line_total))

    chosen = set(options or [])
    for o in p.get("options", []):
        if o["id"] in chosen or (o.get("default") and o["id"] not in chosen):
            if o["type"] == "per_unit":
                price, tot = _d(o["value"]), _round(_d(o["value"]) * qty, step)
            elif o["type"] == "fixed":
                price, tot = _d(o["value"]), _round(_d(o["value"]), step)
            elif o["type"] == "percent":
                price, tot = _d(o["value"]), _round(line_total * _d(o["value"]) / 100, step)
            else:
                raise RulesError(f"unknown option type {o['type']}")
            q.lines.append(Line(o["name"], qty if o["type"] == "per_unit" else Decimal("1"),
                                p["unit"] if o["type"] == "per_unit" else ("%" if o["type"] == "percent" else "piece"),
                                price, tot))
    unknown = chosen - {o["id"] for o in p.get("options", [])}
    if unknown:
        q.notes.append(f"ignored unknown options: {sorted(unknown)}")

    before = sum((ln.total for ln in q.lines), Decimal("0"))
    zone = delivery_zone(rules, postcode)
    ctx = {"quantity": qty, "total_before_surcharges": before, "product.id": p["id"],
           "delivery.zone": zone["zone"] if zone else "", **{f"option.{o['id']}": (o['id'] in chosen) for o in p.get("options", [])}}
    for s in rules.get("surcharges", []) or []:
        if applies(s.get("applies_when", ""), ctx):
            if s["type"] == "fixed":
                tot = _round(_d(s["value"]), step)
            elif s["type"] == "percent":
                tot = _round(before * _d(s["value"]) / 100, step)
            elif s["type"] == "per_unit":
                tot = _round(_d(s["value"]) * qty, step)
            else:
                raise RulesError(f"unknown surcharge type {s['type']}")
            q.surcharges.append(Line(s["name"], Decimal("1"), "", _d(s["value"]), tot))
    if zone:
        q.delivery = Line(f"Delivery ({zone['zone']})", Decimal("1"), "", _d(zone["price"]), _round(_d(zone["price"]), step))

    q.subtotal = _round(before + sum((s.total for s in q.surcharges), Decimal("0")) + (q.delivery.total if q.delivery else 0), step)
    minimum = _d(rules.get("minimum_order", 0))
    if minimum and q.subtotal < minimum:
        q.notes.append(f"minimum order {minimum} applied")
        q.subtotal = minimum
    if q.prices_include_vat:
        q.total = q.subtotal
        q.vat = _round(q.total - q.total / (1 + q.vat_percent / 100), step)
    else:
        q.vat = _round(q.subtotal * q.vat_percent / 100, step)
        q.total = _round(q.subtotal + q.vat, step)
    return q


def check_examples(path: Path) -> list[tuple[str, Decimal, Decimal | None, bool]]:
    """Run every ```yaml block in examples.md through quote(); return (name, expected, got, ok)."""
    text = path.read_text(encoding="utf-8")
    results = []
    for block in re.findall(r"```yaml\n(.*?)```", text, re.S):
        ex = yaml.safe_load(block)
        inp = ex.get("inputs", {})
        q = quote(inp.get("product"), inp.get("quantity"), inp.get("options"), str(inp.get("postcode", "")) or None)
        expected = _d(ex["expected_total"])
        got = None if q.missing_inputs else q.total
        results.append((ex.get("name", "?"), expected, got, got == expected))
    return results


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--check":
        res = check_examples(Path(sys.argv[2]))
        bad = 0
        for name, exp, got, ok in res:
            print(f"{'OK  ' if ok else 'FAIL'} {name}: expected {exp}, got {got}")
            bad += 0 if ok else 1
        print(f"{len(res) - bad}/{len(res)} examples match")
        sys.exit(1 if bad else 0)
    print("usage: python -m server.pricing --check knowledge/pricing/examples.md")
