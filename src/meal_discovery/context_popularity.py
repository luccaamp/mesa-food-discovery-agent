"""What people order around here at this time: region x time-slot popularity.

The business analysis found that popularity is local (regional top-20 restaurants share
almost nothing with the city top-20) and that the time of day changes what is ordered.
Experiment 004 measured that ranking by region and time slot finds the customer's real
next restaurant far more often than city-wide popularity, which matters most for new
customers, about whom nothing else is known.

The artifact holds, for each region (DHRD order geohash) and time slot, the most ordered
items in the official training file, plus a city-wide list per slot. Regions are named
after the nearest well-known Singapore town of the geohash cell's centre, as an
approximation for people; the geohash itself is what the data contains.
"""

from datetime import datetime, timedelta, timezone
from functools import lru_cache
import json
from pathlib import Path

ARTIFACT = Path(__file__).with_name("data") / "context-popularity-v1.json"
SINGAPORE = timezone(timedelta(hours=8))
SLOTS = (("madrugada", 0, 5), ("manha", 6, 10), ("almoco", 11, 13), ("tarde", 14, 16), ("jantar", 17, 20),
         ("noite", 21, 23))
SLOT_LABELS = {"madrugada": "de madrugada", "manha": "de manhã", "almoco": "no almoço", "tarde": "à tarde",
               "jantar": "no jantar", "noite": "à noite"}
CITY = "city"
# Geohash cells with at least 2,000 orders, named after the nearest town to the cell centre.
REGION_NAMES = {
    "w21z6": "Orchard / Tiong Bahru", "w21ze": "Toa Payoh", "w21zu": "Sengkang", "w21z7": "Marina / Kallang",
    "w21zt": "Tampines", "w23b4": "Yishun", "w21z8": "Jurong East", "w21zg": "Ang Mo Kio", "w21zs": "Paya Lebar",
    "w21zk": "Marine Parade", "w23b1": "Woodlands", "w21z3": "Queenstown", "w21xx": "Jurong West",
    "w21zb": "Choa Chu Kang", "w21zv": "Pasir Ris", "w21zc": "Bukit Panjang", "w21z9": "Bukit Batok",
    "w23b5": "Seletar", "w21zf": "Upper Thomson", "w21zd": "Novena / Bukit Timah", "w23b6": "Sembawang",
    "w21z4": "HarbourFront / Sentosa", "w21zm": "Bedok", "w21z2": "Pasir Panjang", "w21z5": "Marina South",
    "w23bh": "Punggol",
}


def slot_at(moment=None):
    """Time slot for a moment, by default now in Singapore, where the catalog is."""
    hour = (moment or datetime.now(SINGAPORE)).astimezone(SINGAPORE).hour
    return next(name for name, first, last in SLOTS if first <= hour <= last)


@lru_cache(maxsize=1)
def _artifact(path=ARTIFACT):
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("artifact_version") != "context-popularity-v1":
        raise ValueError("Unsupported context popularity artifact")
    return data


def regions():
    data = _artifact()
    return [{"id": key, "name": REGION_NAMES.get(key, key), "orders": data["region_orders"][key]}
            for key in sorted(data["region_orders"], key=lambda key: REGION_NAMES.get(key, key))]


def region_name(region):
    return REGION_NAMES.get(region, region)


def popular_here(region=None, slot=None):
    """Ranked (vendor_id, product_id, orders) for a region and slot; the city list when the region is unknown."""
    data = _artifact()
    slot = slot or slot_at()
    if slot not in SLOT_LABELS:
        raise ValueError("Unknown time slot")
    scope = region if region in data["regions"] else CITY
    entries = data["regions"].get(scope, {}).get(slot) or data["regions"][CITY][slot]
    return scope, slot, [tuple(entry) for entry in entries]


def build(database: Path, output: Path, *, last_day=75, per_list=40, min_region_orders=2000):
    """Write the artifact from the official training orders (days 0..last_day)."""
    import sqlite3
    from collections import Counter, defaultdict
    from .dataset import file_hash
    connection = sqlite3.connect(Path(database).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        manifest = json.loads(connection.execute("SELECT value FROM metadata WHERE key='manifest'").fetchone()[0])
        if manifest.get("data_kind") != "official_dhrd":
            raise ValueError("Context popularity requires the official dataset")
        region_orders = Counter(dict(connection.execute(
            "SELECT c.geohash, COUNT(*) FROM orders o JOIN order_context c USING(order_id) WHERE o.order_day<=? GROUP BY 1",
            (last_day,)).fetchall()))
        counts = defaultdict(Counter)
        rows = connection.execute("""SELECT c.geohash, CAST(substr(o.order_time,1,2) AS INTEGER), i.vendor_id, i.product_id
                                     FROM orders o JOIN order_context c USING(order_id) JOIN order_items i USING(order_id)
                                     WHERE o.order_day<=?""", (last_day,))
        for geohash, hour, vendor, product in rows:
            slot = next(name for name, first, last in SLOTS if first <= hour <= last)
            counts[(CITY, slot)][(vendor, product)] += 1
            if region_orders[geohash] >= min_region_orders:
                counts[(geohash, slot)][(vendor, product)] += 1
    finally:
        connection.close()
    lists = defaultdict(dict)
    for (scope, slot), counter in counts.items():
        ranked = sorted(counter.items(), key=lambda pair: (-pair[1], pair[0]))[:per_list]
        lists[scope][slot] = [[vendor, product, count] for (vendor, product), count in ranked]
    data = {"artifact_version": "context-popularity-v1", "data_kind": manifest["data_kind"], "city": manifest["city"],
            "source_database_sha256": file_hash(database), "order_days": [0, last_day],
            "method": "Item presence in orders per DHRD order geohash and Singapore time slot; regions with at least "
                      f"{min_region_orders} orders; '{CITY}' is the whole city.",
            "region_orders": {key: region_orders[key] for key in lists if key != CITY},
            "regions": dict(sorted(lists.items()))}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    return {"regions": len(lists) - 1, "slots": len(SLOTS)}


def recommend_here(index, *, region=None, slot=None, cuisine=None, min_price=None, max_price=None, price_level=None,
                   exclude=(), limit=10, allow_test_data=False):
    """Catalog rows for the most ordered items here and now, filtered like any recommendation."""
    from .catalog import open_catalog
    from .pricing import annotate
    scope, slot, entries = popular_here(region, slot)
    connection, _ = open_catalog(index, allow_test_data=allow_test_data)
    items = []
    try:
        for vendor, product, orders in entries:
            if len(items) >= limit:
                break
            if (vendor, product) in exclude:
                continue
            row = connection.execute("SELECT vendor_id,product_id,name,unit_price,primary_cuisine FROM items "
                                     "WHERE vendor_id=? AND product_id=?", (vendor, product)).fetchone()
            if row is None or (cuisine is not None and row["primary_cuisine"] != cuisine):
                continue
            item = annotate([dict(row)])[0]
            level = item["price_band"]["level"]
            if price_level is not None and (level is None or level > price_level):
                continue
            price = item["unit_price"] or 0
            if (max_price is not None and not 0 < price <= max_price) or (min_price is not None and price < min_price):
                continue
            items.append({**item, "score": None, "supporting_co_baskets": 0, "training_baskets": 0,
                          "context_orders": orders, "reason": "popular_here"})
    finally:
        connection.close()
    return {"items": items, "region": None if scope == CITY else {"id": scope, "name": region_name(scope)},
            "slot": slot, "slot_label": SLOT_LABELS[slot]}
