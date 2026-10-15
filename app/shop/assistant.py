"""The AI shopping assistant.

Architecture: **retrieval always decides which products are shown; language
models only ever write the prose around them.** An LLM that invents a product
or a price is worse than no LLM at all, so the catalog is the single source of
truth and the model is handed a fixed shortlist it is told not to extend.

Two tiers:

* **Tier 1 (always on)** — deterministic intent and entity parsing, then
  TF-IDF retrieval over the catalog through :mod:`app.shop.catalog`. Runs with
  no API key, costs nothing, and cannot hallucinate.
* **Tier 2 (opt-in)** — if ``SHOP_LLM_API_KEY`` is set, the shortlist and the
  shopper's question are sent to a chat-completions endpoint for a more natural
  answer. Any failure — timeout, bad key, rate limit, malformed response —
  silently falls back to the Tier 1 wording, so the assistant never breaks.

Config (all optional):
    SHOP_LLM_API_KEY   enables Tier 2
    SHOP_LLM_BASE_URL  default https://api.deepseek.com/v1
    SHOP_LLM_MODEL     default deepseek-chat
    SHOP_LLM_TIMEOUT   default 12 seconds
"""

from __future__ import annotations

import json
import os
import re

from . import catalog
from .cart import format_naira
from .serializers import product_card

# --------------------------------------------------------------------------
# Intent vocabulary
# --------------------------------------------------------------------------

CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "phones-tablets": [
        "phone", "phones", "smartphone", "smartphones", "android", "iphone",
        "tablet", "tablets", "handset", "mobile", "sim", "redmi", "tecno",
        "infinix", "samsung galaxy",
    ],
    "computing": [
        "laptop", "laptops", "computer", "notebook", "macbook", "pc", "monitor",
        "keyboard", "mouse", "ssd", "hard drive", "storage", "ram", "ideapad",
    ],
    "electronics": [
        "tv", "television", "speaker", "speakers", "headphone", "headphones",
        "soundbar", "sound bar", "decoder", "dstv", "audio", "bluetooth",
        "earbuds", "home theatre",
    ],
    "appliances": [
        "fridge", "refrigerator", "freezer", "washing machine", "washer",
        "air conditioner", "air condition", "split ac", "kettle", "air fryer",
        "appliance", "appliances", "generator",
    ],
    "home-kitchen": [
        "blender", "cookware", "pot", "pots", "pan", "dining table", "dining",
        "pillow", "mosquito net", "kitchen", "cooker", "gas cooker", "furniture",
        "bedding", "mattress", "curtain", "home",
    ],
    "health-beauty": [
        "lotion", "skincare", "skin care", "serum", "cleanser", "razor",
        "toothbrush", "foundation", "makeup", "beauty", "grooming", "shaving",
        "cream", "perfume", "body care", "niacinamide",
    ],
    "fashion": [
        "shirt", "dress", "shoe", "shoes", "sneakers", "bag", "briefcase",
        "sunglasses", "watch", "clothes", "clothing", "fashion", "ankara",
        "footwear", "jeans", "trouser", "wear",
    ],
    "baby-products": [
        "baby", "diaper", "diapers", "pampers", "stroller", "baby bottle",
        "car seat", "wipes", "nursery", "infant", "newborn", "pram", "feeding",
    ],
    "grocery": [
        "rice", "noodles", "indomie", "milk", "sugar", "cooking oil",
        "vegetable oil", "coke", "coca cola", "grocery", "groceries", "food",
        "semovita", "drinks", "beverage", "beverages", "pantry", "provisions",
    ],
    "sporting-goods": [
        "dumbbell", "dumbbells", "yoga", "yoga mat", "football", "bike",
        "bicycle", "resistance band", "tent", "camping", "fitness", "gym",
        "sport", "sports", "weights", "exercise",
    ],
    "video-games": [
        "playstation", "ps5", "ps4", "xbox", "nintendo", "switch", "console",
        "game", "games", "controller", "gaming", "gaming headset", "fifa",
    ],
    "automotive": [
        "car", "cars", "tyre", "tyres", "tire", "tires", "battery", "dash cam",
        "dashcam", "engine oil", "automotive", "vehicle", "car vacuum",
        "phone holder", "spare part",
    ],
}

STOP_PHRASES = {
    "i want", "i need", "i would like", "i'd like", "looking for", "find me",
    "show me", "help me find", "help me", "please", "can you", "do you have",
    "any", "some", "good", "nice", "the best", "recommend", "suggest",
    "under", "over", "with", "that", "for me", "around", "about",
    "what", "can", "get", "buy", "afford", "have", "give", "show",
    "something", "anything", "else", "much", "cost", "price", "cheapest",
    # Function words that survive the length filter and pollute retrieval.
    "for", "the", "and", "you", "are", "how", "all", "its", "was", "this",
    "these", "those", "them", "they", "your", "our", "from", "into", "than",
    "when", "where", "which", "who", "why", "not", "but", "does", "did",
}

NUMBER_WORDS = {
    "half": 0.5, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "twenty": 20,
    "thirty": 30, "forty": 40, "fifty": 50, "hundred": 100, "thousand": 1000,
}

INTENTS = (
    "greeting", "help", "thanks", "compare", "gift", "track_order",
    "delivery", "returns", "payment", "warranty", "budget", "recommend",
    "search", "smalltalk",
)

_ALL_CATEGORY_WORDS = {
    word: slug for slug, words in CATEGORY_KEYWORDS.items() for word in words
}

FAQ: dict[str, dict] = {
    "delivery": {
        "title": "Delivery",
        "answer": (
            "Standard delivery lands in 2-5 working days and costs \u20a61,500. "
            "Express delivery is \u20a64,500 and arrives next working day in Lagos, "
            "Abuja and Port Harcourt. Orders above \u20a650,000 ship free, and you can "
            "pay on delivery."
        ),
    },
    "returns": {
        "title": "Returns",
        "answer": (
            "You have 7 days from delivery to return an item for a full refund or "
            "exchange. It needs to be unused and in its original packaging. Start a "
            "return from the order confirmation page and we arrange the pickup."
        ),
    },
    "payment": {
        "title": "Payment",
        "answer": (
            "You can pay on delivery (cash or POS), by debit card, or by bank "
            "transfer. Card details are never stored on this demo store \u2014 checkout "
            "records the order and stops short of taking payment."
        ),
    },
    "warranty": {
        "title": "Warranty",
        "answer": (
            "Electronics, appliances and computing items carry a 12-month seller "
            "warranty; grocery and beauty items are excluded for hygiene reasons. "
            "Keep the order reference \u2014 it is your warranty proof."
        ),
    },
    "track_order": {
        "title": "Tracking",
        "answer": (
            "Your order reference looks like SS-7K2QF9. Open the order confirmation "
            "page to see its status, or ask me again with the reference and I will "
            "pull it up."
        ),
    },
}


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------

def parse_amount(text: str) -> float | None:
    """Parse '200k', '1.5m', '\u20a6150,000', 'fifty thousand' into a number."""
    if not text:
        return None
    cleaned = text.lower().strip()
    cleaned = cleaned.replace(",", "").replace("\u20a6", "").replace("n", "", 0)
    cleaned = re.sub(r"^(n|ngn|naira)\s*", "", cleaned)

    match = re.search(r"(\d+(?:\.\d+)?)\s*(k|m|thousand|million)?", cleaned)
    if match:
        value = float(match.group(1))
        suffix = match.group(2)
        if suffix in ("k", "thousand"):
            value *= 1_000
        elif suffix in ("m", "million"):
            value *= 1_000_000
        if 0 < value:
            return value

    # Word forms: "fifty thousand", "two hundred thousand".
    words = re.findall(r"[a-z]+", cleaned)
    total = 0.0
    current = 0.0
    found = False
    for word in words:
        if word not in NUMBER_WORDS:
            continue
        found = True
        value = NUMBER_WORDS[word]
        if value >= 1000:
            current = max(current, 1.0) * value
            total += current
            current = 0.0
        elif value >= 100:
            current = max(current, 1.0) * value
        else:
            current += value
    if found:
        return total + current
    return None


BUDGET_PATTERNS = [
    (r"(?:what can i (?:get|buy|afford)|what do you have)(?:\s+for|\s+with|\s+under)?\s*:?\s*([\d.,]+\s*(?:k|m|thousand|million)?)", "max"),
    (r"(?:under|below|less than|cheaper than|max(?:imum)?(?: of)?|up to|within|not more than|no more than|budget of|budget is|spend)\s*:?\s*([\d.,]+\s*(?:k|m|thousand|million)?|\u20a6[\d.,]+)", "max"),
    (r"(?:between)\s*([\d.,]+\s*(?:k|m|thousand|million)?)\s*(?:and|-|to)\s*([\d.,]+\s*(?:k|m|thousand|million)?)", "range"),
    (r"(?:over|above|more than|at least|from)\s*([\d.,]+\s*(?:k|m|thousand|million)?)", "min"),
    # "laptop for 700000" — require 4+ digits or a k/m suffix so model numbers
    # like "iphone for 13" are not mistaken for prices.
    (r"\bfor\s+([\d.,]{4,}\s*(?:k|m|thousand|million)?|[\d.,]+\s*(?:k|m|thousand|million))\b", "max"),
]

# A bare amount ("50000", "150k") on its own is a budget question.
_BARE_AMOUNT_RE = re.compile(r"^\s*(?:\u20a6|ngn|n)?\s*([\d.,]+\s*(?:k|m|thousand|million)?)\s*$")


def extract_budget(text: str) -> tuple[float | None, float | None]:
    """Return (min_budget, max_budget) found in the query."""
    lowered = text.lower()
    bare = _BARE_AMOUNT_RE.match(lowered)
    if bare:
        value = parse_amount(bare.group(1))
        if value:
            return (None, value)
    for pattern, kind in BUDGET_PATTERNS:
        match = re.search(pattern, lowered)
        if not match:
            continue
        if kind == "range":
            low = parse_amount(match.group(1))
            high = parse_amount(match.group(2))
            if low and high:
                return (min(low, high), max(low, high))
        else:
            value = parse_amount(match.group(1))
            if value:
                if kind == "max":
                    return (None, value)
                return (value, None)
    return (None, None)


def extract_category(text: str) -> str | None:
    """Pick the category the shopper meant.

    The **earliest** mention wins, with keyword length as the tie-break. Doing
    it the other way round sent "a phone under 200k with a big battery" to
    automotive, because "battery" is longer than "phone".
    """
    lowered = " " + re.sub(r"[^a-z0-9\s]", " ", text.lower()) + " "
    best: tuple[tuple[int, int], str] | None = None
    for word, slug in _ALL_CATEGORY_WORDS.items():
        if len(word) > 4:
            at = lowered.find(word)
        else:
            # Short words must stand alone, so "tv" does not match "dstv".
            at = lowered.find(f" {word} ")
            if at != -1:
                at += 1
        if at == -1:
            continue
        key = (at, -len(word))
        if best is None or key < best[0]:
            best = (key, slug)
    return best[1] if best else None


def extract_brand(text: str) -> str | None:
    lowered = text.lower()
    for brand in sorted(catalog.all_brands(), key=len, reverse=True):
        if re.search(rf"\b{re.escape(brand.lower())}\b", lowered):
            return brand
    return None


def extract_keywords(text: str, category: str | None, brand: str | None) -> str:
    """Strip conversational filler so retrieval sees mostly the product nouns."""
    cleaned = text.lower()
    # Word-boundary replacement, not str.replace: a naive replace would turn
    # "affordable" into "af dable" because it contains "for".
    for phrase in sorted(STOP_PHRASES, key=len, reverse=True):
        cleaned = re.sub(rf"\b{re.escape(phrase)}\b", " ", cleaned)
    if brand:
        cleaned = cleaned.replace(brand.lower(), " ")
    cleaned = re.sub(r"[\d.,]+\s*(k|m|thousand|million)?", " ", cleaned)
    cleaned = re.sub(r"[^a-z0-9\s\-]", " ", cleaned)
    words = [w for w in cleaned.split() if len(w) > 2]
    # Keep the category word in the query; it is a strong retrieval signal.
    return " ".join(words[:12])


class Query:
    """Everything the assistant inferred from one shopper message."""

    def __init__(self, raw: str):
        self.raw = raw
        self.text = (raw or "").strip()
        self.lower = self.text.lower()
        self.intent = "smalltalk"
        self.min_budget, self.max_budget = extract_budget(self.text)
        self.category = extract_category(self.text)
        self.brand = extract_brand(self.text)
        self.compare_terms: list[str] = []
        self.attributes: dict[str, bool] = {}
        self.keywords = ""
        self._classify()

    # -- classification --------------------------------------------------
    def _classify(self) -> None:
        text = self.lower

        compare = re.split(r"\s+(?:vs\.?|versus|or|and)\s+", re.sub(
            r"^(compare|difference between|which is better|what is better)\s+", "", text))
        if re.search(r"\b(compare|vs\.?|versus|difference between)\b", text) and len(compare) >= 2:
            self.intent = "compare"
            self.compare_terms = [c.strip() for c in compare if c.strip()][:2]
            self.keywords = self.text
            return

        if re.search(r"\b(hi|hello|hey|good (morning|afternoon|evening)|how are you)\b", text) \
                and len(text.split()) <= 5:
            self.intent = "greeting"
            return

        if re.search(r"\b(thanks|thank you|thankyou|cheers|appreciate)\b", text):
            self.intent = "thanks"
            return

        if re.search(r"\b(what can you do|help|how do you work|who are you|what are you)\b", text):
            self.intent = "help"
            return

        if re.search(r"\b(track|where is my order|order status|my order)\b", text):
            self.intent = "track_order"
            return

        # Payment is checked before delivery: "do you accept cash on delivery"
        # is a payment question, and the word "delivery" would otherwise win.
        if re.search(r"\b(pay|payment|card|transfer|pos|cash on delivery|cod|pay on delivery)\b", text):
            self.intent = "payment"
            return

        if re.search(r"\b(deliver|delivery|shipping|ship|how long.*(arrive|take)|same day)\b", text):
            self.intent = "delivery"
            return

        if re.search(r"\b(return|refund|exchange|send it back|money back)\b", text):
            self.intent = "returns"
            return

        if re.search(r"\b(warranty|guarantee|faulty|damaged|repair)\b", text) and not self.category:
            self.intent = "warranty"
            return

        if re.search(r"\b(gift|present|birthday|anniversary|for my (wife|husband|mum|mom|dad|sister|brother|friend|son|daughter)|surprise)\b", text):
            self.intent = "gift"
            self.attributes["gift"] = True
            self._extract_attributes()
            # With no other steer, a gift should be a proven crowd-pleaser
            # rather than whatever the keyword match happened to rank first.
            if not any(self.attributes.get(k) for k in ("cheap", "best", "new")):
                self.attributes["popular"] = True
            return

        if re.search(r"\b(cheap|cheapest|affordable|budget|low price|inexpensive)\b", text):
            self.attributes["cheap"] = True
        if re.search(r"\b(best|top|highest rated|quality|premium|flagship|durable)\b", text):
            self.attributes["best"] = True
        if re.search(r"\b(new|newest|latest|recent)\b", text):
            self.attributes["new"] = True
        if re.search(r"\b(fast|express|quick|urgent)\b", text):
            self.attributes["express"] = True

        self.keywords = extract_keywords(self.text, self.category, self.brand)

        if self.max_budget and not self.category and not self.brand and not self.keywords:
            self.intent = "budget"
            # A pure budget question ("what can I get for 50k") has nothing
            # meaningful left to search on, so rank by popularity inside the
            # ceiling rather than by a pointless keyword match.
            self.attributes.setdefault("popular", True)
            return

        if self.max_budget and not self.keywords and not self.category and self.brand:
            self.attributes.setdefault("popular", True)

        searchish = bool(self.category or self.brand or self.keywords or self.max_budget)
        if searchish:
            self.intent = "recommend" if re.search(
                r"\b(recommend|suggest|best|which|what should|advice|option)\b", text) else "search"
        else:
            self.intent = "smalltalk"

    def _extract_attributes(self) -> None:
        for key, pattern in (
            ("cheap", r"\b(cheap|affordable|budget)\b"),
            ("best", r"\b(best|premium|quality)\b"),
            ("new", r"\b(new|latest)\b"),
        ):
            if re.search(pattern, self.lower):
                self.attributes[key] = True

    # -- retrieval -------------------------------------------------------
    def sort_key(self) -> str:
        if self.attributes.get("cheap"):
            return "price-asc"
        if self.attributes.get("best"):
            return "rating"
        if self.attributes.get("new"):
            return "newest"
        if self.attributes.get("popular"):
            return "popular"
        return "relevance"


def parse(query: str) -> Query:
    return Query(query)


# --------------------------------------------------------------------------
# Tier 2: optional LLM prose
# --------------------------------------------------------------------------

def llm_config() -> dict | None:
    """Return the LLM settings when a key is configured, else None."""
    api_key = os.getenv("SHOP_LLM_API_KEY") or os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        return None
    return {
        "api_key": api_key,
        "base_url": (os.getenv("SHOP_LLM_BASE_URL")
                     or "https://api.deepseek.com/v1").rstrip("/"),
        "model": os.getenv("SHOP_LLM_MODEL") or "deepseek-chat",
        "timeout": float(os.getenv("SHOP_LLM_TIMEOUT") or 12),
    }


def llm_enabled() -> bool:
    return llm_config() is not None


SYSTEM_PROMPT = (
    "You are Ama, the shopping assistant for Socratic Shop, a Nigerian online "
    "marketplace. Prices are in Naira (\u20a6). Write 2-4 short sentences answering "
    "the shopper. Recommend ONLY from the PRODUCTS JSON provided; never invent a "
    "product, price or specification, and never claim a discount that is not in "
    "the data. Be concrete about price and fit. If the request is ambiguous, end "
    "with one short clarifying question. Do not use markdown headings or bullet "
    "lists, and do not repeat every product name back to the shopper."
)


def _llm_prose(query: Query, products: list[dict], context_product: dict | None) -> str | None:
    """Ask the model for prose only. Any failure returns None (fall back to rules)."""
    config = llm_config()
    if not config or not products:
        return None
    try:
        import requests  # imported lazily so Tier 1 has no network dependency
    except Exception:
        return None

    payload_products = [
        {
            "title": p["title"],
            "brand": p["brand"],
            "price": p["price"],
            "old_price": p["old_price"],
            "rating": p["rating"],
            "reviews": p["reviews"],
            "subcategory": p["subcategory"],
            "highlights": list((p.get("specs") or {}).items())[:3],
            "tags": p.get("tags", [])[:5],
        }
        for p in products[:4]
    ]

    user_parts = [f"Shopper message: {query.text}"]
    if context_product:
        user_parts.append(f"Product page they are viewing: {context_product['title']}")
    if query.max_budget:
        user_parts.append(f"Budget ceiling detected: \u20a6{query.max_budget:,.0f}")
    user_parts.append("PRODUCTS JSON:\n" + json.dumps(payload_products, ensure_ascii=False))
    user_parts.append("Reply to the shopper in plain prose.")

    try:
        response = requests.post(
            f"{config['base_url']}/chat/completions",
            headers={
                "Authorization": f"Bearer {config['api_key']}",
                "Content-Type": "application/json",
            },
            json={
                "model": config["model"],
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": "\n\n".join(user_parts)},
                ],
                "temperature": 0.4,
                "max_tokens": 320,
            },
            timeout=config["timeout"],
        )
        if response.status_code != 200:
            return None
        data = response.json()
        text = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
        text = (text or "").strip()
        return text or None
    except Exception:
        # Deliberate: a broken key or a slow network must never break the shop.
        return None


# --------------------------------------------------------------------------
# Reply construction
# --------------------------------------------------------------------------

def _chips_for(query: Query, products: list[dict]) -> list[str]:
    chips: list[str] = []
    if query.category:
        label = catalog.category_label(query.category).lower()
        chips.append(f"Cheapest {label}")
        chips.append(f"Best rated {label}")
    elif products:
        chips.append(f"More like {products[0]['title'][:28]}")
    chips.append("What is your delivery policy?")
    chips.append("Show me something under \u20a625,000")
    seen: set[str] = set()
    return [c for c in chips if not (c in seen or seen.add(c))][:4]


def _lead_in(query: Query, count: int) -> str:
    """The opening sentence, built from what was actually understood."""
    bits: list[str] = []

    if query.max_budget and query.min_budget:
        bits.append(f"between {format_naira(query.min_budget)} and {format_naira(query.max_budget)}")
    elif query.max_budget:
        bits.append(f"under {format_naira(query.max_budget)}")
    elif query.min_budget:
        bits.append(f"from {format_naira(query.min_budget)} up")

    if query.category:
        bits.append(catalog.category_label(query.category).lower())
    if query.brand:
        bits.append(query.brand)

    subject = " ".join(bits).strip()
    qualifier = ""
    if query.attributes.get("cheap"):
        qualifier = "cheapest first"
    elif query.attributes.get("best"):
        qualifier = "highest rated first"
    elif query.attributes.get("new"):
        qualifier = "newest first"

    if not count:
        return ""

    if query.attributes.get("gift"):
        opener = "A few gift-safe picks"
    elif query.intent == "budget" and query.max_budget:
        opener = (f"Here {'is' if count == 1 else 'are'} {count} option"
                  f"{'s' if count != 1 else ''} at {format_naira(query.max_budget)} or less")
    elif subject:
        opener = f"Here {'is' if count == 1 else 'are'} {count} option{'s' if count != 1 else ''} for {subject}"
    else:
        opener = f"Here {'is' if count == 1 else 'are'} {count} option{'s' if count != 1 else ''}"

    if qualifier:
        opener += f", {qualifier}"
    return opener + "."


def _pick_line(products: list[dict]) -> str:
    """One sentence naming the strongest result and why."""
    if not products:
        return ""
    top = products[0]
    reasons = []
    if top.get("discount_pct", 0) >= 15:
        reasons.append(f"it is {top['discount_pct']}% off")
    if top.get("rating", 0) >= 4.3 and top.get("reviews", 0) > 100:
        reasons.append(f"rated {top['rating']} by {top['reviews']:,} buyers")
    if top.get("express"):
        reasons.append("eligible for express delivery")
    if not reasons:
        reasons.append(f"{top['sold']:,} sold")
    return f"I would start with the {top['title']} at {format_naira(top['price'])} — {' and '.join(reasons[:2])}."


def _faq_reply(intent: str, orders: list[dict], query: Query) -> dict:
    if intent == "track_order":
        ref_match = re.search(r"\bss-[a-z0-9]{6}\b", query.lower)
        if ref_match:
            ref = ref_match.group(0).upper()
            order = next((o for o in orders if o.get("ref") == ref), None)
            if order:
                status = order.get("status", "Processing")
                return {
                    "reply": (f"Order {ref} is currently {status.lower()}. It has "
                              f"{len(order.get('products', []))} item(s) totalling "
                              f"{format_naira(order.get('total', 0))}, "
                              f"going to {order.get('address', {}).get('city', 'your address')}."),
                    "intent": "track_order",
                }
            return {"reply": (f"I cannot find {ref} in this session. Check the reference on "
                              "your confirmation page — it looks like SS-7K2QF9."),
                    "intent": "track_order"}
        if orders:
            lines = ", ".join(f"{o['ref']} ({o.get('status', 'Processing')})" for o in orders[:3])
            return {"reply": f"You have {len(orders)} order(s) in this session: {lines}.",
                    "intent": "track_order"}
        return {"reply": ("You have not placed an order in this session yet. " + FAQ["track_order"]["answer"]),
                "intent": "track_order"}

    entry = FAQ.get(intent)
    if entry:
        return {"reply": entry["answer"], "intent": intent}
    return {"reply": "Ask me anything about the catalog, delivery or returns.", "intent": intent}


GREETING_REPLY = (
    "Hi, I am Ama \u2014 your shopping assistant. Tell me what you need and I will search "
    "the catalogue, compare options and keep it inside your budget. For example: "
    "\u201ca phone under \u20a6200,000 with a big battery\u201d."
)

HELP_REPLY = (
    "I can search the catalogue in plain language, filter by budget or brand, compare "
    "two products spec by spec, suggest gifts, and answer questions about delivery, "
    "returns, payment and warranty. Try \u201ccompare iPhone 13 and Galaxy A15\u201d or "
    "\u201cwhat can I get for \u20a650,000\u201d."
)


def _search_reply(query: Query, products: list[dict],
                  relaxed: bool) -> str:
    parts = []
    lead = _lead_in(query, len(products))
    if lead:
        parts.append(lead)
    pick = _pick_line(products)
    if pick:
        parts.append(pick)
    if relaxed:
        parts.append("Nothing matched every filter, so I widened the search.")
    return " ".join(parts).strip()


def _compare(query: Query) -> dict:
    """Spec-by-spec comparison of the two best matches for the two terms."""
    picked: list[dict] = []
    for term in query.compare_terms:
        hits = catalog.query_products(q=term, limit=1)
        if hits:
            picked.append(hits[0])
    if len(picked) < 2:
        # Try the whole query as one term before giving up.
        hits = catalog.query_products(q=query.text, limit=2)
        picked = hits[:2]
    if len(picked) < 2:
        return {
            "reply": ("I could not find two products to compare there. Name them "
                      "explicitly, for example \u201ccompare iPhone 13 and Galaxy A15\u201d."),
            "intent": "compare",
            "products": [],
        }

    a, b = picked[0], picked[1]
    spec_keys: list[str] = []
    for product in (a, b):
        for key in (product.get("specs") or {}):
            if key not in spec_keys:
                spec_keys.append(key)

    rows = [
        {"label": "Price", "a": format_naira(a["price"]), "b": format_naira(b["price"])},
        {"label": "Brand", "a": a["brand"], "b": b["brand"]},
        {"label": "Rating", "a": f"{a['rating']} ({a['reviews']:,})",
         "b": f"{b['rating']} ({b['reviews']:,})"},
        {"label": "Sold", "a": f"{a['sold']:,}", "b": f"{b['sold']:,}"},
        {"label": "Delivery", "a": "Express" if a["express"] else "Standard",
         "b": "Express" if b["express"] else "Standard"},
    ]
    for key in spec_keys:
        va = (a.get("specs") or {}).get(key, "\u2014")
        vb = (b.get("specs") or {}).get(key, "\u2014")
        rows.append({"label": key, "a": va, "b": vb})

    cheaper = a if a["price"] <= b["price"] else b
    better = a if a["rating"] >= b["rating"] else b
    verdict = f"The {cheaper['title']} is cheaper at {format_naira(cheaper['price'])}"
    if better["id"] != cheaper["id"]:
        verdict += f", while the {better['title']} scores higher at {better['rating']}\u2605"
    else:
        verdict += " and also scores higher with buyers"
    verdict += ". "

    diff = abs(a["price"] - b["price"])
    verdict += (f"They are {format_naira(diff)} apart. "
                f"Pick the {b['title']} if you want "
                f"{'the higher rating' if better['id'] == b['id'] else 'to save money'}, "
                f"or the {a['title']} for the opposite trade-off.")

    return {
        "reply": verdict,
        "intent": "compare",
        "products": [product_card(a), product_card(b)],
        "comparison": {"columns": [a["title"], b["title"]], "rows": rows,
                       "slugs": [a["slug"], b["slug"]]},
    }


def _gift_reply(query: Query, products: list[dict]) -> str:
    lead = "Gift picks that rarely miss"
    if query.category:
        lead += f" from {catalog.category_label(query.category).lower()}"
    if query.max_budget:
        lead += f" under {format_naira(query.max_budget)}"
    lead += "."
    tail = ("Tell me who it is for and the occasion and I will narrow it down "
            "— or say \u201cwrap it\u201d and I will add gift packaging at checkout.")
    pick = _pick_line(products)
    return " ".join(p for p in (lead, pick, tail) if p)


def respond(query_text: str, history_ids: list[str] | None = None,
            context_product: dict | None = None,
            orders: list[dict] | None = None) -> dict:
    """Answer one shopper message.

    Returns a dict with: reply, products (cards), chips, intent, engine and an
    optional comparison table. Never raises on retrieval problems — an empty
    catalog degrades to an apology plus trending items.
    """
    query = parse(query_text or "")
    orders = orders or []
    history_ids = history_ids or []
    products: list[dict] = []
    comparison = None
    relaxed = False
    engine = "rules"

    if query.intent == "compare":
        result = _compare(query)
        reply = result["reply"]
        products = result.get("products", [])
        comparison = result.get("comparison")
        return {
            "reply": reply, "products": products,
            "chips": ["Show me cheaper alternatives", "What is your return policy?"],
            "intent": "compare", "engine": "rules", "comparison": comparison,
        }

    if query.intent in ("greeting", "help", "thanks", "smalltalk"):
        if query.intent == "greeting":
            reply = GREETING_REPLY
        elif query.intent == "help":
            reply = HELP_REPLY
        elif query.intent == "thanks":
            reply = "Any time. Want me to keep an eye on anything else in the catalogue?"
        else:
            reply = ("I can help with that if you name a product, a category or a "
                     "budget. For example: \u201claptop under \u20a6700,000\u201d.")
        if query.intent in ("greeting", "help", "smalltalk"):
            shelf = catalog.trending(4)
            products = [product_card(p, reason="Trending in the store today") for p in shelf]
        return {"reply": reply, "products": products,
                "chips": ["Phones under \u20a6200,000", "Best laptops",
                          "Track my order", "Delivery policy"],
                "intent": query.intent, "engine": "rules", "comparison": None}

    if query.intent in ("delivery", "returns", "payment", "warranty", "track_order"):
        faq = _faq_reply(query.intent, orders, query)
        # Warranty and delivery questions still deserve relevant products.
        if query.intent in ("delivery", "warranty") and (query.category or query.brand):
            hits = catalog.query_products(q=query.keywords, category=query.category,
                                          limit=3)
            products = [product_card(p) for p in hits]
        return {"reply": faq["reply"], "products": products,
                "chips": ["What can I get for \u20a650,000?", "Show me best sellers",
                          "Compare two phones"],
                "intent": query.intent, "engine": "rules", "comparison": None}

    # -- product retrieval ------------------------------------------------
    filters = {
        "q": query.keywords or None,
        "category": query.category,
        "min_price": int(query.min_budget) if query.min_budget else None,
        "max_price": int(query.max_budget) if query.max_budget else None,
        "sort": query.sort_key(),
    }
    if query.brand:
        filters["brands"] = [query.brand]

    hits = catalog.query_products(**filters, limit=4)

    if not hits:
        relaxed = True
        loose = dict(filters)
        loose.pop("min_price", None)
        loose.pop("max_price", None)
        loose["max_price"] = int(query.max_budget * 1.25) if query.max_budget else None
        hits = catalog.query_products(**loose, limit=4)
    if not hits and (query.category or query.brand):
        relaxed = True
        hits = catalog.query_products(q=query.keywords or None, limit=4)

    if not hits:
        import difflib
        near = difflib.get_close_matches(
            query.keywords or query.text, catalog.all_brands(), n=2, cutoff=0.5)
        reply = ("I could not find anything for that in the catalogue. "
                 + (f"Did you mean {', '.join(near)}? " if near else "")
                 + "Try a category like phones, laptops, grocery or appliances, "
                   "or give me a budget and I will suggest something.")
        products = [product_card(p, reason="Popular right now") for p in catalog.trending(3)]
        return {"reply": reply, "products": products,
                "chips": ["Show me best sellers", "Health and beauty picks",
                          "What is on flash sale?"],
                "intent": query.intent, "engine": "rules", "comparison": None}

    if query.intent == "gift":
        reply = _gift_reply(query, hits)
    else:
        reply = _search_reply(query, hits, relaxed)

    # Personalise the tail when we know what the shopper has been looking at.
    if history_ids and len(hits) >= 2:
        viewed = catalog.product_by_id().get(history_ids[0])
        if viewed:
            reply += f" You looked at the {viewed['title']} earlier — the picks above sit in the same range."

    products = [product_card(p) for p in hits]

    # Tier 2: let a model rewrite the prose around the same retrieved shortlist.
    prose = _llm_prose(query, hits, context_product)
    if prose:
        reply = prose
        engine = "llm"

    return {
        "reply": reply,
        "products": products,
        "chips": _chips_for(query, hits),
        "intent": query.intent,
        "engine": engine,
        "comparison": comparison,
        "understood": {
            "category": query.category,
            "brand": query.brand,
            "max_budget": query.max_budget,
            "min_budget": query.min_budget,
            "sort": query.sort_key(),
        },
    }


def welcome() -> dict:
    """Opening message for the assistant page and the chat drawer."""
    return {
        "reply": (
            "Hi, I am Ama. I know every product in this store, so tell me what you "
            "are shopping for in your own words: a budget, a brand, or the problem "
            "you want solved. I will shortlist the options and explain the trade-offs."
        ),
        "products": [product_card(p, reason="Trending right now") for p in catalog.trending(3)],
        "chips": [
            "Phone under \u20a6200,000 with a big battery",
            "Best laptop for school",
            "I need a gift under \u20a630,000",
            "Compare iPhone 13 and Galaxy A15",
        ],
        "intent": "welcome",
        "engine": "rules",
        "comparison": None,
    }
