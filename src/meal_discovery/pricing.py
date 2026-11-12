"""Price bands: turn the dataset's unitless prices into something a person can read.

DHRD publishes prices normalized to an undisclosed scale (the maximum is 1.0 and a
plate of chicken rice is about 0.0028), so no currency value can be shown without
inventing a conversion. A position within the same cuisine survives any
order-preserving normalization, so every item gets:

* a band: ``$`` (cheapest third of its cuisine), ``$$`` (middle third), ``$$$`` (top third);
* how many priced items of that cuisine cost more ("mais barato que 72% em pizza").

A recorded price of 0 means the source has no price; it gets no band and never
matches a price filter. Bands come from a small versioned artifact built from the
full catalog by ``scripts/build_price_bands.py``.
"""

from bisect import bisect_left, bisect_right
from functools import lru_cache
import json
from pathlib import Path

ARTIFACT = Path(__file__).with_name("data") / "price-bands-v1.json"
LEVELS = {1: ("$", "barato"), 2: ("$$", "preço médio"), 3: ("$$$", "mais caro")}
GLOBAL = "__all__"


class _Distribution:
    def __init__(self, values, counts):
        self.values = values
        running, self.cumulative = 0, []
        for count in counts:
            running += count
            self.cumulative.append(running)
        self.total = running
        self.cuts = (self.quantile(1 / 3), self.quantile(2 / 3))

    def quantile(self, share):
        return self.values[bisect_left(self.cumulative, share * self.total)]

    def pricier_share(self, price):
        cheaper_or_equal = bisect_right(self.values, price)
        return 1 - (self.cumulative[cheaper_or_equal - 1] if cheaper_or_equal else 0) / self.total

    def level(self, price):
        return 1 if price <= self.cuts[0] else 2 if price <= self.cuts[1] else 3


@lru_cache(maxsize=1)
def _bands(path=ARTIFACT):
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("artifact_version") != "price-bands-v1":
        raise ValueError("Unsupported price band artifact")
    return {name: _Distribution(entry["values"], entry["counts"]) for name, entry in data["cuisines"].items()}


def _distribution(cuisine):
    bands = _bands()
    return bands.get(cuisine) or bands[GLOBAL]


def price_band(unit_price, cuisine):
    """Band and relative position of a price within its cuisine; None fields when unknown."""
    if unit_price is None or unit_price <= 0:
        return {"level": None, "symbol": None, "label": "preço não informado", "pricier_share": None,
                "reference": cuisine}
    distribution = _distribution(cuisine)
    level = distribution.level(unit_price)
    symbol, label = LEVELS[level]
    return {"level": level, "symbol": symbol, "label": label,
            "pricier_share": round(distribution.pricier_share(unit_price), 3), "reference": cuisine}


def annotate(items):
    for item in items:
        item["price_band"] = price_band(item.get("unit_price"), item.get("primary_cuisine"))
    return items


def describe(band):
    """Short Portuguese text, e.g. "$ · mais barato que 72% dos itens de pizza"."""
    if band["level"] is None:
        return "preço não informado"
    share = band["pricier_share"]
    if share >= 0.5:
        relation = f"mais barato que {round(share * 100)}%"
    else:
        relation = f"mais caro que {round((1 - share) * 100)}%"
    return f"{band['symbol']} · {relation} dos itens de {band['reference']}"


def level_clause(max_level, column="i.unit_price", cuisine_column="i.primary_cuisine"):
    """SQL fragment and parameters keeping items at or below a band of their own cuisine."""
    if max_level not in (1, 2, 3):
        raise ValueError("Price level must be 1, 2 or 3")
    if max_level == 3:
        return f"{column}>0", []
    bands = _bands()
    index = max_level - 1
    cases, params = [], []
    for name, distribution in bands.items():
        if name != GLOBAL:
            cases.append("WHEN ? THEN ?")
            params += [name, distribution.cuts[index]]
    sql = f"{column}>0 AND {column}<=CASE {cuisine_column} {' '.join(cases)} ELSE ? END"
    return sql, params + [bands[GLOBAL].cuts[index]]


def build_bands(catalog: Path, output: Path):
    """Write the band artifact from every priced item of a catalog index."""
    import sqlite3
    from collections import Counter, defaultdict
    from .dataset import file_hash
    connection = sqlite3.connect(catalog.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        manifest = json.loads(connection.execute("SELECT value FROM metadata WHERE key='catalog_manifest'").fetchone()[0])
        counters = defaultdict(Counter)
        for price, cuisine in connection.execute("SELECT unit_price,primary_cuisine FROM items WHERE unit_price>0"):
            counters[cuisine][price] += 1
            counters[GLOBAL][price] += 1
    finally:
        connection.close()
    cuisines = {}
    for name, counter in sorted(counters.items()):
        values = sorted(counter)
        cuisines[name] = {"values": values, "counts": [counter[value] for value in values]}
    data = {"artifact_version": "price-bands-v1", "data_kind": manifest["data_kind"], "city": manifest["city"],
            "catalog_sha256": file_hash(catalog), "priced_items": sum(cuisines[GLOBAL]["counts"]),
            "method": "Tertiles of recorded prices (> 0) within each vendor primary cuisine; __all__ is the fallback.",
            "cuisines": cuisines}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    return {"priced_items": data["priced_items"], "cuisines": len(cuisines) - 1}
