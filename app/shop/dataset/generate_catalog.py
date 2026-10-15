"""Generate the Socratic Shop catalog and synthetic order history.

Run from the project root:

    python -m app.shop.dataset.generate_catalog

Writes ``products.json`` and ``orders.json`` next to this file. The output is
deterministic: everything that looks random (ratings, units sold, discounts,
order baskets) is derived from a fixed seed or a hash of the product slug, so
re-running never churns the committed dataset.

The order history is synthetic on purpose. It exists so the recommender has a
real item-to-item co-purchase signal to learn from, which is the same shape of
data a production store would feed it from its orders table.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from pathlib import Path

from app.shop.categories import CATEGORIES

HERE = Path(__file__).resolve().parent

# --------------------------------------------------------------------------
# Catalog source data
# (name, brand, subcategory, price in NGN, tags, specs)
# --------------------------------------------------------------------------
ITEMS: dict[str, list[tuple]] = {
    "phones-tablets": [
        ("Samsung Galaxy A15 128GB", "Samsung", "Smartphones", 189000,
         ["smartphone", "android", "amoled", "dual sim", "4g"],
         {"Display": "6.5\" Super AMOLED", "Battery": "5000mAh", "Camera": "50MP triple", "Storage": "128GB / 4GB RAM"}),
        ("Tecno Spark 20 Pro 256GB", "Tecno", "Smartphones", 165500,
         ["smartphone", "android", "budget", "big battery", "dual sim"],
         {"Display": "6.78\" 120Hz", "Battery": "5000mAh", "Camera": "108MP", "Storage": "256GB / 8GB RAM"}),
        ("Infinix Hot 40i 128GB", "Infinix", "Smartphones", 132000,
         ["smartphone", "android", "budget", "dual sim"],
         {"Display": "6.6\" 90Hz", "Battery": "5000mAh", "Camera": "50MP", "Storage": "128GB / 8GB RAM"}),
        ("Xiaomi Redmi Note 13 256GB", "Xiaomi", "Smartphones", 248000,
         ["smartphone", "android", "amoled", "fast charging"],
         {"Display": "6.67\" AMOLED 120Hz", "Battery": "5000mAh", "Charging": "33W fast", "Storage": "256GB / 8GB RAM"}),
        ("Apple iPhone 13 128GB", "Apple", "Smartphones", 725000,
         ["smartphone", "ios", "premium", "5g", "camera"],
         {"Display": "6.1\" Super Retina XDR", "Chip": "A15 Bionic", "Camera": "Dual 12MP", "Storage": "128GB"}),
        ("Samsung Galaxy Tab A9+ 64GB", "Samsung", "Tablets", 315000,
         ["tablet", "android", "wifi", "streaming"],
         {"Display": "11\" TFT 90Hz", "Battery": "7040mAh", "Storage": "64GB / 4GB RAM", "Audio": "Quad speakers"}),
    ],
    "electronics": [
        ("LG 43\" Smart LED TV", "LG", "Televisions", 385000,
         ["tv", "smart tv", "4k", "netflix"],
         {"Screen": "43\" LED", "Resolution": "Full HD", "Smart": "webOS", "Ports": "3x HDMI"}),
        ("Hisense 55\" 4K UHD Smart TV", "Hisense", "Televisions", 520000,
         ["tv", "smart tv", "4k", "uhd"],
         {"Screen": "55\" UHD", "Resolution": "3840x2160", "Smart": "VIDAA", "HDR": "HDR10"}),
        ("Sony WH-CH520 Wireless Headphones", "Sony", "Audio", 78000,
         ["headphones", "bluetooth", "wireless", "audio"],
         {"Battery": "50 hours", "Connectivity": "Bluetooth 5.2", "Type": "On-ear", "Mic": "Built-in"}),
        ("JBL Go 4 Bluetooth Speaker", "JBL", "Audio", 55000,
         ["speaker", "bluetooth", "portable", "waterproof"],
         {"Output": "4.2W", "Battery": "7 hours", "Rating": "IP67 waterproof", "Connectivity": "Bluetooth 5.3"}),
        ("Oraimo 60W Sound Bar", "Oraimo", "Audio", 96000,
         ["soundbar", "audio", "home theatre", "bluetooth"],
         {"Output": "60W", "Channels": "2.1", "Connectivity": "Bluetooth / HDMI / AUX", "Remote": "Included"}),
        ("DStv Explora Decoder", "DStv", "TV Accessories", 88000,
         ["decoder", "dstv", "satellite", "tv"],
         {"Recording": "Dual-view recording", "Storage": "1TB HDD", "Output": "1080p", "Catch-up": "Yes"}),
    ],
    "computing": [
        ("HP 250 G9 Core i5 8GB/512GB", "HP", "Laptops", 685000,
         ["laptop", "windows", "business", "ssd"],
         {"Processor": "Intel Core i5 12th Gen", "Memory": "8GB DDR4", "Storage": "512GB SSD", "Display": "15.6\" FHD"}),
        ("Lenovo IdeaPad Slim 3 Ryzen 5", "Lenovo", "Laptops", 610000,
         ["laptop", "windows", "student", "ssd"],
         {"Processor": "AMD Ryzen 5 7000", "Memory": "8GB DDR4", "Storage": "512GB SSD", "Display": "15.6\" FHD"}),
        ("Apple MacBook Air M2 13\"", "Apple", "Laptops", 1450000,
         ["laptop", "macos", "premium", "lightweight"],
         {"Chip": "Apple M2", "Memory": "8GB unified", "Storage": "256GB SSD", "Battery": "Up to 18 hours"}),
        ("Dell 24\" FHD IPS Monitor", "Dell", "Monitors", 175000,
         ["monitor", "ips", "full hd", "office"],
         {"Screen": "23.8\" IPS", "Resolution": "1920x1080", "Refresh": "75Hz", "Ports": "HDMI / VGA"}),
        ("Logitech MK270 Wireless Combo", "Logitech", "Accessories", 32000,
         ["keyboard", "mouse", "wireless", "office"],
         {"Type": "Keyboard + mouse", "Connectivity": "2.4GHz wireless", "Battery": "24 months", "Layout": "Full size"}),
        ("Kingston 1TB NVMe SSD", "Kingston", "Storage", 118000,
         ["ssd", "storage", "nvme", "upgrade"],
         {"Capacity": "1TB", "Interface": "NVMe PCIe 4.0", "Read": "Up to 3500MB/s", "Form": "M.2 2280"}),
    ],
    "home-kitchen": [
        ("Philips 2-in-1 Blender 600W", "Philips", "Kitchen Appliances", 89000,
         ["blender", "kitchen", "600w", "smoothie"],
         {"Power": "600W", "Capacity": "2L jar", "Speeds": "2 + pulse", "Blades": "Stainless steel"}),
        ("Tower Non-Stick Cookware Set 10pc", "Tower", "Cookware", 125000,
         ["cookware", "non-stick", "pots", "kitchen"],
         {"Pieces": "10", "Coating": "Non-stick", "Base": "Induction ready", "Material": "Aluminium"}),
        ("Scanfrost 4-Burner Gas Cooker", "Scanfrost", "Kitchen Appliances", 315000,
         ["gas cooker", "kitchen", "oven", "4 burner"],
         {"Burners": "4", "Oven": "With grill", "Ignition": "Auto", "Stand": "Included"}),
        ("4-Seater Dining Table Set", "Socratic Basics", "Furniture", 245000,
         ["dining", "furniture", "table", "chairs"],
         {"Seats": "4", "Material": "Engineered wood", "Finish": "Walnut", "Assembly": "Flat pack"}),
        ("Memory Foam Pillow 2-Pack", "Socratic Basics", "Bedding", 38000,
         ["pillow", "memory foam", "bedding", "sleep"],
         {"Pack": "2 pillows", "Fill": "Memory foam", "Cover": "Washable", "Firmness": "Medium"}),
        ("Treated Mosquito Net Double", "Socratic Basics", "Bedding", 21500,
         ["mosquito net", "bedding", "treated", "double"],
         {"Size": "Double", "Treatment": "Insecticide treated", "Shape": "Rectangular", "Frame": "Not required"}),
    ],
    "appliances": [
        ("LG 200L Chest Freezer", "LG", "Cooling", 425000,
         ["freezer", "chest freezer", "cooling", "200l"],
         {"Capacity": "200L", "Type": "Chest", "Fast freeze": "Yes", "Lock": "With key"}),
        ("Haier Thermocool 1.5HP Split AC", "Haier", "Cooling", 520000,
         ["air conditioner", "split ac", "cooling", "1.5hp"],
         {"Capacity": "1.5HP", "Type": "Split", "Energy": "Inverter", "Remote": "Included"}),
        ("Samsung 7kg Front Load Washer", "Samsung", "Laundry", 615000,
         ["washing machine", "front load", "laundry", "7kg"],
         {"Capacity": "7kg", "Type": "Front load", "Spin": "1200 rpm", "Programs": "14"}),
        ("Nexus 1.5L Electric Kettle", "Nexus", "Small Appliances", 28000,
         ["kettle", "electric", "kitchen", "1.5l"],
         {"Capacity": "1.5L", "Power": "1800W", "Body": "Stainless steel", "Cut-off": "Auto"}),
        ("Binatone 2.0L Air Fryer", "Binatone", "Small Appliances", 96000,
         ["air fryer", "kitchen", "healthy", "2l"],
         {"Capacity": "2.0L", "Power": "1400W", "Timer": "30 minutes", "Basket": "Non-stick"}),
        ("Hisense 160L Double Door Fridge", "Hisense", "Cooling", 480000,
         ["fridge", "refrigerator", "double door", "cooling"],
         {"Capacity": "160L", "Doors": "2", "Defrost": "Manual", "Shelves": "Tempered glass"}),
    ],
    "health-beauty": [
        ("Nivea Nourishing Body Lotion 400ml", "Nivea", "Body Care", 12500,
         ["lotion", "body care", "moisturiser", "dry skin"],
         {"Size": "400ml", "Skin": "Dry to normal", "SPF": "None", "Type": "Lotion"}),
        ("CeraVe Hydrating Cleanser 473ml", "CeraVe", "Skincare", 34000,
         ["cleanser", "skincare", "hydrating", "ceramides"],
         {"Size": "473ml", "Skin": "Sensitive", "Key": "Ceramides + HA", "Fragrance": "Free"}),
        ("The Ordinary Niacinamide 10% Serum", "The Ordinary", "Skincare", 18500,
         ["serum", "niacinamide", "skincare", "pores"],
         {"Size": "30ml", "Active": "Niacinamide 10% + Zinc", "Concern": "Pores and oil", "Texture": "Light"}),
        ("Gillette Fusion5 Razor Kit", "Gillette", "Grooming", 26000,
         ["razor", "grooming", "shaving", "men"],
         {"Blades": "5", "Handle": "Ergonomic", "Refills": "1 included", "Lubrication": "Strip"}),
        ("Oral-B Vitality Electric Toothbrush", "Oral-B", "Oral Care", 42000,
         ["toothbrush", "electric", "oral care", "rechargeable"],
         {"Type": "Rechargeable", "Head": "Round", "Timer": "2 minute", "Modes": "1"}),
        ("Maybelline Fit Me Foundation", "Maybelline", "Makeup", 15500,
         ["foundation", "makeup", "face", "matte"],
         {"Finish": "Matte + poreless", "Coverage": "Medium", "Shades": "Multiple", "Volume": "30ml"}),
    ],
    "fashion": [
        ("Men's Slim Fit Oxford Shirt", "Socratic Basics", "Menswear", 18500,
         ["shirt", "men", "formal", "cotton"],
         {"Fit": "Slim", "Fabric": "Cotton blend", "Collar": "Button-down", "Care": "Machine wash"}),
        ("Women's Ankara Print Maxi Dress", "Socratic Basics", "Womenswear", 32000,
         ["dress", "women", "ankara", "maxi"],
         {"Style": "Maxi", "Print": "Ankara", "Fabric": "Wax cotton", "Fit": "Regular"}),
        ("Nike Air Zoom Running Shoes", "Nike", "Footwear", 98000,
         ["shoes", "running", "sneakers", "sport"],
         {"Type": "Running", "Cushioning": "Air Zoom", "Upper": "Mesh", "Sizes": "40-46"}),
        ("Leather Laptop Briefcase", "Socratic Basics", "Bags", 45000,
         ["bag", "briefcase", "leather", "laptop"],
         {"Fits": "Up to 15.6\"", "Material": "PU leather", "Straps": "Shoulder + handle", "Compartments": "3"}),
        ("Unisex Aviator Sunglasses UV400", "Socratic Basics", "Accessories", 12000,
         ["sunglasses", "unisex", "uv400", "aviator"],
         {"Lens": "UV400", "Frame": "Metal", "Style": "Aviator", "Case": "Included"}),
        ("Men's Classic Leather Wristwatch", "Socratic Basics", "Watches", 38000,
         ["watch", "men", "leather", "classic"],
         {"Movement": "Quartz", "Strap": "Leather", "Water": "30m", "Dial": "Analogue"}),
    ],
    "baby-products": [
        ("Pampers Baby Dry Diapers Jumbo", "Pampers", "Diapering", 28500,
         ["diapers", "baby", "jumbo", "baby dry"],
         {"Size": "Midi (4)", "Count": "68", "Absorbency": "12 hours", "Type": "Tape"}),
        ("Chicco Lightweight Baby Stroller", "Chicco", "Gear", 185000,
         ["stroller", "baby", "lightweight", "travel"],
         {"Weight": "7.5kg", "Folding": "Compact", "Recline": "Multi-position", "Canopy": "With sun visor"}),
        ("Philips Avent Anti-Colic Bottle 260ml", "Philips Avent", "Feeding", 16500,
         ["bottle", "feeding", "anti-colic", "baby"],
         {"Volume": "260ml", "Teat": "Anti-colic", "Material": "BPA free", "Age": "0m+"}),
        ("Johnson's Baby Bath 500ml", "Johnson's", "Baby Care", 9800,
         ["baby bath", "baby", "gentle", "500ml"],
         {"Size": "500ml", "Formula": "No more tears", "Skin": "Sensitive", "Type": "Wash"}),
        ("Graco Convertible Car Seat", "Graco", "Safety", 245000,
         ["car seat", "baby", "safety", "convertible"],
         {"Group": "0+/1/2", "Install": "ISOFIX + belt", "Recline": "5 positions", "Harness": "5-point"}),
        ("Baby Wipes Sensitive 4-Pack", "Socratic Basics", "Diapering", 7500,
         ["wipes", "baby", "sensitive", "4 pack"],
         {"Packs": "4 x 80", "Formula": "Fragrance free", "Skin": "Newborn", "Type": "Wipes"}),
    ],
    "grocery": [
        ("Golden Penny Semovita 2kg", "Golden Penny", "Pantry", 6800,
         ["semovita", "swallow", "pantry", "2kg"],
         {"Weight": "2kg", "Type": "Semolina", "Shelf life": "12 months", "Packaging": "Sealed bag"}),
        ("Indomie Instant Noodles Carton", "Indomie", "Pantry", 12500,
         ["noodles", "indomie", "carton", "instant"],
         {"Packs": "40 x 70g", "Flavour": "Chicken", "Type": "Instant", "Carton": "Yes"}),
        ("Peak Milk Powder 400g", "Peak", "Beverages", 7200,
         ["milk", "powder", "beverages", "400g"],
         {"Weight": "400g tin", "Type": "Full cream", "Fortified": "Vitamin A + D", "Shelf life": "18 months"}),
        ("Dangote Refined Sugar 1kg", "Dangote", "Pantry", 2400,
         ["sugar", "dangote", "pantry", "1kg"],
         {"Weight": "1kg", "Type": "Refined white", "Packaging": "Sealed", "Origin": "Nigeria"}),
        ("Coca-Cola 50cl Pack of 12", "Coca-Cola", "Beverages", 6500,
         ["coca cola", "soft drink", "beverages", "12 pack"],
         {"Volume": "50cl x 12", "Type": "Carbonated", "Serve": "Chilled", "Packaging": "PET"}),
        ("Pure Heaven Vegetable Oil 5L", "Pure Heaven", "Pantry", 14500,
         ["oil", "vegetable oil", "cooking", "5l"],
         {"Volume": "5 litres", "Type": "Refined vegetable", "Cholesterol": "Free", "Packaging": "Jerry can"}),
    ],
    "sporting-goods": [
        ("Adjustable Dumbbell Set 20kg", "Socratic Basics", "Fitness", 78000,
         ["dumbbell", "fitness", "weights", "home gym"],
         {"Total": "20kg", "Type": "Adjustable", "Plates": "Coated", "Bar": "Chrome"}),
        ("Yoga Mat Non-Slip 6mm", "Socratic Basics", "Fitness", 18500,
         ["yoga mat", "fitness", "non-slip", "6mm"],
         {"Thickness": "6mm", "Surface": "Non-slip", "Size": "183 x 61cm", "Strap": "Included"}),
        ("Adidas Football Size 5", "Adidas", "Outdoor", 24500,
         ["football", "adidas", "outdoor", "size 5"],
         {"Size": "5", "Construction": "Machine stitched", "Cover": "TPU", "Use": "Training"}),
        ("Mountain Bike 26\" 21-Speed", "Socratic Basics", "Cycling", 285000,
         ["bike", "cycling", "mountain bike", "21 speed"],
         {"Wheels": "26\"", "Gears": "21-speed", "Brakes": "Disc", "Frame": "Steel hardtail"}),
        ("Resistance Bands Set 5pc", "Socratic Basics", "Fitness", 12500,
         ["resistance bands", "fitness", "home gym", "5pc"],
         {"Pieces": "5 bands", "Levels": "Light to extra heavy", "Material": "Latex", "Anchors": "Door + handles"}),
        ("Camping Tent 4-Person Waterproof", "Socratic Basics", "Outdoor", 96000,
         ["tent", "camping", "outdoor", "4 person"],
         {"Sleeps": "4", "Waterproof": "2000mm", "Poles": "Fibreglass", "Bag": "Carry bag included"}),
    ],
    "video-games": [
        ("Sony PlayStation 5 Slim Console", "Sony", "Consoles", 950000,
         ["playstation", "console", "ps5", "gaming"],
         {"Storage": "1TB SSD", "Resolution": "Up to 4K 120Hz", "Controller": "DualSense", "Edition": "Disc"}),
        ("Xbox Series S 512GB", "Microsoft", "Consoles", 585000,
         ["xbox", "console", "gaming", "digital"],
         {"Storage": "512GB SSD", "Resolution": "1440p", "Edition": "All-digital", "Controller": "Wireless"}),
        ("DualSense Wireless Controller", "Sony", "Controllers", 95000,
         ["controller", "ps5", "wireless", "gaming"],
         {"Haptics": "Adaptive triggers", "Battery": "Rechargeable", "Connectivity": "Bluetooth", "Extras": "Motion + speaker"}),
        ("EA Sports FC 24 (PS5)", "EA Sports", "Games", 62000,
         ["game", "football", "ps5", "sports"],
         {"Platform": "PS5", "Genre": "Sports", "Players": "1-4 local", "Online": "Yes"}),
        ("Nintendo Switch OLED", "Nintendo", "Consoles", 620000,
         ["nintendo", "console", "handheld", "gaming"],
         {"Screen": "7\" OLED", "Storage": "64GB", "Modes": "TV / tabletop / handheld", "Joy-Con": "Included"}),
        ("Gaming Headset 7.1 Surround", "Socratic Basics", "Accessories", 48000,
         ["headset", "gaming", "7.1", "microphone"],
         {"Audio": "7.1 surround", "Mic": "Noise cancelling", "Connectivity": "USB + 3.5mm", "Lighting": "RGB"}),
    ],
    "automotive": [
        ("Car Dash Camera 1080P Dual", "Socratic Basics", "In-Car Electronics", 68000,
         ["dash cam", "car", "1080p", "recording"],
         {"Resolution": "1080P dual", "View": "170 degrees", "Storage": "Up to 64GB", "Night": "IR night vision"}),
        ("Michelin Tyre 205/55R16", "Michelin", "Tyres", 92000,
         ["tyre", "michelin", "car", "205/55r16"],
         {"Size": "205/55R16", "Type": "All season", "Load": "91V", "Warranty": "Manufacturer"}),
        ("Car Vacuum Cleaner 12V", "Socratic Basics", "Car Care", 22000,
         ["vacuum", "car", "12v", "cleaning"],
         {"Power": "12V DC", "Suction": "High", "Attachments": "3 nozzles", "Filter": "Washable HEPA"}),
        ("Bosch Car Battery 60Ah", "Bosch", "Batteries", 115000,
         ["battery", "bosch", "car", "60ah"],
         {"Capacity": "60Ah", "CCA": "540A", "Type": "Maintenance free", "Warranty": "18 months"}),
        ("Magnetic Car Phone Holder", "Socratic Basics", "Accessories", 8500,
         ["phone holder", "car", "magnetic", "accessory"],
         {"Mount": "Dashboard + vent", "Magnets": "6x N52", "Rotation": "360 degrees", "Phones": "Up to 6.9\""}),
        ("Total 5W-30 Synthetic Engine Oil 5L", "Total", "Car Care", 38000,
         ["engine oil", "5w-30", "synthetic", "car"],
         {"Viscosity": "5W-30", "Type": "Fully synthetic", "Volume": "5 litres", "Spec": "API SP"}),
    ],
}

DESC_TEMPLATES = [
    "The {title} from {brand} is built for everyday use in {city}. {hook} Backed by a {warranty}-month {brand} warranty and eligible for pay-on-delivery.",
    "{brand} brings the {title} to {category} shoppers who want {hook_lower} Free returns within 7 days if it is not right for you.",
    "A {subcategory_lower} pick from {brand}: the {title} pairs {hook_lower} It ships from a verified seller and includes a {warranty}-month warranty.",
]

HOOKS = [
    "Expect dependable build quality, honest specifications and spares that are easy to find.",
    "It is one of the most reviewed options in its price band this month.",
    "Buyers consistently mention value for money and fast delivery.",
    "It is a straightforward upgrade that does not need extra accessories.",
    "Stock moves quickly, so the listed price is the price while it lasts.",
]

CITIES = ["Lagos", "Abuja", "Port Harcourt", "Ibadan", "Kano", "Benin City"]

VARIANTS_BY_CATEGORY = {
    "phones-tablets": {"Colour": ["Midnight Black", "Ice Blue", "Mint Green"], "Storage": ["128GB", "256GB"]},
    "electronics": {"Warranty": ["1 year", "2 years"]},
    "computing": {"Memory": ["8GB", "16GB"], "Storage": ["256GB SSD", "512GB SSD", "1TB SSD"]},
    "home-kitchen": {"Colour": ["Silver", "Black", "Stainless Steel"]},
    "appliances": {"Warranty": ["1 year", "2 years"]},
    "health-beauty": {"Size": ["Standard", "Value Pack"]},
    "fashion": {"Size": ["S", "M", "L", "XL"], "Colour": ["Black", "Navy", "Beige"]},
    "baby-products": {"Size": ["Newborn", "0-6 months", "6-12 months"]},
    "grocery": {"Pack": ["Single", "Pack of 3", "Carton"]},
    "sporting-goods": {"Colour": ["Black", "Grey", "Blue"]},
    "video-games": {"Edition": ["Standard", "Deluxe"]},
    "automotive": {"Position": ["Front", "Rear"]},
}

SELLERS = [
    "Socratic Official Store", "Verified Partner", "MegaMart NG", "Prime Gadgets NG",
    "TopChoice Retail", "Naija Best Buys",
]


def slugify(text: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return re.sub(r"-{2,}", "-", text)


def _stable_int(seed_text: str, low: int, high: int) -> int:
    """Deterministic integer in [low, high] derived from the string."""
    digest = hashlib.sha256(seed_text.encode("utf-8")).hexdigest()
    return low + int(digest[:12], 16) % (high - low + 1)


def build_products() -> list[dict]:
    products: list[dict] = []
    counter = 0
    for cat_slug, items in ITEMS.items():
        cat = CATEGORIES[cat_slug]
        for name, brand, subcategory, price, tags, specs in items:
            counter += 1
            slug = slugify(f"{name}")
            sku = f"SKU-{counter:04d}"

            # Deterministic commercial signals.
            discount_pct = _stable_int(slug + "disc", 5, 34)
            old_price = int(round(price / (1 - discount_pct / 100.0), -2))
            rating = round(_stable_int(slug + "rate", 36, 49) / 10.0, 1)
            reviews = _stable_int(slug + "rev", 18, 940)
            sold = _stable_int(slug + "sold", 35, 3100)
            stock = _stable_int(slug + "stock", 4, 140)
            express = _stable_int(slug + "exp", 0, 99) < 55
            created = _stable_int(slug + "age", 2, 240)
            warranty = 12 if cat_slug not in ("grocery", "health-beauty") else 0
            city = CITIES[_stable_int(slug + "city", 0, len(CITIES) - 1)]
            hook = HOOKS[_stable_int(slug + "hook", 0, len(HOOKS) - 1)]
            template = DESC_TEMPLATES[_stable_int(slug + "tpl", 0, len(DESC_TEMPLATES) - 1)]
            description = template.format(
                title=name,
                brand=brand,
                city=city,
                hook=hook,
                hook_lower=hook[0].lower() + hook[1:],
                category=cat["label"],
                subcategory_lower=subcategory.lower(),
                warranty=warranty or 6,
            )

            products.append({
                "id": sku,
                "slug": slug,
                "title": name,
                "brand": brand,
                "category": cat_slug,
                "category_label": cat["label"],
                "subcategory": subcategory,
                "price": price,
                "old_price": old_price,
                "discount_pct": discount_pct,
                "rating": rating,
                "reviews": reviews,
                "sold": sold,
                "stock": stock,
                "express": express,
                "warranty_months": warranty,
                "seller": SELLERS[_stable_int(slug + "seller", 0, len(SELLERS) - 1)],
                "tags": tags,
                "specs": specs,
                "variants": VARIANTS_BY_CATEGORY.get(cat_slug, {}),
                "description": description,
                "created_days_ago": created,
                "flash": False,
                "image": None,
            })

    # Flash sale: deepest discounts, at most two per category.
    by_cat: dict[str, list[dict]] = {}
    for p in products:
        by_cat.setdefault(p["category"], []).append(p)
    for group in by_cat.values():
        for p in sorted(group, key=lambda x: -x["discount_pct"])[:2]:
            p["flash"] = True

    return products


def build_orders(products: list[dict]) -> list[dict]:
    """Synthetic baskets so the recommender has a co-purchase signal.

    Baskets lean on three real behaviours: same-category substitution,
    cross-category complements (phone -> case/charger, laptop -> mouse), and a
    long tail of single-item orders.
    """
    rng = random.Random(20241013)
    by_cat: dict[str, list[dict]] = {}
    for p in products:
        by_cat.setdefault(p["category"], []).append(p)

    # Hand-picked complement pairs, both directions.
    complements = [
        ("phones-tablets", "electronics"), ("phones-tablets", "computing"),
        ("computing", "electronics"), ("computing", "home-kitchen"),
        ("appliances", "home-kitchen"), ("grocery", "grocery"),
        ("baby-products", "health-beauty"), ("fashion", "fashion"),
        ("video-games", "electronics"), ("sporting-goods", "fashion"),
        ("automotive", "electronics"), ("health-beauty", "health-beauty"),
    ]
    complement_map: dict[str, list[str]] = {}
    for a, b in complements:
        complement_map.setdefault(a, []).append(b)
        complement_map.setdefault(b, []).append(a)

    all_ids = [p["id"] for p in products]
    categories = list(by_cat)
    orders: list[dict] = []
    for n in range(420):
        basket: list[str] = []
        roll = rng.random()
        if roll < 0.30:
            # Single item, the long tail of a real store.
            basket.append(rng.choice(all_ids))
        elif roll < 0.62:
            # Two items: a same-category substitution, or a complement pair.
            if rng.random() < 0.5:
                cat = rng.choice(categories)
                picks = rng.sample(by_cat[cat], k=min(2, len(by_cat[cat])))
                basket.extend(p["id"] for p in picks)
            else:
                a, b = rng.choice(complements)
                basket.append(rng.choice(by_cat[a])["id"])
                basket.append(rng.choice(by_cat[b])["id"])
        elif roll < 0.90:
            # Three to four items: one anchor plus items that genuinely go with
            # it. Drawing the extras from the anchor's complement categories is
            # what makes the learned "bought together" shelf coherent.
            cat = rng.choice(categories)
            basket.append(rng.choice(by_cat[cat])["id"])
            targets = complement_map.get(cat, []) + [cat]
            for _ in range(rng.randint(1, 3)):
                basket.append(rng.choice(by_cat[rng.choice(targets)])["id"])
        else:
            # A deliberately noisy basket, so the co-purchase signal is not
            # suspiciously perfect and lift remains a meaningful test.
            for _ in range(rng.randint(1, 3)):
                basket.append(rng.choice(all_ids))

        # De-duplicate while keeping order.
        seen: set[str] = set()
        basket = [i for i in basket if not (i in seen or seen.add(i))]
        orders.append({"id": f"ORD-{n + 1:04d}", "items": basket})
    return orders


def main() -> None:
    products = build_products()
    orders = build_orders(products)
    (HERE / "products.json").write_text(
        json.dumps(products, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (HERE / "orders.json").write_text(
        json.dumps(orders, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    cats = {p["category"] for p in products}
    print(f"products: {len(products)} across {len(cats)} categories")
    print(f"orders:   {len(orders)} baskets")
    print(f"flash:    {sum(1 for p in products if p['flash'])}")


if __name__ == "__main__":
    main()
