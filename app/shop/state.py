"""Per-shopper session state: recently viewed, wishlist and placed orders.

Kept separate from the cart because the recommender reads browsing history
independently of what is in the basket.
"""

from __future__ import annotations

import random
import string
from datetime import datetime, timezone

from flask import session

HISTORY_KEY = "shop_history"
WISHLIST_KEY = "shop_wishlist"
ORDERS_KEY = "shop_orders"

MAX_HISTORY = 24
MAX_ORDERS = 8


# -- recently viewed ------------------------------------------------------

def record_view(product_id: str) -> None:
    """Push a product to the front of the browsing history."""
    if not product_id:
        return
    history = session.get(HISTORY_KEY) or []
    history = [h for h in history if h != product_id]
    history.insert(0, product_id)
    session[HISTORY_KEY] = history[:MAX_HISTORY]
    session.modified = True


def viewed_ids(limit: int | None = None) -> list[str]:
    """Most-recent-first product ids. This feeds the taste vector."""
    history = session.get(HISTORY_KEY) or []
    return history[:limit] if limit else list(history)


# -- wishlist -------------------------------------------------------------

def wishlist_ids() -> list[str]:
    return list(session.get(WISHLIST_KEY) or [])


def in_wishlist(product_id: str) -> bool:
    return product_id in wishlist_ids()


def toggle_wishlist(product_id: str) -> bool:
    """Add or remove a product. Returns True when it is now saved."""
    items = wishlist_ids()
    if product_id in items:
        items.remove(product_id)
        saved = False
    else:
        items.insert(0, product_id)
        saved = True
    session[WISHLIST_KEY] = items[:60]
    session.modified = True
    return saved


# -- orders ---------------------------------------------------------------

def new_order_ref() -> str:
    """Human-readable order reference, e.g. SS-7K2QF9."""
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"SS-{suffix}"


def save_order(order: dict) -> None:
    orders = list(session.get(ORDERS_KEY) or [])
    orders.insert(0, order)
    session[ORDERS_KEY] = orders[:MAX_ORDERS]
    session.modified = True


def get_order(ref: str) -> dict | None:
    for order in session.get(ORDERS_KEY) or []:
        if order.get("ref") == ref:
            return order
    return None


def list_orders() -> list[dict]:
    return list(session.get(ORDERS_KEY) or [])


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
