"""One place that turns catalog rows and recommendation objects into JSON.

The chat API, the live-search endpoint and the cart API all return product
shapes, so a single serializer keeps them from drifting apart. Paths are built
from :data:`SHOP_PREFIX` rather than ``url_for`` so the helpers stay callable
outside a request context (tests, the recommender's own smoke checks).
"""

from __future__ import annotations

from .cart import format_naira

SHOP_PREFIX = "/shop"


def product_url(slug: str) -> str:
    return f"{SHOP_PREFIX}/p/{slug}"


def image_url(slug: str) -> str:
    return f"{SHOP_PREFIX}/img/{slug}.svg"


def category_url(slug: str) -> str:
    return f"{SHOP_PREFIX}/c/{slug}"


def product_card(product: dict, reason: str | None = None,
                 score: float | None = None) -> dict:
    """The compact product shape used in grids, chat replies and live search."""
    card = {
        "id": product["id"],
        "slug": product["slug"],
        "title": product["title"],
        "brand": product["brand"],
        "category": product["category"],
        "category_label": product.get("category_label") or product["category"],
        "subcategory": product.get("subcategory", ""),
        "price": product["price"],
        "price_display": format_naira(product["price"]),
        "old_price": product.get("old_price"),
        "old_price_display": format_naira(product.get("old_price") or 0),
        "discount_pct": product.get("discount_pct", 0),
        "rating": product.get("rating", 0),
        "reviews": product.get("reviews", 0),
        "sold": product.get("sold", 0),
        "stock": product.get("stock", 0),
        "express": bool(product.get("express")),
        "flash": bool(product.get("flash")),
        "seller": product.get("seller", ""),
        "tags": product.get("tags", []),
        "url": product_url(product["slug"]),
        "image": product.get("image") or image_url(product["slug"]),
    }
    if reason:
        card["reason"] = reason
    if score is not None:
        card["score"] = round(float(score), 4)
    return card


def recommendation_card(rec: dict) -> dict:
    """Flatten a recommender result into a product card carrying its reason."""
    return product_card(rec["product"], reason=rec.get("reason"), score=rec.get("score"))


def recommendation_cards(recs: list[dict]) -> list[dict]:
    return [recommendation_card(r) for r in recs if r and r.get("product")]
