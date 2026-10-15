"""The recommendation engine behind Socratic Shop.

Deliberately dependency-free: TF-IDF, cosine similarity, item-to-item
collaborative filtering and a Bayesian rating prior are all implemented here in
plain Python over sparse dicts. At this catalog size that is faster than
importing scikit-learn, it keeps the deploy small, and the maths stays
readable — which is the point of shipping it in a portfolio.

Four signals, blended by :mod:`app.shop.recommender`:

1. **Content similarity** — TF-IDF over a product's own text, compared by
   cosine. Answers "more like this".
2. **Collaborative filtering** — items co-occurring in the same basket, scored
   with a cosine over the item-user matrix. Answers "people who bought this
   also bought".
3. **Bayesian rating prior** — shrinks a 5.0-from-3-reviews toward the catalog
   mean, so "top rated" cannot be gamed by tiny sample sizes.
4. **Popularity and recency** — sold counts decayed by product age for
   "trending now".
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict

# --------------------------------------------------------------------------
# Text handling
# --------------------------------------------------------------------------

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has",
    "in", "is", "it", "its", "of", "on", "or", "that", "the", "this", "to",
    "with", "you", "your", "not", "but", "if", "we", "us", "our", "can",
}

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Lowercase, split, drop stopwords, and crudely singularise.

    The singularisation is a deliberate simplification: it merges
    "speakers"/"speaker" and "shoes"/"shoe" without pulling in a stemmer.
    """
    tokens = []
    for raw in _TOKEN_RE.findall((text or "").lower()):
        if len(raw) < 2 or raw in STOPWORDS:
            continue
        if len(raw) > 4 and raw.endswith("s") and not raw.endswith("ss"):
            raw = raw[:-1]
        tokens.append(raw)
    return tokens


class TfidfIndex:
    """A TF-IDF vector space over a fixed set of documents.

    Vectors are L2-normalised at build time, so cosine similarity is a plain
    dot product and every score lands in [0, 1].
    """

    def __init__(self, documents: dict[str, str]):
        self.doc_ids: list[str] = list(documents.keys())
        self.idf: dict[str, float] = {}
        self.vectors: dict[str, dict[str, float]] = {}
        self._build(documents)

    def _build(self, documents: dict[str, str]) -> None:
        tokenised = {doc_id: tokenize(text) for doc_id, text in documents.items()}
        n_docs = max(len(tokenised), 1)

        doc_freq: Counter[str] = Counter()
        for tokens in tokenised.values():
            doc_freq.update(set(tokens))

        # Smoothed inverse document frequency: never zero, never negative.
        self.idf = {
            term: math.log((1 + n_docs) / (1 + df)) + 1.0
            for term, df in doc_freq.items()
        }

        for doc_id, tokens in tokenised.items():
            self.vectors[doc_id] = self._normalise(self._tfidf(tokens))

    def _tfidf(self, tokens: list[str]) -> dict[str, float]:
        """Sub-linear term frequency, weighted by IDF."""
        counts = Counter(tokens)
        total = sum(counts.values()) or 1
        vec = {}
        for term, count in counts.items():
            tf = count / total
            weight = (1.0 + math.log(count)) * self.idf.get(term, 0.0)
            if weight:
                vec[term] = weight
        return vec

    @staticmethod
    def _normalise(vec: dict[str, float]) -> dict[str, float]:
        norm = math.sqrt(sum(v * v for v in vec.values()))
        if not norm:
            return {}
        return {k: v / norm for k, v in vec.items()}

    def vectorize(self, text: str) -> dict[str, float]:
        """Vectorise arbitrary text into the existing space."""
        return self._normalise(self._tfidf(tokenize(text)))

    @staticmethod
    def dot(a: dict[str, float], b: dict[str, float]) -> float:
        """Dot product of two sparse vectors, iterating the smaller one."""
        if len(a) > len(b):
            a, b = b, a
        return sum(weight * b.get(term, 0.0) for term, weight in a.items())

    def centroid(self, doc_ids: list[str]) -> dict[str, float]:
        """Mean of several document vectors — the 'taste profile' of a session."""
        acc: dict[str, float] = defaultdict(float)
        used = 0
        for doc_id in doc_ids:
            vec = self.vectors.get(doc_id)
            if not vec:
                continue
            used += 1
            for term, weight in vec.items():
                acc[term] += weight
        if not used:
            return {}
        return self._normalise({k: v / used for k, v in acc.items()})

    def rank(self, query_vec: dict[str, float], k: int = 10,
             exclude: set[str] | None = None,
             pool: list[str] | None = None) -> list[tuple[str, float]]:
        """Rank documents against a query vector by cosine similarity."""
        exclude = exclude or set()
        candidates = pool if pool is not None else self.doc_ids
        scored = []
        for doc_id in candidates:
            if doc_id in exclude:
                continue
            score = self.dot(query_vec, self.vectors.get(doc_id, {}))
            if score > 0:
                scored.append((doc_id, score))
        scored.sort(key=lambda pair: (-pair[1], pair[0]))
        return scored[:k]

    def similar(self, doc_id: str, k: int = 8,
                exclude: set[str] | None = None,
                pool: list[str] | None = None) -> list[tuple[str, float]]:
        """Documents closest to ``doc_id``."""
        vec = self.vectors.get(doc_id)
        if not vec:
            return []
        exclude = set(exclude or ()) | {doc_id}
        return self.rank(vec, k=k, exclude=exclude, pool=pool)


# --------------------------------------------------------------------------
# Collaborative filtering
# --------------------------------------------------------------------------

class ItemItemCF:
    """Item-to-item collaborative filtering from order baskets.

    Builds the item-user incidence matrix implicitly from orders, then scores
    pairs by the cosine of their user sets. Cosine (rather than raw
    co-occurrence) stops best-sellers from dominating every recommendation
    simply because they appear in more baskets.
    """

    def __init__(self, orders: list[dict]):
        self.n_orders = len(orders)
        self.item_orders: dict[str, set[str]] = defaultdict(set)
        self.order_items: dict[str, set[str]] = {}
        self.popularity: Counter[str] = Counter()

        for order in orders:
            order_id = order.get("id")
            items = {i for i in order.get("items", []) if i}
            if not order_id or not items:
                continue
            self.order_items[order_id] = items
            for item in items:
                self.item_orders[item].add(order_id)
                self.popularity[item] += 1

        self._neighbours: dict[str, list[tuple[str, float]]] = {}
        self._build_neighbours()

    def _build_neighbours(self) -> None:
        for item, orders in self.item_orders.items():
            counts: Counter[str] = Counter()
            for order_id in orders:
                for other in self.order_items[order_id]:
                    if other != item:
                        counts[other] += 1
            denom_a = math.sqrt(len(orders))
            scored = []
            for other, co in counts.items():
                denom_b = math.sqrt(len(self.item_orders[other]))
                if denom_a and denom_b:
                    scored.append((other, co / (denom_a * denom_b)))
            scored.sort(key=lambda pair: (-pair[1], pair[0]))
            self._neighbours[item] = scored

    def also_bought(self, item_id: str, k: int = 8,
                    exclude: set[str] | None = None) -> list[tuple[str, float]]:
        exclude = set(exclude or ()) | {item_id}
        return [(i, s) for i, s in self._neighbours.get(item_id, []) if i not in exclude][:k]

    def lift(self, a: str, b: str) -> float:
        """How much more often a and b co-occur than chance would suggest."""
        if not self.n_orders:
            return 0.0
        pa = len(self.item_orders.get(a, ())) / self.n_orders
        pb = len(self.item_orders.get(b, ())) / self.n_orders
        if not pa or not pb:
            return 0.0
        co = len(self.item_orders.get(a, set()) & self.item_orders.get(b, set())) / self.n_orders
        return co / (pa * pb)


# --------------------------------------------------------------------------
# Ranking priors
# --------------------------------------------------------------------------

def bayesian_rating(rating: float, reviews: int,
                    prior_mean: float = 4.15, prior_weight: float = 25.0) -> float:
    """Shrink a product's rating toward the catalog mean by review count.

    A single 5-star review carries little evidence, so it should not outrank a
    4.5 from 800 buyers. ``prior_weight`` is the number of reviews at which the
    product's own rating and the prior are weighted equally.
    """
    reviews = max(int(reviews or 0), 0)
    return (rating * reviews + prior_mean * prior_weight) / (reviews + prior_weight)


def popularity_score(sold: int, reviews: int, discount_pct: float) -> float:
    """A bounded 0-1 interest score used as the blend's cold-start signal."""
    sold_term = math.log1p(max(sold, 0)) / math.log1p(5000)
    reviews_term = math.log1p(max(reviews, 0)) / math.log1p(1500)
    discount_term = min(max(discount_pct, 0), 40) / 40
    return min(1.0, 0.5 * sold_term + 0.3 * reviews_term + 0.2 * discount_term)


def recency_score(created_days_ago: int, horizon: int = 240) -> float:
    """1.0 for brand-new stock decaying to 0.0 at the horizon."""
    age = max(int(created_days_ago or 0), 0)
    return max(0.0, 1.0 - min(age, horizon) / horizon)


def trending_score(sold: int, reviews: int, discount_pct: float,
                   created_days_ago: int) -> float:
    """Popularity weighted toward recent listings."""
    return 0.65 * popularity_score(sold, reviews, discount_pct) + \
        0.35 * recency_score(created_days_ago)
