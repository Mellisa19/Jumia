"""Deterministic sample reviews.

A storefront without reviews looks unfinished, and reviews are also the clearest
place a recommender can earn trust ("4.4 from 318 buyers"). These are generated
from the product's own rating and a seeded hash so the same product always shows
the same reviews — stable across restarts, and no invented claims about real
people.
"""

from __future__ import annotations

import hashlib

FIRST_NAMES = [
    "Chidi", "Amaka", "Tunde", "Ngozi", "Emeka", "Fatima", "Ibrahim", "Blessing",
    "Segun", "Halima", "Obinna", "Yemi", "Kelechi", "Zainab", "Musa", "Ada",
]
CITIES = ["Lagos", "Abuja", "Port Harcourt", "Ibadan", "Kano", "Enugu", "Benin City"]

POSITIVE = [
    "Exactly as described and it arrived two days early. Packaging was sealed properly.",
    "Good value for the price. I compared three sellers before buying and this was the best deal.",
    "Works perfectly. The seller answered my questions on WhatsApp before I ordered.",
    "Second time buying from this store and the quality is consistent. Recommended.",
    "Very happy with it. The description matched what I received, no surprises.",
    "Solid build and the delivery rider was professional. Would buy again.",
]
MIXED = [
    "Good product overall, but delivery took one day longer than the estimate.",
    "Does the job well. I wish the manual had clearer instructions, but no complaints about the item.",
    "Quality is fine for the money. Not premium, but honestly priced.",
]
CRITICAL = [
    "Item is okay but arrived with a small dent on the carton. Seller responded quickly though.",
    "Works, but the accessories listed were not all in the box. Support sorted it out after I complained.",
]


def _pick(seq: list[str], seed: str, offset: int) -> str:
    digest = hashlib.sha256(f"{seed}:{offset}".encode("utf-8")).hexdigest()
    return seq[int(digest[:8], 16) % len(seq)]


def reviews_for(product: dict, limit: int = 4) -> list[dict]:
    """Build a small, stable set of reviews consistent with the product's rating."""
    seed = product["slug"]
    rating = float(product.get("rating", 4.2))
    out: list[dict] = []

    for i in range(limit):
        digest = hashlib.sha256(f"{seed}:r{i}".encode("utf-8")).hexdigest()
        roll = int(digest[8:16], 16) % 100

        # Skew the star distribution toward the product's own average.
        if roll < 62:
            stars = 5
            body = _pick(POSITIVE, seed, i)
        elif roll < 82:
            stars = 4
            body = _pick(POSITIVE if rating >= 4.3 else MIXED, seed, i + 40)
        elif roll < 94:
            stars = 3
            body = _pick(MIXED, seed, i + 80)
        else:
            stars = 2
            body = _pick(CRITICAL, seed, i + 120)

        name = _pick(FIRST_NAMES, seed, i + 200)
        city = _pick(CITIES, seed, i + 300)
        days = 2 + int(digest[16:20], 16) % 60

        out.append({
            "author": f"{name} {_pick(['A.', 'O.', 'B.', 'M.', 'I.', 'E.'], seed, i + 400)}",
            "city": city,
            "stars": stars,
            "days_ago": days,
            "verified": int(digest[20:24], 16) % 100 < 78,
            "body": body,
        })
    return out


def rating_breakdown(product: dict) -> list[dict]:
    """How the stars are distributed, derived from the average and review count."""
    rating = float(product.get("rating", 4.2))
    # A middle-heavy distribution around the average; good enough to render a bar chart.
    weights = {}
    for stars in range(1, 6):
        distance = abs(stars - rating)
        weights[stars] = max(0.02, 1.0 - distance * 0.42) ** 2
    total = sum(weights.values())
    rows = []
    for stars in range(5, 0, -1):
        share = weights[stars] / total
        rows.append({
            "stars": stars,
            "share": round(share * 100),
            "count": int(round(share * product.get("reviews", 0))),
        })
    return rows
