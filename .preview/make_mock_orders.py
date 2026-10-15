"""
Preview helper: build a realistic order history for the mock orders API.

The real app fetches paid orders from a WooCommerce endpoint (see
app/services/get_data.py). For a local preview there is no such store, so this
script fabricates a plausible dataset - one that keeps repeat customers, so the
repurchase/lapsed screens have something to show - and writes it to
.preview/mock_orders.json. .preview/mock_api.py serves that file in the exact
shape the app expects.
"""
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

random.seed(7)

HERE = Path(__file__).resolve().parent

FIRST_NAMES_F = ["Ana", "Andrea", "Carolina", "Diana", "Laura", "Marcela", "Paula",
                 "Sofia", "Valentina", "Camila", "Juliana", "Natalia", "Isabella"]
FIRST_NAMES_M = ["Carlos", "Andres", "Felipe", "Juan", "Santiago", "Diego", "Camilo",
                 "Sebastian", "Daniel", "Miguel", "Alejandro", "Julian"]
LAST_NAMES = ["Garcia", "Rodriguez", "Martinez", "Lopez", "Gomez", "Diaz", "Torres",
              "Ramirez", "Moreno", "Castillo", "Vargas", "Ortiz", "Jimenez", "Rojas"]

CITIES = [
    ("BOGOTA (C/MARCA)", "Cundinamarca", 4.7110, -74.0721),
    ("MEDELLIN (ANT)", "Antioquia", 6.2442, -75.5812),
    ("CALI (VAC)", "Valle del Cauca", 3.4516, -76.5320),
    ("BARRANQUILLA (ATL)", "Atlantico", 10.9685, -74.7813),
    ("CARTAGENA (BOL)", "Bolivar", 10.3910, -75.4794),
    ("BUCARAMANGA (SAN)", "Santander", 7.1193, -73.1227),
    ("AGUA DE DIOS (C/MARCA)", "Cundinamarca", 4.3764, -74.6694),
    ("PEREIRA (RIS)", "Risaralda", 4.8133, -75.6961),
]

UTM = [
    ("facebook", "cpc", "prospecting_2025"),
    ("google", "cpc", "search_brand"),
    ("tiktok", "cpc", "video_views"),
    ("wati", "whatsapp", "remarketing"),
    ("instagram", "social", "organic"),
    ("", "", ""),
]

PRODUCTS = [
    ("Promocion 3X2 (3 unidades)", "pack_3x2", 42500),
    ("Promocion Regala Salud (10 unidades)", "pack_10", 114000),
    ("Unidad Sencilla", "una_unidad", 18000),
    ("Pack Ecostand (6 unidades)", "pack_ecostand", 68000),
    ("Promocion Pareja (2 unidades)", "pack_2", 32000),
]

INTERVAL = ("daily", "gummies", "eco", "hotel")
ANSWERS = ["salud", "energia", "piel", "recomendacion", "instagram", "facebook"]


def phone() -> str:
    return "+573" + "".join(random.choice("0123456789") for _ in range(8))


def make_customers(n):
    """People, each with the identity the store would report for them."""
    people = []
    for i in range(n):
        female = random.random() < 0.62
        first = random.choice(FIRST_NAMES_F if female else FIRST_NAMES_M)
        last = random.choice(LAST_NAMES)
        handle = f"{first.lower()}.{last.lower()}{random.randint(1, 999)}"
        people.append({
            "name": first,
            "last_name": last,
            "gender": "female" if female else "male",
            "email": f"{handle}@gmail.com",
            "phone": phone(),
            "city": None,  # chosen per order
        })
    return people


def build():
    now = datetime(2026, 10, 11, 12, 0, 0)
    start = now - timedelta(days=300)

    people = make_customers(260)
    orders = []
    order_id = 120000

    for person in people:
        city, state, lat, lng = random.choice(CITIES)
        # Repeat buyers make the repurchase screens meaningful: most buy once,
        # a solid minority return two to five times.
        roll = random.random()
        if roll < 0.55:
            visits = 1
        elif roll < 0.82:
            visits = random.randint(2, 3)
        elif roll < 0.96:
            visits = random.randint(4, 5)
        else:
            visits = random.randint(6, 8)

        day = start + timedelta(days=random.randint(0, 290))
        for visit in range(visits):
            day = day + timedelta(days=random.randint(12, 70))
            if day > now:
                break

            product, sku, base_price = random.choice(PRODUCTS)
            qty = random.choice([1, 1, 1, 2, 2, 3])
            total = float(base_price * qty)
            utm_source, utm_medium, utm_campaign = random.choice(UTM)
            hour = random.randint(7, 21)
            minute = random.randint(0, 59)
            stamp = day.replace(hour=hour, minute=minute, second=random.randint(0, 59))
            utc = stamp - timedelta(hours=5)  # Colombia is UTC-5

            orders.append({
                "order_id": str(order_id),
                "order_date": stamp.strftime("%Y-%m-%d %H:%M:%S"),
                "order_date_utc": utc.strftime("%Y-%m-%d %H:%M:%S"),
                "name": person["name"],
                "last_name": person["last_name"],
                "gender": person["gender"],
                "email": person["email"],
                "phone": person["phone"],
                "city": city,
                "state": state,
                "order_lat": str(lat),
                "order_lng": str(lng),
                "total_value": f"{total:.2f}",
                "product": product,
                "sku": sku,
                "utm_source": utm_source,
                "utm_medium": utm_medium,
                "utm_campaign": utm_campaign,
                "utm_term": "undefined",
                "utm_content": "undefined",
                "utm_answer": random.choice(ANSWERS),
                "address_1": f"Calle {random.randint(1, 160)} #{random.randint(1, 90)}-{random.randint(1, 80)}",
                "purchase_number": str(visit + 1),
                "is_repurchase": "true" if visit >= 1 else "false",
            })
            order_id += 1

    # Newest first, exactly as the store's API returns them.
    orders.sort(key=lambda o: o["order_date"], reverse=True)
    return orders


def main():
    orders = build()
    out = HERE / "mock_orders.json"
    out.write_text(json.dumps(orders, ensure_ascii=False), encoding="utf-8")

    customers = {(o["email"]) for o in orders}
    reps = [o for o in orders if o["is_repurchase"] == "true"]
    total = sum(float(o["total_value"]) for o in orders)
    print(f"orders:    {len(orders)}")
    print(f"customers: {len(customers)}")
    print(f"repurchases: {len(reps)}")
    print(f"revenue:   {total:,.0f} COP")
    print(f"span:      {min(o['order_date'] for o in orders)[:10]} .. {max(o['order_date'] for o in orders)[:10]}")
    print(f"written:   {out}")


if __name__ == "__main__":
    main()
