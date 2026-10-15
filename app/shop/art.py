"""Generated product artwork.

This demo store ships no photographs. Instead each product gets a deterministic
SVG built from its category hue and a vector glyph, served from
``/shop/img/<slug>.svg``. Two reasons:

* the repository stays text-only and tiny, and the deploy never waits on an
  image CDN or hotlinks someone else's bandwidth;
* the grid stays visually coherent, which is the hard part of a marketplace UI.

To use real photography, set a product's ``image`` field in
``catalog/products.json`` to a URL. :func:`app.shop.serializers.product_card`
prefers that field and the templates fall back to this endpoint.
"""

from __future__ import annotations

from .categories import CATEGORIES, category_glyph, category_hue

# Glyphs are drawn in a 0-100 coordinate box as stroked paths, then scaled.
GLYPHS: dict[str, str] = {
    "phone": (
        '<rect x="31" y="8" width="38" height="84" rx="9"/>'
        '<line x1="43" y1="82" x2="57" y2="82"/>'
        '<line x1="38" y1="19" x2="49" y2="19"/>'
    ),
    "tv": (
        '<rect x="8" y="20" width="84" height="52" rx="6"/>'
        '<line x1="50" y1="72" x2="50" y2="86"/>'
        '<line x1="33" y1="86" x2="67" y2="86"/>'
    ),
    "laptop": (
        '<rect x="22" y="24" width="56" height="38" rx="4"/>'
        '<path d="M12 72 H88 L80 62 H20 Z"/>'
        '<line x1="42" y1="72" x2="58" y2="72"/>'
    ),
    "house": (
        '<path d="M50 12 L88 46 H79 V86 H60 V60 H40 V86 H21 V46 H12 Z"/>'
        '<line x1="50" y1="12" x2="88" y2="46"/>'
    ),
    "washer": (
        '<rect x="18" y="10" width="64" height="80" rx="9"/>'
        '<circle cx="50" cy="58" r="19"/>'
        '<circle cx="32" cy="25" r="4"/>'
        '<line x1="46" y1="25" x2="68" y2="25"/>'
    ),
    "bottle": (
        '<rect x="35" y="30" width="30" height="58" rx="8"/>'
        '<rect x="42" y="12" width="16" height="20" rx="3"/>'
        '<line x1="35" y1="46" x2="65" y2="46"/>'
    ),
    "shirt": (
        '<path d="M30 20 L50 13 L70 20 L87 35 L74 47 L74 86 H26 V47 L13 35 Z"/>'
        '<path d="M38 16 Q50 30 62 16"/>'
    ),
    "baby": (
        '<circle cx="50" cy="26" r="14"/>'
        '<path d="M22 86 Q50 44 78 86 Z"/>'
        '<line x1="22" y1="86" x2="78" y2="86"/>'
    ),
    "basket": (
        '<path d="M12 38 H88 L79 84 H21 Z"/>'
        '<path d="M32 38 Q50 10 68 38"/>'
        '<line x1="38" y1="52" x2="38" y2="72"/>'
        '<line x1="62" y1="52" x2="62" y2="72"/>'
    ),
    "dumbbell": (
        '<rect x="30" y="43" width="40" height="14" rx="4"/>'
        '<rect x="17" y="32" width="13" height="36" rx="4"/>'
        '<rect x="70" y="32" width="13" height="36" rx="4"/>'
    ),
    "gamepad": (
        '<rect x="9" y="33" width="82" height="42" rx="20"/>'
        '<circle cx="33" cy="54" r="6"/>'
        '<circle cx="67" cy="54" r="6"/>'
        '<line x1="45" y1="54" x2="55" y2="54"/>'
    ),
    "car": (
        '<path d="M14 62 L22 40 H78 L86 62 V76 H14 Z"/>'
        '<path d="M30 40 L36 26 H64 L70 40"/>'
        '<circle cx="31" cy="78" r="8"/>'
        '<circle cx="69" cy="78" r="8"/>'
    ),
    "tag": (
        '<path d="M52 10 H88 V46 L46 88 L10 52 Z"/>'
        '<circle cx="71" cy="27" r="6"/>'
    ),
}


def _hsl(hue: int, saturation: int, lightness: int) -> str:
    return f"hsl({hue} {saturation}% {lightness}%)"


def _escape(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def initials(title: str, brand: str) -> str:
    """One or two letters for the artwork monogram."""
    words = [w for w in (title or "").split() if w[:1].isalpha()]
    if len(words) >= 2:
        return (words[0][0] + words[1][0]).upper()
    if words:
        return words[0][:2].upper()
    return (brand or "S")[:2].upper()


def product_image_svg(product: dict, variant: int = 0) -> str:
    """Render the deterministic artwork for one product.

    ``variant`` produces the extra gallery angles (0-3) by rotating the glyph,
    shifting the gradient and moving the highlight, so a product page can show a
    real thumbnail strip without shipping four files.
    """
    slug = product.get("slug", "product")
    category = product.get("category", "")
    hue = category_hue(category)
    glyph = GLYPHS.get(category_glyph(category), GLYPHS["tag"])

    variant = variant % 4

    # Offset the hue a little per product so a category row is not flat colour.
    shift = (sum(ord(c) for c in slug) % 26) - 13
    hue_top = (hue + shift + variant * 9) % 360
    hue_bottom = (hue + 24 + shift + variant * 9) % 360

    # Gallery angles: rotate the glyph and re-place the glow.
    rotation = (0, -12, 10, 0)[variant]
    scale = (2.5, 2.15, 2.2, 2.95)[variant]
    glow = ((120, 120), (470, 150), (170, 470), (500, 480))[variant]

    monogram = initials(product.get("title", ""), product.get("brand", ""))
    brand = _escape(product.get("brand", ""))
    label = _escape(CATEGORIES.get(category, {}).get("short", category.replace("-", " ").title()))

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 640" width="640" height="640" role="img" aria-label="{_escape(product.get('title', 'Product'))}">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="0.35" y2="1">
      <stop offset="0%" stop-color="{_hsl(hue_top, 62, 58)}"/>
      <stop offset="100%" stop-color="{_hsl(hue_bottom, 58, 38)}"/>
    </linearGradient>
    <pattern id="dots" width="26" height="26" patternUnits="userSpaceOnUse">
      <circle cx="2" cy="2" r="1.6" fill="#ffffff" opacity="0.13"/>
    </pattern>
    <filter id="soft" x="-20%" y="-20%" width="140%" height="140%">
      <feGaussianBlur stdDeviation="26"/>
    </filter>
  </defs>

  <rect width="640" height="640" fill="url(#bg)"/>
  <rect width="640" height="640" fill="url(#dots)"/>
  <circle cx="{glow[0]}" cy="{glow[1]}" r="150" fill="#ffffff" opacity="0.10" filter="url(#soft)"/>
  <circle cx="{640 - glow[0]}" cy="{640 - glow[1]}" r="190" fill="#ffffff" opacity="0.09" filter="url(#soft)"/>

  <g transform="translate(320 300) rotate({rotation}) scale({scale}) translate(-50 -50)"
     fill="none" stroke="#ffffff" stroke-opacity="0.56" stroke-width="4.5"
     stroke-linecap="round" stroke-linejoin="round">{glyph}</g>

  <text x="48" y="592" font-family="Manrope, Segoe UI, Arial, sans-serif"
        font-size="58" font-weight="800" fill="#ffffff" fill-opacity="0.34"
        letter-spacing="1">{monogram}</text>
  <text x="592" y="592" text-anchor="end" font-family="Segoe UI, Arial, sans-serif"
        font-size="26" font-weight="600" fill="#ffffff" fill-opacity="0.80"
        letter-spacing="2.5">{label}</text>
  <text x="48" y="86" font-family="Segoe UI, Arial, sans-serif"
        font-size="27" font-weight="600" fill="#ffffff" fill-opacity="0.88"
        letter-spacing="0.5">{brand}</text>
</svg>
"""
