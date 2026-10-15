"""Storefront views and the JSON API behind the live UI.

Route layout:

    /shop/                     home
    /shop/c/<slug>             category listing
    /shop/p/<slug>             product detail
    /shop/search               search results with filters
    /shop/deals                flash sale
    /shop/cart                 cart page
    /shop/checkout             checkout form (GET/POST)
    /shop/order/<ref>          order confirmation
    /shop/orders               orders placed in this session
    /shop/wishlist             saved items
    /shop/assistant            full-page AI assistant
    /shop/img/<slug>.svg       generated product artwork

    /shop/api/cart             GET summary, POST mutations
    /shop/api/assistant        POST a chat message
    /shop/api/search           GET autocomplete suggestions
    /shop/api/wishlist         POST toggle
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from flask import (flash, jsonify, redirect, render_template, request,
                   url_for, Response)

from . import catalog, state
from .art import product_image_svg
from .assistant import FAQ, llm_enabled
from .assistant import respond as assistant_respond
from .assistant import welcome as assistant_welcome
from .blueprint import shop
from .cart import (COUPONS, FREE_SHIPPING_THRESHOLD, STANDARD_SHIPPING, Cart,
                   format_naira)
from .categories import CATEGORIES
from .recommender import get_recommender
from .reviews import rating_breakdown, reviews_for
from .serializers import (category_url, image_url, product_card, product_url,
                          recommendation_cards)

PER_PAGE = 12

# --------------------------------------------------------------------------
# Template plumbing
# --------------------------------------------------------------------------

@shop.app_template_filter("naira")
def naira_filter(value) -> str:
    return format_naira(value)


@shop.app_context_processor
def inject_shop_globals() -> dict:
    """Data every storefront template needs: nav, badges and brand constants."""
    cart = Cart.from_session()
    return {
        "shop_categories": catalog.categories_with_counts(),
        "shop_cart_count": cart.item_count,
        "shop_wishlist_count": len(state.wishlist_ids()),
        "shop_llm_enabled": llm_enabled(),
        "shop_free_shipping_threshold": FREE_SHIPPING_THRESHOLD,
        "shop_standard_shipping": STANDARD_SHIPPING,
        "shop_coupons": COUPONS,
        "shop_sort_options": catalog.SORT_OPTIONS,
        "shop_year": datetime.now(timezone.utc).year,
        "shop_assistant_intro": assistant_welcome(),
        "shop_price_bounds": catalog.price_bounds(),
    }


# These four are registered as Jinja *globals* rather than context-processor
# entries on purpose: macros in _macros.html are imported without `with
# context`, so they can only see globals and filters, not the request context.
shop.app_template_global("shop_category_url")(category_url)
shop.app_template_global("shop_product_url")(product_url)
shop.app_template_global("shop_image_url")(image_url)


def _page_url(page: int) -> str:
    """Current URL with the ``page`` argument replaced, for pagination links."""
    args = request.args.to_dict()
    args["page"] = page
    endpoint = request.endpoint
    if not endpoint:
        return "?"
    try:
        return url_for(endpoint, **(request.view_args or {}), **args)
    except Exception:
        # A route without the expected arguments should never break rendering.
        args.pop("page", None)
        query = "&".join(f"{k}={v}" for k, v in args.items())
        return f"?page={page}" + (f"&{query}" if query else "")


shop.app_template_global("shop_page_url")(_page_url)


def paginate(items: list, page: int, per_page: int = PER_PAGE) -> dict:
    total = len(items)
    pages = max(1, math.ceil(total / per_page))
    page = min(max(page, 1), pages)
    start = (page - 1) * per_page
    return {
        # NB: key is "products", not "items" — in Jinja, `page_data.items`
        # resolves to the dict's own .items method, not this value.
        "products": items[start:start + per_page],
        "page": page,
        "pages": pages,
        "total": total,
        "has_prev": page > 1,
        "has_next": page < pages,
        "prev_page": page - 1,
        "next_page": page + 1,
        "first_index": start + 1 if total else 0,
        "last_index": min(start + per_page, total),
    }


def _card_page(page_data: dict) -> dict:
    """Swap raw catalog rows for serializer cards so templates get one shape."""
    page_data["products"] = [product_card(p) for p in page_data["products"]]
    return page_data


def _int_arg(name: str, default=None):
    raw = request.args.get(name)
    if raw in (None, ""):
        return default
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return default


def _float_arg(name: str, default=None):
    raw = request.args.get(name)
    if raw in (None, ""):
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def flash_deadline_iso() -> str:
    """Next 6-hour boundary, so the flash countdown is real and always resets."""
    now = datetime.now(timezone.utc)
    hours = 6 - (now.hour % 6)
    deadline = (now + timedelta(hours=hours)).replace(minute=0, second=0, microsecond=0)
    return deadline.isoformat()


def _assistant_context() -> dict:
    """Session-derived context shared by the assistant page and the chat API."""
    return {
        "history": state.viewed_ids(),
        "orders": state.list_orders(),
    }


# --------------------------------------------------------------------------
# Storefront pages
# --------------------------------------------------------------------------

@shop.route("/")
def home():
    recommender = get_recommender()
    history = state.viewed_ids()

    for_you = recommender.for_you(history, k=12)
    # Do not show the same products twice on one page.
    shown = {r["product"]["id"] for r in for_you}
    trending = recommender.trending_shelf(k=12, exclude=shown)
    shown |= {r["product"]["id"] for r in trending}
    quality = recommender.quality_shelf(k=8, exclude=shown)

    recently_viewed = [
        product_card(catalog.product_by_id()[pid]) for pid in history[:6]
        if pid in catalog.product_by_id()
    ]

    return render_template(
        "shop/home.html",
        hero_slides=HERO_SLIDES,
        flash=[product_card(p) for p in catalog.flash_products(10)],
        flash_deadline=flash_deadline_iso(),
        for_you=recommendation_cards(for_you),
        trending=recommendation_cards(trending),
        quality=recommendation_cards(quality),
        recently_viewed=recently_viewed,
        brands=catalog.all_brands(),
        assistant_intro=assistant_welcome(),
    )


@shop.route("/c/<slug>")
def category(slug: str):
    if slug not in CATEGORIES:
        return render_template("shop/not_found.html",
                               message=f"Category “{slug}” does not exist."), 404

    brands = request.args.getlist("brand") or None
    page = _int_arg("page", 1) or 1
    sort = request.args.get("sort", "popular")

    results = catalog.query_products(
        category=slug, brands=brands,
        min_price=_int_arg("min_price"), max_price=_int_arg("max_price"),
        min_rating=_float_arg("min_rating"),
        express=request.args.get("express") == "1",
        flash=request.args.get("flash") == "1",
        sort=sort,
    )
    meta = CATEGORIES[slug]
    recommender = get_recommender()

    return render_template(
        "shop/category.html",
        category_slug=slug,
        category=meta,
        page_data=_card_page(paginate(results, page)),
        facets=catalog.facets(results),
        active={"brands": brands or [], "min_price": _int_arg("min_price"),
                "max_price": _int_arg("max_price"),
                "min_rating": _float_arg("min_rating"),
                "express": request.args.get("express") == "1",
                "flash": request.args.get("flash") == "1",
                "sort": sort},
        picks=recommendation_cards(recommender.rank_products(results, k=4)),
    )


@shop.route("/p/<slug>")
def product_detail(slug: str):
    product = catalog.get_product(slug)
    if not product:
        return render_template("shop/not_found.html",
                               message="We could not find that product."), 404

    state.record_view(product["id"])
    recommender = get_recommender()

    similar = recommender.similar(product["id"], k=8)
    also_bought = recommender.also_bought(product["id"], k=8)
    bundle = recommender.bundle(product["id"], k=2)

    # Keep the three shelves distinct.
    seen = {product["id"]}
    also_bought = [r for r in also_bought if r["product"]["id"] not in seen]
    seen |= {r["product"]["id"] for r in also_bought}
    similar = [r for r in similar if r["product"]["id"] not in seen]

    return render_template(
        "shop/product.html",
        product=product,
        gallery=[f"{image_url(product['slug'])}?v={v}" for v in range(4)],
        reviews=reviews_for(product),
        breakdown=rating_breakdown(product),
        bundle=bundle,
        also_bought=recommendation_cards(also_bought),
        similar=recommendation_cards(similar),
        related=[product_card(p) for p in catalog.related_by_category(product, limit=6)],
        in_wishlist=state.in_wishlist(product["id"]),
        delivery_from=(datetime.now(timezone.utc) + timedelta(days=2)).strftime("%a %d %b"),
        delivery_to=(datetime.now(timezone.utc) + timedelta(days=5)).strftime("%a %d %b"),
    )


@shop.route("/search")
def search():
    q = (request.args.get("q") or "").strip()
    page = _int_arg("page", 1) or 1
    sort = request.args.get("sort", "relevance")
    brands = request.args.getlist("brand") or None

    results = catalog.query_products(
        q=q or None, category=request.args.get("category"),
        brands=brands,
        min_price=_int_arg("min_price"), max_price=_int_arg("max_price"),
        min_rating=_float_arg("min_rating"),
        express=request.args.get("express") == "1",
        sort=sort,
    ) if q else []

    recommender = get_recommender()
    page_data = _card_page(paginate(results, page))

    # When a search finds nothing, offer the AI a chance to interpret it.
    ai_hint = None
    if q and not results:
        ai_hint = assistant_respond(q, history_ids=state.viewed_ids(),
                                    orders=state.list_orders())

    return render_template(
        "shop/search.html",
        q=q,
        page_data=page_data,
        facets=catalog.facets(results) if results else None,
        active={"brands": brands or [], "min_price": _int_arg("min_price"),
                "max_price": _int_arg("max_price"),
                "min_rating": _float_arg("min_rating"),
                "express": request.args.get("express") == "1",
                "sort": sort, "category": request.args.get("category")},
        ai_hint=ai_hint,
        fallback=recommendation_cards(recommender.trending_shelf(k=8)) if not results else [],
    )


@shop.route("/deals")
def deals():
    flash = catalog.flash_products(24)
    return render_template(
        "shop/deals.html",
        flash=[product_card(p) for p in flash],
        flash_deadline=flash_deadline_iso(),
        trending=recommendation_cards(get_recommender().trending_shelf(k=8)),
    )


@shop.route("/cart")
def cart_page():
    cart = Cart.from_session()
    recommender = get_recommender()
    in_cart = {line.product["id"] for line in cart.lines}
    suggestions = recommendation_cards(
        recommender.for_you(state.viewed_ids(), k=8, exclude=in_cart))
    return render_template("shop/cart.html", cart=cart, suggestions=suggestions)


@shop.route("/wishlist")
def wishlist():
    by_id = catalog.product_by_id()
    items = [by_id[pid] for pid in state.wishlist_ids() if pid in by_id]
    recommender = get_recommender()
    exclude = {p["id"] for p in items}
    return render_template(
        "shop/wishlist.html",
        items=[product_card(p) for p in items],
        suggestions=recommendation_cards(
            recommender.for_you(state.viewed_ids(), k=8, exclude=exclude)),
    )


@shop.route("/assistant")
def assistant_page():
    context = _assistant_context()
    return render_template(
        "shop/assistant.html",
        intro=assistant_welcome(),
        faq=FAQ,
        llm_enabled=llm_enabled(),
        context_product=None,
        **context,
    )


@shop.route("/orders")
def orders_page():
    return render_template("shop/orders.html", orders=state.list_orders())


# --------------------------------------------------------------------------
# Cart mutations (form posts, so the store works without JavaScript)
# --------------------------------------------------------------------------

def _back_to(default_endpoint: str = "shop.cart_page"):
    """Redirect to the form's ``next`` target, but only within this site."""
    target = request.form.get("next") or request.args.get("next")
    if target and target.startswith("/") and not target.startswith("//"):
        return redirect(target)
    return redirect(url_for(default_endpoint))


@shop.route("/cart/add", methods=["POST"])
def cart_add():
    product_id = request.form.get("product_id", "")
    try:
        qty = max(1, int(request.form.get("qty", 1)))
    except (TypeError, ValueError):
        qty = 1

    cart = Cart.from_session()
    if cart.add(product_id, qty):
        cart.save()
        flash("Added to your cart.", "success")
    else:
        flash("That item is not available right now.", "error")
    return _back_to()


@shop.route("/cart/add-bundle", methods=["POST"])
def cart_add_bundle():
    """Add every item of a 'frequently bought together' set in one action."""
    cart = Cart.from_session()
    added = 0
    for product_id in request.form.getlist("product_id"):
        if cart.add(product_id, 1):
            added += 1
    cart.save()
    if added:
        flash(f"Added {added} item{'s' if added != 1 else ''} to your cart.", "success")
    else:
        flash("Those items are not available right now.", "error")
    return _back_to()


@shop.route("/cart/update", methods=["POST"])
def cart_update():
    cart = Cart.from_session()
    for key, value in request.form.items():
        if key.startswith("qty_"):
            try:
                cart.set_qty(key[4:], int(value))
            except (TypeError, ValueError):
                continue
    cart.save()
    return _back_to()


@shop.route("/cart/remove", methods=["POST"])
def cart_remove():
    cart = Cart.from_session()
    cart.remove(request.form.get("product_id", ""))
    cart.save()
    return _back_to()


@shop.route("/cart/clear", methods=["POST"])
def cart_clear():
    cart = Cart.from_session()
    cart.clear()
    cart.save()
    return _back_to()


@shop.route("/cart/coupon", methods=["POST"])
def cart_coupon():
    cart = Cart.from_session()
    if request.form.get("remove"):
        cart.remove_coupon()
        flash("Coupon removed.", "info")
    else:
        code = request.form.get("code", "")
        ok, message = cart.apply_coupon(code)
        flash(message, "success" if ok else "error")
    cart.save()
    return _back_to()


# --------------------------------------------------------------------------
# Checkout
# --------------------------------------------------------------------------

CHECKOUT_FIELDS = [
    ("full_name", "Full name"),
    ("email", "Email address"),
    ("phone", "Phone number"),
    ("address", "Street address"),
    ("city", "City"),
    ("state", "State"),
]


def _validate_checkout(form) -> tuple[dict, list[str]]:
    values = {name: (form.get(name) or "").strip() for name, _ in CHECKOUT_FIELDS}
    values["delivery"] = form.get("delivery", "standard")
    values["payment"] = form.get("payment", "card")
    values["notes"] = (form.get("notes") or "").strip()[:400]

    errors: list[str] = []
    for name, label in CHECKOUT_FIELDS:
        if not values[name]:
            errors.append(f"{label} is required.")
    if values["email"] and "@" not in values["email"]:
        errors.append("Enter a valid email address.")
    if values["phone"]:
        digits = [c for c in values["phone"] if c.isdigit()]
        if len(digits) < 10:
            errors.append("Enter a valid phone number (at least 10 digits).")
    if values["delivery"] not in ("standard", "express"):
        values["delivery"] = "standard"
    if values["payment"] not in ("card", "transfer", "cod"):
        values["payment"] = "card"
    return values, errors


@shop.route("/checkout", methods=["GET", "POST"])
def checkout():
    cart = Cart.from_session()
    if not cart.lines:
        return redirect(url_for("shop.cart_page"))

    values: dict = {}
    errors: list[str] = []

    if request.method == "POST":
        values, errors = _validate_checkout(request.form)
        if not errors:
            cart.express = values["delivery"] == "express"
            cart.save()

            eta_days = 1 if cart.express else 4
            eta = (datetime.now(timezone.utc) + timedelta(days=eta_days)).strftime("%A %d %B %Y")
            order = {
                "ref": state.new_order_ref(),
                "created": state.utcnow_iso(),
                "status": "Processing",
                "eta": eta,
                "products": [
                    {
                        "id": l.product["id"],
                        "slug": l.product["slug"],
                        "title": l.product["title"],
                        "qty": l.qty,
                        "price": l.product["price"],
                        "price_display": format_naira(l.product["price"]),
                    }
                    for l in cart.lines
                ],
                "item_count": cart.item_count,
                "subtotal": cart.subtotal,
                "discount": cart.discount,
                "shipping": cart.shipping,
                "total": cart.total,
                "coupon": cart.coupon,
                "address": {k: values[k] for k, _ in CHECKOUT_FIELDS},
                "delivery": values["delivery"],
                "payment": values["payment"],
                "notes": values["notes"],
            }
            state.save_order(order)
            cart.clear()
            cart.save()
            return redirect(url_for("shop.order_confirmation", ref=order["ref"]))

    return render_template(
        "shop/checkout.html", cart=cart, values=values, errors=errors,
        fields=CHECKOUT_FIELDS, step=2,
    )


@shop.route("/order/<ref>")
def order_confirmation(ref: str):
    order = state.get_order(ref)
    if not order:
        return render_template(
            "shop/not_found.html",
            message=f"We have no record of order {ref} in this session."), 404
    recommender = get_recommender()
    ordered = {i["id"] for i in order["products"]}
    return render_template(
        "shop/order.html", order=order,
        suggestions=recommendation_cards(
            recommender.for_you([i["id"] for i in order["products"]], k=6, exclude=ordered)),
    )


# --------------------------------------------------------------------------
# Generated artwork
# --------------------------------------------------------------------------

@shop.route("/img/<slug>.svg")
def product_image(slug: str):
    product = catalog.get_product(slug)
    if not product:
        # Fall back to a neutral tile rather than a broken image.
        product = {"slug": slug, "title": "Product", "brand": "Socratic",
                   "category": "electronics"}
    try:
        variant = int(request.args.get("v", 0))
    except (TypeError, ValueError):
        variant = 0

    svg = product_image_svg(product, variant=variant)
    return Response(svg, mimetype="image/svg+xml", headers={
        "Cache-Control": "public, max-age=604800, immutable",
    })


# --------------------------------------------------------------------------
# JSON API
# --------------------------------------------------------------------------

@shop.route("/api/cart", methods=["GET", "POST"])
def api_cart():
    """Cart JSON API.

    Every response — success, coupon failure or unknown action — uses the same
    shape, ``{"ok", "message", "cart"}``, so the client only ever has to read
    one structure.
    """
    cart = Cart.from_session()
    message = None
    ok = True

    if request.method == "POST":
        data = request.get_json(silent=True) or request.form
        action = (data.get("action") or "").strip()
        product_id = data.get("product_id") or ""

        if action == "add":
            try:
                qty = max(1, int(data.get("qty", 1)))
            except (TypeError, ValueError):
                qty = 1
            if cart.add(product_id, qty):
                message = "Added to cart"
            else:
                message = "That item is out of stock"
                ok = False
        elif action == "set":
            try:
                cart.set_qty(product_id, int(data.get("qty", 1)))
            except (TypeError, ValueError):
                pass
        elif action == "remove":
            cart.remove(product_id)
            message = "Removed from cart"
        elif action == "clear":
            cart.clear()
            message = "Cart cleared"
        elif action == "coupon":
            ok, message = cart.apply_coupon(data.get("code", ""))
            cart.save()
            return jsonify({"ok": ok, "message": message, "cart": cart.to_dict()})
        elif action == "express":
            cart.express = str(data.get("value", "1")) in ("1", "true", "True", "on")
        else:
            return jsonify({"ok": False, "message": "Unknown action",
                            "cart": cart.to_dict()}), 400

        cart.save()

    return jsonify({"ok": ok, "message": message, "cart": cart.to_dict()})


@shop.route("/api/search")
def api_search():
    q = request.args.get("q", "")
    limit = _int_arg("limit", 6) or 6
    return jsonify({
        "ok": True,
        "query": q,
        "results": [product_card(p) for p in catalog.suggestions(q, limit=max(1, min(limit, 12)))],
    })


@shop.route("/api/assistant", methods=["POST"])
def api_assistant():
    data = request.get_json(silent=True) or request.form
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"ok": False, "message": "Say something and I will help."}), 400
    if len(message) > 600:
        message = message[:600]

    context_slug = data.get("context_product")
    context_product = catalog.get_product(context_slug) if context_slug else None

    result = assistant_respond(
        message,
        history_ids=state.viewed_ids(),
        context_product=context_product,
        orders=state.list_orders(),
    )
    result["ok"] = True
    return jsonify(result)


@shop.route("/api/wishlist", methods=["POST"])
def api_wishlist():
    data = request.get_json(silent=True) or request.form
    product_id = data.get("product_id", "")
    if product_id not in catalog.product_by_id():
        return jsonify({"ok": False, "message": "Unknown product"}), 404
    saved = state.toggle_wishlist(product_id)
    return jsonify({
        "ok": True,
        "saved": saved,
        "count": len(state.wishlist_ids()),
        "message": "Saved to wishlist" if saved else "Removed from wishlist",
    })


# --------------------------------------------------------------------------
# Home page hero content
# --------------------------------------------------------------------------

HERO_SLIDES = [
    {
        "eyebrow": "Ask Ama, shop instantly",
        "title": "Not sure what to buy? Describe it.",
        "body": ("Tell the assistant your budget, your brand or the problem you want "
                 "solved. It searches the whole catalogue and explains the trade-offs "
                 "before you spend a naira."),
        "cta": "Open the AI assistant",
        "url": "/shop/assistant",
        "accent": "#0F6E63",
        "glyph": "assistant",
    },
    {
        "eyebrow": "Flash sale \u00b7 ends soon",
        "title": "Up to 34% off, today only",
        "body": ("Discounted stock across phones, appliances, computing and grocery. "
                 "The countdown resets every six hours and the price you see is the "
                 "price you pay."),
        "cta": "Shop flash deals",
        "url": "/shop/deals",
        "accent": "#B7791F",
        "glyph": "flash",
    },
    {
        "eyebrow": "Pay on delivery",
        "title": "Free delivery over \u20a650,000",
        "body": ("Order now, pay when it reaches your door. Standard delivery in 2-5 "
                 "working days, express next-day in Lagos, Abuja and Port Harcourt."),
        "cta": "Browse all categories",
        "url": "/shop/c/phones-tablets",
        "accent": "#4A6FA5",
        "glyph": "truck",
    },
]
