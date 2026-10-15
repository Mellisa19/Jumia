"""Blends the ML signals into the recommendation surfaces the shop renders.

Every recommendation carries a ``reason`` string. That is a product decision
rather than a technical one: an unexplained recommendation grid reads as noise,
while "Because you viewed Samsung Galaxy A15" tells the shopper why the shelf
changed and makes the personalisation legible.
"""

from __future__ import annotations

from functools import lru_cache

from . import catalog
from .ml import ItemItemCF, bayesian_rating, popularity_score

MAX_HISTORY = 12


class Recommender:
    """Content, collaborative, quality and popularity signals behind one API."""

    def __init__(self, products: tuple[dict, ...], orders: tuple[dict, ...]):
        self.products = list(products)
        self.by_id = {p["id"]: p for p in self.products}
        self.index = catalog.index()
        self.cf = ItemItemCF(list(orders))

    # -- helpers ---------------------------------------------------------
    def _pack(self, product_id: str, score: float, reason: str, signal: str) -> dict | None:
        product = self.by_id.get(product_id)
        if not product:
            return None
        return {"product": product, "score": round(float(score), 4),
                "reason": reason, "signal": signal}

    def _co_count(self, a: str, b: str) -> int:
        return len(self.cf.item_orders.get(a, set()) & self.cf.item_orders.get(b, set()))

    def _shared_traits(self, a: dict, b: dict) -> str:
        if a.get("brand") == b.get("brand"):
            return f"Another {a['brand']} pick in the same range"
        if a.get("subcategory") == b.get("subcategory"):
            return f"Similar {a['subcategory'].lower()} with matching specs"
        if a.get("category") == b.get("category"):
            return f"Comparable {a['category_label'].lower()} choice"
        return "Matched on your search wording"

    # -- surfaces --------------------------------------------------------
    def similar(self, product_id: str, k: int = 8,
                exclude: set[str] | None = None) -> list[dict]:
        """Content-similar products ('more like this')."""
        anchor = self.by_id.get(product_id)
        if not anchor:
            return []
        exclude = set(exclude or ()) | {product_id}

        # Search the product's own department and brand first. With a small
        # catalog, thin TF-IDF text can otherwise pair a phone with a shirt;
        # the global pass below only tops the shelf up when the local pool
        # cannot fill it.
        local_pool = [
            p["id"] for p in self.products
            if p["id"] not in exclude
            and (p["category"] == anchor["category"] or p["brand"] == anchor["brand"])
        ]

        out: list[dict] = []
        taken = set(exclude)
        for pool in (local_pool, None):
            if len(out) >= k:
                break
            for pid, score in self.index.similar(
                    product_id, k=k * 2, exclude=taken, pool=pool):
                candidate = self.by_id.get(pid)
                if not candidate or pid in taken:
                    continue
                taken.add(pid)
                out.append(self._pack(pid, score, self._shared_traits(anchor, candidate), "content"))
                if len(out) >= k:
                    break
        return out

    def also_bought(self, product_id: str, k: int = 8,
                    exclude: set[str] | None = None) -> list[dict]:
        """Collaborative 'customers also bought'."""
        exclude = set(exclude or ()) | {product_id}
        out = []
        for pid, score in self.cf.also_bought(product_id, k=k * 2, exclude=exclude):
            co = self._co_count(product_id, pid)
            buyers = self.cf.popularity.get(product_id, 0)
            if co >= 2 and buyers:
                pct = max(1, round(100 * co / buyers))
                reason = f"Bought with this in {pct}% of orders"
            else:
                reason = "Bought together by other shoppers"
            packed = self._pack(pid, score, reason, "collaborative")
            if packed:
                out.append(packed)
            if len(out) >= k:
                break
        return out

    def bundle(self, product_id: str, k: int = 3) -> dict | None:
        """'Frequently bought together' — CF partners with real lift, priced as a set."""
        anchor = self.by_id.get(product_id)
        if not anchor:
            return None
        partners = []
        for pid, _ in self.cf.also_bought(product_id, k=24):
            if self.cf.lift(product_id, pid) <= 1.0:
                continue
            packed = self._pack(pid, self.cf.lift(product_id, pid),
                                f"Added in {self._co_count(product_id, pid)} orders",
                                "collaborative")
            if packed:
                partners.append(packed)
            if len(partners) >= k:
                break
        if not partners:
            return None
        items = [anchor] + [p["product"] for p in partners]
        return {
            "anchor": anchor,
            # "products", not "items": Jinja would otherwise resolve
            # bundle.items to the dict method instead of this list.
            "products": items,
            "total": sum(i["price"] for i in items),
            "total_old": sum(i["old_price"] for i in items),
            "saving": sum(i["old_price"] - i["price"] for i in items),
        }

    def for_you(self, history_ids: list[str], k: int = 12,
                exclude: set[str] | None = None) -> list[dict]:
        """Personalised shelf from the session's browsing and cart history.

        Builds a taste vector (the centroid of everything seen), ranks the
        catalog against it, then blends in a popularity prior so a shopper with
        a thin history still gets sensible results instead of a random shelf.
        """
        exclude = set(exclude or ())
        history = [i for i in history_ids if i in self.by_id][-MAX_HISTORY:]

        if not history:
            return self.trending_shelf(k=k, exclude=exclude)

        centroid = self.index.centroid(history)
        ranked = self.index.rank(centroid, k=k * 3, exclude=exclude)
        anchor = self.by_id.get(history[-1])

        out = []
        for pid, score in ranked:
            candidate = self.by_id.get(pid)
            if not candidate:
                continue
            blend = 0.8 * score + 0.2 * popularity_score(
                candidate["sold"], candidate["reviews"], candidate["discount_pct"])
            if anchor:
                reason = f"Because you viewed {anchor['title'][:44]}"
            else:
                reason = "Picked for you"
            packed = self._pack(pid, blend, reason, "personal")
            if packed:
                out.append(packed)
        out.sort(key=lambda r: -r["score"])
        return out[:k]

    def trending_shelf(self, k: int = 12, exclude: set[str] | None = None) -> list[dict]:
        """Cold-start shelf: trending products with an honest reason."""
        exclude = set(exclude or ())
        pool = [p for p in self.products if p["id"] not in exclude]
        from .ml import trending_score
        pool.sort(key=lambda p: -trending_score(
            p["sold"], p["reviews"], p["discount_pct"], p["created_days_ago"]))
        out = []
        for p in pool[:k]:
            reason = f"{p['sold']:,} sold this month"
            out.append(self._pack(p["id"], popularity_score(
                p["sold"], p["reviews"], p["discount_pct"]), reason, "popularity"))
        return [r for r in out if r]

    def quality_shelf(self, k: int = 8, exclude: set[str] | None = None) -> list[dict]:
        """Top-rated shelf using the Bayesian prior, with the evidence in the reason."""
        exclude = set(exclude or ())
        pool = [p for p in self.products if p["id"] not in exclude]
        pool.sort(key=lambda p: -bayesian_rating(p["rating"], p["reviews"]))
        out = []
        for p in pool[:k]:
            out.append(self._pack(
                p["id"], bayesian_rating(p["rating"], p["reviews"]),
                f"{p['rating']} from {p['reviews']:,} reviews", "quality"))
        return [r for r in out if r]

    def rank_products(self, items: list[dict], k: int = 12) -> list[dict]:
        """Fallback: score an arbitrary product list by popularity."""
        scored = sorted(
            items,
            key=lambda p: -popularity_score(p["sold"], p["reviews"], p["discount_pct"]),
        )[:k]
        return [
            self._pack(p["id"], popularity_score(p["sold"], p["reviews"], p["discount_pct"]),
                       "Popular in this category", "popularity")
            for p in scored
        ]


@lru_cache(maxsize=1)
def get_recommender() -> Recommender:
    """Process-wide recommender. The index is built once on first use."""
    return Recommender(catalog.products(), catalog.orders())
