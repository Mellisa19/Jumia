"""Session-backed shopping cart with coupon and shipping rules.

State lives in the signed Flask session rather than the database. A storefront
cart is short-lived and small, and keeping it out of the ORM means the shop
works even if the analytics schema or migrations are in a bad state.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from flask import session

from . import catalog

CART_KEY = "shop_cart"

CURRENCY_SYMBOL = "\u20a6"          # Naira
FREE_SHIPPING_THRESHOLD = 50_000
STANDARD_SHIPPING = 1_500
EXPRESS_SHIPPING = 4_500
VAT_RATE = 0.075                    # Nigerian VAT, shown as included in price
MAX_QTY_PER_LINE = 20

COUPONS = {
    "WELCOME10": {
        "type": "percent", "value": 10, "label": "10% off your order",
        "min_spend": 0,
    },
    "SAVE2000": {
        "type": "fixed", "value": 2_000, "label": "\u20a62,000 off orders over \u20a625,000",
        "min_spend": 25_000,
    },
    "FREESHIP": {
        "type": "shipping", "value": 0, "label": "Free delivery on this order",
        "min_spend": 0,
    },
}


def format_naira(value) -> str:
    """Format a number as Naira, e.g. 189000 -> '\u20a6189,000'."""
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return str(value)
    return f"{CURRENCY_SYMBOL}{number:,.0f}"


@dataclass
class CartLine:
    product: dict
    qty: int

    @property
    def line_total(self) -> int:
        return self.product["price"] * self.qty

    @property
    def line_old_total(self) -> int:
        return self.product["old_price"] * self.qty

    @property
    def line_saving(self) -> int:
        return max(0, self.line_old_total - self.line_total)

    @property
    def max_qty(self) -> int:
        return min(MAX_QTY_PER_LINE, max(self.product.get("stock", 1), 1))


@dataclass
class Cart:
    lines: list[CartLine] = field(default_factory=list)
    coupon: str | None = None
    express: bool = False

    # -- construction ----------------------------------------------------
    @classmethod
    def from_session(cls, key: str = CART_KEY) -> "Cart":
        raw = session.get(key) or {}
        items = raw.get("items") or {}
        by_id = catalog.product_by_id()
        lines = []
        for pid, qty in items.items():
            product = by_id.get(pid)
            if not product:
                continue  # product retired from the catalog since the cart was saved
            try:
                qty = int(qty)
            except (TypeError, ValueError):
                continue
            if qty > 0:
                lines.append(CartLine(product, min(qty, MAX_QTY_PER_LINE)))
        return cls(lines=lines, coupon=raw.get("coupon") or None,
                   express=bool(raw.get("express")))

    def save(self, key: str = CART_KEY) -> None:
        session[key] = {
            "items": {line.product["id"]: line.qty for line in self.lines},
            "coupon": self.coupon,
            "express": self.express,
        }
        session.modified = True

    # -- mutation --------------------------------------------------------
    def _find(self, product_id: str) -> CartLine | None:
        return next((l for l in self.lines if l.product["id"] == product_id), None)

    def add(self, product_id: str, qty: int = 1) -> bool:
        product = catalog.product_by_id().get(product_id)
        if not product or product.get("stock", 0) <= 0 or qty <= 0:
            return False
        line = self._find(product_id)
        if line:
            line.qty = min(line.qty + qty, MAX_QTY_PER_LINE)
        else:
            self.lines.append(CartLine(product, min(qty, MAX_QTY_PER_LINE)))
        return True

    def set_qty(self, product_id: str, qty: int) -> None:
        line = self._find(product_id)
        if not line:
            return
        if qty <= 0:
            self.remove(product_id)
        else:
            line.qty = min(qty, MAX_QTY_PER_LINE)

    def remove(self, product_id: str) -> None:
        self.lines = [l for l in self.lines if l.product["id"] != product_id]

    def clear(self) -> None:
        self.lines = []
        self.coupon = None
        self.express = False

    # -- coupons ---------------------------------------------------------
    def apply_coupon(self, code: str) -> tuple[bool, str]:
        code = (code or "").strip().upper()
        if not code:
            return False, "Enter a coupon code."
        rule = COUPONS.get(code)
        if not rule:
            return False, f"\u201c{code}\u201d is not a valid coupon code."
        if self.subtotal < rule["min_spend"]:
            return False, (
                f"{code} needs a minimum spend of {format_naira(rule['min_spend'])}."
            )
        self.coupon = code
        return True, f"Coupon {code} applied: {rule['label']}."

    def remove_coupon(self) -> None:
        self.coupon = None

    # -- totals ----------------------------------------------------------
    @property
    def item_count(self) -> int:
        return sum(l.qty for l in self.lines)

    @property
    def subtotal(self) -> int:
        return sum(l.line_total for l in self.lines)

    @property
    def old_subtotal(self) -> int:
        return sum(l.line_old_total for l in self.lines)

    @property
    def coupon_rule(self) -> dict | None:
        return COUPONS.get(self.coupon or "")

    @property
    def discount(self) -> int:
        rule = self.coupon_rule
        if not rule or not self.lines:
            return 0
        if rule["type"] == "percent":
            return int(round(self.subtotal * rule["value"] / 100.0))
        if rule["type"] == "fixed":
            return min(rule["value"], self.subtotal)
        return 0

    @property
    def shipping(self) -> int:
        if not self.lines:
            return 0
        if self.coupon_rule and self.coupon_rule["type"] == "shipping":
            return 0
        if self.subtotal - self.discount >= FREE_SHIPPING_THRESHOLD:
            return 0
        return EXPRESS_SHIPPING if self.express else STANDARD_SHIPPING

    @property
    def total(self) -> int:
        return max(0, self.subtotal - self.discount) + self.shipping

    @property
    def total_saving(self) -> int:
        return max(0, self.old_subtotal - self.subtotal) + self.discount

    @property
    def vat_included(self) -> int:
        """VAT already inside the displayed price, shown for transparency."""
        return int(round(self.total * VAT_RATE / (1 + VAT_RATE)))

    @property
    def free_shipping_remaining(self) -> int:
        if not self.lines:
            return 0
        gap = FREE_SHIPPING_THRESHOLD - (self.subtotal - self.discount)
        return max(0, gap)

    def to_dict(self) -> dict:
        """JSON shape consumed by the slide-over cart and its API."""
        return {
            "items": [
                {
                    "id": l.product["id"],
                    "slug": l.product["slug"],
                    "title": l.product["title"],
                    "brand": l.product["brand"],
                    "price": l.product["price"],
                    "old_price": l.product["old_price"],
                    "qty": l.qty,
                    "max_qty": l.max_qty,
                    "line_total": l.line_total,
                    "image": f"/shop/img/{l.product['slug']}.svg",
                }
                for l in self.lines
            ],
            "item_count": self.item_count,
            "subtotal": self.subtotal,
            "subtotal_display": format_naira(self.subtotal),
            "discount": self.discount,
            "discount_display": format_naira(self.discount),
            "shipping": self.shipping,
            "shipping_display": "Free" if self.shipping == 0 else format_naira(self.shipping),
            "total": self.total,
            "total_display": format_naira(self.total),
            "total_saving": self.total_saving,
            "coupon": self.coupon,
            "express": self.express,
            "free_shipping_remaining": self.free_shipping_remaining,
            "free_shipping_remaining_display": format_naira(self.free_shipping_remaining),
        }
