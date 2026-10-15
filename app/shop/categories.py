"""Category metadata for the Socratic Shop storefront.

`hue` drives the generated product artwork and the category tiles, so a
category keeps the same visual identity everywhere it appears. `glyph`
names a simple vector shape drawn by ``app.shop.art``.
"""

CATEGORIES = {
    "phones-tablets": {
        "label": "Phones & Tablets",
        "short": "Phones",
        "glyph": "phone",
        "hue": 205,
        "blurb": "Smartphones, tablets and everyday accessories",
    },
    "electronics": {
        "label": "Electronics",
        "short": "Electronics",
        "glyph": "tv",
        "hue": 268,
        "blurb": "Televisions, audio and home entertainment",
    },
    "computing": {
        "label": "Computing",
        "short": "Computing",
        "glyph": "laptop",
        "hue": 190,
        "blurb": "Laptops, monitors, storage and peripherals",
    },
    "home-kitchen": {
        "label": "Home & Kitchen",
        "short": "Home",
        "glyph": "house",
        "hue": 28,
        "blurb": "Cookware, furniture and home essentials",
    },
    "appliances": {
        "label": "Appliances",
        "short": "Appliances",
        "glyph": "washer",
        "hue": 158,
        "blurb": "Fridges, washers and cooling for the home",
    },
    "health-beauty": {
        "label": "Health & Beauty",
        "short": "Beauty",
        "glyph": "bottle",
        "hue": 330,
        "blurb": "Skincare, grooming and personal care",
    },
    "fashion": {
        "label": "Fashion",
        "short": "Fashion",
        "glyph": "shirt",
        "hue": 350,
        "blurb": "Clothing, footwear and bags for everyone",
    },
    "baby-products": {
        "label": "Baby Products",
        "short": "Baby",
        "glyph": "baby",
        "hue": 45,
        "blurb": "Baby care, feeding and nursery gear",
    },
    "grocery": {
        "label": "Grocery",
        "short": "Grocery",
        "glyph": "basket",
        "hue": 96,
        "blurb": "Pantry staples, drinks and household food",
    },
    "sporting-goods": {
        "label": "Sporting Goods",
        "short": "Sports",
        "glyph": "dumbbell",
        "hue": 175,
        "blurb": "Fitness, outdoor and training equipment",
    },
    "video-games": {
        "label": "Video Games",
        "short": "Gaming",
        "glyph": "gamepad",
        "hue": 288,
        "blurb": "Consoles, controllers and play accessories",
    },
    "automotive": {
        "label": "Automotive",
        "short": "Auto",
        "glyph": "car",
        "hue": 216,
        "blurb": "Car care, parts and in-car electronics",
    },
}

CATEGORY_ORDER = list(CATEGORIES.keys())


def category_label(slug: str) -> str:
    """Human label for a category slug, falling back to a title-cased slug."""
    meta = CATEGORIES.get(slug)
    if meta:
        return meta["label"]
    return (slug or "Other").replace("-", " ").title()


def category_hue(slug: str) -> int:
    meta = CATEGORIES.get(slug)
    return meta["hue"] if meta else 210


def category_glyph(slug: str) -> str:
    meta = CATEGORIES.get(slug)
    return meta["glyph"] if meta else "tag"
