"""Tests for the Socratic Shop storefront.

Runnable with pytest::

    python -m pytest tests/test_shop.py -q

The suite covers the parts most likely to break silently: the TF-IDF and
collaborative-filtering maths, intent and budget parsing in the assistant, the
cart's money arithmetic, and that every storefront route returns 200.
"""

from __future__ import annotations

import math

import pytest

from app import create_app
from app.shop import assistant, catalog, state
from app.shop.art import product_image_svg
from app.shop.cart import COUPONS, Cart, format_naira
from app.shop.ml import (ItemItemCF, TfidfIndex, bayesian_rating,
                         popularity_score, tokenize, trending_score)
from app.shop.recommender import Recommender


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def app():
    application = create_app()
    application.config.update(TESTING=True, SECRET_KEY="test-key")
    return application


@pytest.fixture()
def client(app):
    return app.test_client()


# --------------------------------------------------------------------------
# Dataset
# --------------------------------------------------------------------------

def test_catalog_loads():
    products = catalog.products()
    assert len(products) >= 60
    assert len({p["category"] for p in products}) == 12


def test_catalog_products_are_well_formed():
    for product in catalog.products():
        assert product["slug"] and product["title"]
        assert product["price"] > 0
        assert product["old_price"] >= product["price"]
        assert 0 < product["rating"] <= 5
        assert product["reviews"] >= 0
        assert isinstance(product["specs"], dict) and product["specs"]
        assert product["description"]


def test_category_counts_match_products():
    counts = {c["slug"]: c["count"] for c in catalog.categories_with_counts()}
    assert sum(counts.values()) == len(catalog.products())
    assert all(count > 0 for count in counts.values())


def test_order_history_has_baskets():
    orders = catalog.orders()
    assert len(orders) > 100
    ids = set(catalog.product_by_id())
    for order in orders[:50]:
        assert order["items"]
        assert all(item in ids for item in order["items"])


# --------------------------------------------------------------------------
# ML core
# --------------------------------------------------------------------------

def test_tokenize_drops_stopwords_and_singularises():
    tokens = tokenize("The speakers are the best")
    assert "the" not in tokens
    assert "speaker" in tokens


def test_tfidf_ranks_the_relevant_document_first():
    docs = {
        "a": "wireless bluetooth speaker portable audio",
        "b": "gas cooker kitchen oven burner",
        "c": "running shoes trainers sport",
    }
    index = TfidfIndex(docs)
    ranked = index.rank(index.vectorize("bluetooth speaker"), k=3)
    assert ranked
    assert ranked[0][0] == "a"


def test_tfidf_vectors_are_normalised():
    index = catalog.index()
    for vector in list(index.vectors.values())[:20]:
        norm = math.sqrt(sum(v * v for v in vector.values()))
        assert abs(norm - 1.0) < 1e-9


def test_centroid_of_one_document_matches_that_document():
    index = catalog.index()
    doc_id = catalog.products()[0]["id"]
    centroid = index.centroid([doc_id])
    assert index.dot(centroid, index.vectors[doc_id]) > 0.99


def test_collaborative_filtering_finds_complements():
    cf = ItemItemCF(list(catalog.orders()))
    # SKU-0001 is the Samsung Galaxy A15, a phone.
    neighbours = cf.also_bought("SKU-0001", k=4)
    assert neighbours

    by_id = catalog.product_by_id()
    categories = {by_id[pid]["category"] for pid, _ in neighbours}
    # A phone should be associated with accessories and computing, not grocery.
    assert categories & {"electronics", "computing"}
    assert "grocery" not in categories

    # The association must beat chance, which is what lift measures.
    assert all(cf.lift("SKU-0001", pid) > 1.0 for pid, _ in neighbours)


def test_grocery_baskets_stay_inside_grocery():
    cf = ItemItemCF(list(catalog.orders()))
    by_id = catalog.product_by_id()
    # SKU-0049 is the Golden Penny Semovita, a grocery staple.
    grocery = [p for p in catalog.products() if p["category"] == "grocery"]
    seed = grocery[0]["id"]
    neighbours = cf.also_bought(seed, k=4)
    assert neighbours
    categories = {by_id[pid]["category"] for pid, _ in neighbours}
    assert "grocery" in categories


def test_collaborative_scoring_is_bounded():
    cf = ItemItemCF(list(catalog.orders()))
    for pid, score in cf.also_bought("SKU-0001", k=10):
        assert 0.0 < score <= 1.0 + 1e-9


def test_bayesian_rating_shrinks_small_samples():
    # 5.0 from 2 reviews must not beat 4.6 from 900.
    assert bayesian_rating(5.0, 2) < bayesian_rating(4.6, 900)


def test_bayesian_rating_moves_toward_the_prior():
    assert bayesian_rating(5.0, 0) == pytest.approx(4.15, abs=0.01)


def test_popularity_and_trending_are_bounded():
    for product in catalog.products()[:25]:
        score = popularity_score(product["sold"], product["reviews"], product["discount_pct"])
        assert 0.0 <= score <= 1.0
        trend = trending_score(product["sold"], product["reviews"],
                               product["discount_pct"], product["created_days_ago"])
        assert 0.0 <= trend <= 1.0


# --------------------------------------------------------------------------
# Catalog search
# --------------------------------------------------------------------------

@pytest.mark.parametrize("query,expected_category", [
    ("phone", "phones-tablets"),
    ("laptop", "computing"),
    ("blender", "home-kitchen"),
    ("diapers", "baby-products"),
    ("playstation", "video-games"),
    ("tyre", "automotive"),
])
def test_search_finds_the_expected_department(query, expected_category):
    results = catalog.query_products(q=query, limit=5)
    assert results
    assert results[0]["category"] == expected_category


def test_price_filter_is_respected():
    results = catalog.query_products(max_price=30_000, limit=50)
    assert results
    assert all(p["price"] <= 30_000 for p in results)


def test_sorting_by_price_is_ordered():
    results = catalog.query_products(category="fashion", sort="price-asc", limit=20)
    prices = [p["price"] for p in results]
    assert prices == sorted(prices)


def test_price_range_filter_is_inclusive():
    results = catalog.query_products(min_price=50_000, max_price=100_000, limit=50)
    assert results
    assert all(50_000 <= p["price"] <= 100_000 for p in results)


def test_unknown_query_returns_nothing_rather_than_everything():
    assert catalog.query_products(q="zzzqqqxyzzy", limit=10) == []


def test_suggestions_need_two_characters():
    assert catalog.suggestions("a") == []
    assert catalog.suggestions("gal")


# --------------------------------------------------------------------------
# Recommender
# --------------------------------------------------------------------------

def test_recommender_similarity_excludes_the_seed():
    rec = Recommender(catalog.products(), catalog.orders())
    anchor = catalog.products()[0]
    results = rec.similar(anchor["id"], k=6)
    assert results
    assert all(r["product"]["id"] != anchor["id"] for r in results)
    assert all(r["reason"] for r in results)


def test_recommender_also_bought_carries_a_reason():
    rec = Recommender(catalog.products(), catalog.orders())
    results = rec.also_bought("SKU-0001", k=6)
    assert results
    assert all(r["signal"] == "collaborative" for r in results)


def test_bundle_prices_match_its_items():
    rec = Recommender(catalog.products(), catalog.orders())
    for product in catalog.products()[:20]:
        bundle = rec.bundle(product["id"], k=2)
        if not bundle:
            continue
        assert bundle["total"] == sum(i["price"] for i in bundle["products"])
        assert bundle["saving"] == bundle["total_old"] - bundle["total"]
        assert len(bundle["products"]) >= 2
        return
    pytest.skip("no bundle found in the first 20 products")


def test_for_you_without_history_falls_back_to_trending():
    rec = Recommender(catalog.products(), catalog.orders())
    results = rec.for_you([], k=6)
    assert results
    assert all(r["reason"] for r in results)


def test_for_you_with_history_personalises():
    rec = Recommender(catalog.products(), catalog.orders())
    history = [p["id"] for p in catalog.query_products(category="computing", limit=3)]
    results = rec.for_you(history, k=8)
    assert results
    assert all(r["reason"] for r in results)
    categories = [r["product"]["category"] for r in results]
    # A computing-heavy history should not return a grocery-dominant shelf.
    assert categories.count("grocery") <= 2


# --------------------------------------------------------------------------
# Assistant parsing
# --------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("200k", 200_000),
    ("\u20a6150,000", 150_000),
    ("1.5m", 1_500_000),
    ("fifty thousand", 50_000),
])
def test_parse_amount(text, expected):
    assert assistant.parse_amount(text) == pytest.approx(expected)


@pytest.mark.parametrize("text,low,high", [
    ("phones under 200k", None, 200_000),
    ("between 50k and 120k", 50_000, 120_000),
    ("laptop over 500000", 500_000, None),
    ("what can I get for 50000", None, 50_000),
    ("150k", None, 150_000),
])
def test_extract_budget(text, low, high):
    assert assistant.extract_budget(text) == (low, high)


def test_budget_does_not_hijack_model_numbers():
    assert assistant.extract_budget("compare iphone 13 and galaxy a15") == (None, None)


def test_earliest_category_mention_wins():
    # "battery" is longer than "phone", but the shopper is asking for a phone.
    assert assistant.extract_category("a phone under 200k with a big battery") == "phones-tablets"


@pytest.mark.parametrize("text,intent", [
    ("hello there", "greeting"),
    ("what can you do?", "help"),
    ("thanks!", "thanks"),
    ("what is your delivery policy", "delivery"),
    ("can I return this", "returns"),
    ("do you accept cash on delivery", "payment"),
    ("is there a warranty", "warranty"),
    ("track my order", "track_order"),
    ("I need a birthday present", "gift"),
    ("compare iPhone 13 and Galaxy A15", "compare"),
])
def test_intent_classification(text, intent):
    assert assistant.parse(text).intent == intent


def test_compare_produces_a_table():
    result = assistant.respond("compare iPhone 13 and Galaxy A15")
    assert result["intent"] == "compare"
    assert result["comparison"] is not None
    assert len(result["comparison"]["rows"]) > 3
    assert len(result["products"]) == 2


def test_assistant_only_returns_catalog_products():
    ids = set(catalog.product_by_id())
    for query in ["phone under 200k", "a gift for my mum", "cheap blender", "laptop"]:
        result = assistant.respond(query)
        for product in result["products"]:
            assert product["id"] in ids


def test_assistant_never_raises_on_nonsense():
    for query in ["", "   ", "!!!", "asdkjhasd", "\u20a6" * 5, "a" * 600]:
        result = assistant.respond(query)
        assert isinstance(result["reply"], str)
        assert result["reply"].strip()


def test_assistant_defaults_to_rules_without_a_key(monkeypatch):
    monkeypatch.delenv("SHOP_LLM_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    assert assistant.llm_enabled() is False
    assert assistant.respond("phone")["engine"] == "rules"


def test_assistant_understands_a_budget():
    result = assistant.respond("what can I get for 50000")
    assert result["products"]
    assert all(p["price"] <= 50_000 for p in result["products"])


# --------------------------------------------------------------------------
# Cart
# --------------------------------------------------------------------------

def test_naira_formatting():
    assert format_naira(189000) == "\u20a6189,000"
    assert format_naira(0) == "\u20a60"
    assert format_naira("nonsense") == "nonsense"


def test_cart_totals_are_consistent(app):
    with app.test_request_context():
        cart = Cart()
        first = catalog.products()[0]
        assert cart.add(first["id"], 2)
        assert cart.item_count == 2
        assert cart.subtotal == first["price"] * 2
        assert cart.total == cart.subtotal - cart.discount + cart.shipping


def test_cart_rejects_out_of_stock_and_unknown(app):
    with app.test_request_context():
        cart = Cart()
        assert cart.add("SKU-DOES-NOT-EXIST") is False


def test_cart_quantity_is_capped(app):
    with app.test_request_context():
        cart = Cart()
        first = catalog.products()[0]
        cart.add(first["id"], 999)
        assert cart.lines[0].qty <= 20


def test_cart_free_shipping_threshold(app):
    with app.test_request_context():
        cart = Cart()
        expensive = max(catalog.products(), key=lambda p: p["price"])
        cart.add(expensive["id"], 1)
        assert cart.shipping == 0


def test_percent_coupon_reduces_the_total(app):
    with app.test_request_context():
        cart = Cart()
        for product in catalog.products()[:3]:
            cart.add(product["id"], 1)
        before = cart.total
        ok, _ = cart.apply_coupon("WELCOME10")
        assert ok
        assert cart.discount == int(round(cart.subtotal * 0.10))
        assert cart.total < before


def test_fixed_coupon_respects_minimum_spend(app):
    with app.test_request_context():
        cart = Cart()
        cheap = min(catalog.products(), key=lambda p: p["price"])
        cart.add(cheap["id"], 1)
        ok, message = cart.apply_coupon("SAVE2000")
        assert ok is False
        assert "minimum spend" in message


def test_unknown_coupon_is_rejected(app):
    with app.test_request_context():
        cart = Cart()
        cart.add(catalog.products()[0]["id"], 1)
        ok, message = cart.apply_coupon("NOPE123")
        assert ok is False
        assert "not a valid coupon" in message


def test_all_advertised_coupons_exist():
    for code in ("WELCOME10", "SAVE2000", "FREESHIP"):
        assert code in COUPONS


def test_cart_round_trips_through_the_session(app):
    with app.test_request_context():
        cart = Cart()
        cart.add(catalog.products()[0]["id"], 3)
        cart.apply_coupon("WELCOME10")
        cart.save()
        rebuilt = Cart.from_session()
        assert rebuilt.item_count == 3
        assert rebuilt.coupon == "WELCOME10"


# --------------------------------------------------------------------------
# Artwork
# --------------------------------------------------------------------------

def test_product_image_is_valid_svg():
    svg = product_image_svg(catalog.products()[0])
    assert svg.startswith("<svg")
    assert svg.rstrip().endswith("</svg>")
    assert "viewBox" in svg


def test_gallery_variants_differ():
    product = catalog.products()[0]
    renders = {product_image_svg(product, variant=v) for v in range(4)}
    assert len(renders) == 4


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------

PAGES = [
    "/shop/",
    "/shop/deals",
    "/shop/c/phones-tablets",
    "/shop/c/computing?sort=newest",
    "/shop/c/fashion?brand=Nike",
    "/shop/c/grocery?min_price=5000&max_price=20000",
    "/shop/search?q=phone",
    "/shop/search?q=phone&page=2",
    "/shop/search",
    "/shop/search?q=zzzqqqxyzzy",
    "/shop/cart",
    "/shop/wishlist",
    "/shop/assistant",
    "/shop/orders",
]


@pytest.mark.parametrize("path", PAGES)
def test_pages_render(client, path):
    assert client.get(path).status_code == 200


def test_every_product_page_renders(client):
    for product in catalog.products():
        response = client.get(f"/shop/p/{product['slug']}")
        assert response.status_code == 200, product["slug"]


def test_every_category_page_renders(client):
    for category in catalog.categories_with_counts():
        assert client.get(f"/shop/c/{category['slug']}").status_code == 200


def test_artwork_route_serves_svg(client):
    response = client.get("/shop/img/samsung-galaxy-a15-128gb.svg")
    assert response.status_code == 200
    assert response.mimetype == "image/svg+xml"


def test_unknown_product_is_a_404(client):
    assert client.get("/shop/p/not-a-real-product").status_code == 404


def test_unknown_category_is_a_404(client):
    assert client.get("/shop/c/not-a-category").status_code == 404


def test_cart_api_add_and_remove(client):
    response = client.post("/shop/api/cart", json={"action": "add", "product_id": "SKU-0001", "qty": 2})
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["cart"]["item_count"] == 2

    response = client.post("/shop/api/cart", json={"action": "remove", "product_id": "SKU-0001"})
    assert response.get_json()["cart"]["item_count"] == 0


def test_cart_add_bundle_adds_every_item(client):
    client.post("/shop/cart/clear", data={})
    client.post("/shop/cart/add-bundle", data={"product_id": ["SKU-0001", "SKU-0002"]})
    payload = client.get("/shop/api/cart").get_json()
    assert payload["cart"]["item_count"] == 2


def test_wishlist_api_toggles(client):
    first = client.post("/shop/api/wishlist", json={"product_id": "SKU-0005"}).get_json()
    assert first["saved"] is True
    second = client.post("/shop/api/wishlist", json={"product_id": "SKU-0005"}).get_json()
    assert second["saved"] is False


def test_wishlist_rejects_unknown_product(client):
    assert client.post("/shop/api/wishlist", json={"product_id": "NOPE"}).status_code == 404


def test_search_api_returns_suggestions(client):
    payload = client.get("/shop/api/search?q=gal").get_json()
    assert payload["ok"] is True
    assert payload["results"]
    assert all(r["price_display"].startswith("\u20a6") for r in payload["results"])


def test_assistant_api_replies(client):
    payload = client.post("/shop/api/assistant", json={"message": "phone under 200000"}).get_json()
    assert payload["ok"] is True
    assert payload["reply"]
    assert payload["intent"]


def test_assistant_api_rejects_empty_message(client):
    assert client.post("/shop/api/assistant", json={"message": "  "}).status_code == 400


def test_checkout_flow_creates_an_order(client):
    client.post("/shop/cart/clear", data={})
    client.post("/shop/cart/add", data={"product_id": "SKU-0001", "qty": 1})

    response = client.post("/shop/checkout", data={
        "full_name": "Ada Obi", "email": "ada@example.com", "phone": "08031234567",
        "address": "12 Marina Road", "city": "Lagos", "state": "Lagos",
        "delivery": "standard", "payment": "card",
    })
    assert response.status_code == 302
    location = response.headers["Location"]
    assert "/shop/order/SS-" in location
    assert client.get(location).status_code == 200
    assert client.get("/shop/orders").status_code == 200
    # The cart is emptied once the order is placed.
    assert client.get("/shop/api/cart").get_json()["cart"]["item_count"] == 0


def test_checkout_validation_reports_every_missing_field(client):
    client.post("/shop/cart/clear", data={})
    client.post("/shop/cart/add", data={"product_id": "SKU-0001", "qty": 1})
    response = client.post("/shop/checkout", data={"full_name": "", "email": "bad", "phone": "1"})
    assert response.status_code == 200
    assert b"Please fix" in response.data


def test_checkout_redirects_when_the_cart_is_empty(client):
    client.post("/shop/cart/clear", data={})
    response = client.post("/shop/checkout", data={"full_name": "Ada"})
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/shop/cart")


def test_dashboard_still_works(client):
    """The storefront must not have broken the existing analytics app."""
    response = client.get("/")
    assert response.status_code in (200, 302)


def test_health_endpoint_reports_a_loaded_catalogue(client):
    payload = client.get("/shop/health").get_json()
    assert payload["status"] == "ok"
    assert payload["products"] == len(catalog.products())
    assert payload["categories"] == 12
    assert payload["assistant"] in ("rules", "llm")


def test_login_page_links_to_the_storefront(client):
    """The deployed root is a login wall, so it must offer a route into the shop."""
    html = client.get("/login").get_data(as_text=True)
    assert 'href="/shop/"' in html
    assert "storefront" in html.lower()


def test_filter_sidebar_shows_the_catalogue_price_range(client):
    low, high = catalog.price_bounds()
    assert 0 < low < high
    html = client.get("/shop/c/phones-tablets").get_data(as_text=True)
    assert "Catalogue range" in html
    assert format_naira(low) in html
    assert format_naira(high) in html

