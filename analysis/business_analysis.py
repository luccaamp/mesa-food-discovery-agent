"""Business questions answered from 1.7 million real delivery orders (DHRD, Singapore).

Reads the official training database (days 0-75) read-only and writes:
  evaluations/results/business-analysis-v1.json   every number quoted in docs/BUSINESS_ANALYSIS.md
  docs/analysis/*.png                              the charts

Run: python analysis/business_analysis.py   (needs the "analysis" extra: pandas, matplotlib)

The file holds 76 days; nothing before day 0 is known. Questions about a customer's
history therefore only use orders from day 30 on, so every customer has at least 30
observed days behind each order, and "new" means "absent for at least 30 days".
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
LOOKBACK_START = 30
SLOTS = [(0, 6, "madrugada"), (6, 11, "manhã"), (11, 14, "almoço"), (14, 17, "tarde"), (17, 21, "jantar"), (21, 24, "noite")]
BRAND, ACCENT, GOLD, INK, MUTED = "#17483a", "#b0432a", "#e3a43b", "#1b2621", "#9aa59f"


def load(database):
    connection = sqlite3.connect(Path(database).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        manifest = json.loads(connection.execute("SELECT value FROM metadata WHERE key='manifest'").fetchone()[0])
        if manifest.get("data_kind") != "official_dhrd":
            raise SystemExit("The analysis runs only on the verified official dataset")
        orders = pd.read_sql("""SELECT o.order_id, o.customer_id, o.order_day, o.order_time, c.geohash, c.day_of_week
                                FROM orders o JOIN order_context c USING(order_id)""", connection)
        items = pd.read_sql("SELECT order_id, vendor_id, product_id FROM order_items", connection)
        vendors = pd.read_sql("""SELECT v.vendor_id, v.primary_cuisine, x.chain_id, x.geohash AS vendor_geohash
                                 FROM vendors v LEFT JOIN vendor_context x USING(vendor_id)""", connection)
        products = pd.read_sql("SELECT vendor_id, product_id, unit_price FROM products", connection)
    finally:
        connection.close()
    # Every order has a single vendor in DHRD; checked rather than assumed.
    per_order = items.groupby("order_id").vendor_id.agg(["first", "nunique"])
    if (per_order["nunique"] != 1).any():
        raise SystemExit("Found an order with more than one vendor")
    orders = orders.merge(per_order["first"].rename("vendor_id"), left_on="order_id", right_index=True)
    orders = orders.merge(vendors, on="vendor_id", how="left")
    orders["hour"] = orders.order_time.str[:2].astype(int)
    orders["slot"] = pd.cut(orders.hour, [s[0] - 1 for s in SLOTS] + [23], labels=[s[2] for s in SLOTS])
    orders = orders.sort_values(["customer_id", "order_day", "order_time", "order_id"]).reset_index(drop=True)
    return manifest, orders, items, vendors, products


def exploration(orders, items):
    """How often a returning customer orders from a restaurant (and items) they never used before."""
    orders = orders.copy()
    orders["prior_orders"] = orders.groupby("customer_id").cumcount()
    orders["vendor_seen"] = orders.duplicated(["customer_id", "vendor_id"])
    chain = orders.chain_id.fillna("vendor:" + orders.vendor_id)
    orders["chain_seen"] = pd.Series(list(zip(orders.customer_id, chain))).duplicated().values
    window = orders[(orders.order_day >= LOOKBACK_START) & (orders.prior_orders > 0)]
    bins = [(1, 1, "1"), (2, 4, "2–4"), (5, 9, "5–9"), (10, 10**6, "10+")]
    by_history = []
    for low, high, label in bins:
        group = window[(window.prior_orders >= low) & (window.prior_orders <= high)]
        by_history.append({"prior_orders": label, "orders": int(len(group)),
                           "new_vendor_share": float(1 - group.vendor_seen.mean()),
                           "new_chain_share": float(1 - group.chain_seen.mean())})
    lines = items.merge(orders[["order_id", "customer_id", "order_day", "prior_orders"]], on="order_id")
    lines = lines.sort_values(["customer_id", "order_day"], kind="stable")
    order_rank = orders.set_index("order_id").index.get_indexer(lines.order_id)
    lines = lines.assign(rank=order_rank).sort_values("rank")
    lines["item_seen"] = lines.duplicated(["customer_id", "vendor_id", "product_id"])
    item_window = lines[(lines.order_day >= LOOKBACK_START) & (lines.prior_orders > 0)]
    return {
        "returning_orders": int(len(window)),
        "new_vendor_share": float(1 - window.vendor_seen.mean()),
        "new_chain_share": float(1 - window.chain_seen.mean()),
        "repeated_item_share": float(item_window.item_seen.mean()),
        "orders_with_any_repeated_item": float(item_window.groupby("order_id").item_seen.any().mean()),
        "by_prior_orders": by_history,
    }


def retention(orders):
    """Customers first seen on days 30-45 (absent for 30+ days): do they come back within 30 days?"""
    first = orders.groupby("customer_id").order_day.min()
    cohort = first[(first >= LOOKBACK_START) & (first <= 45)]
    later = orders[orders.customer_id.isin(cohort.index)].merge(cohort.rename("first_day"), left_on="customer_id",
                                                                 right_index=True)
    returned = later[(later.order_day > later.first_day) & (later.order_day <= later.first_day + 30)].customer_id.unique()
    per_customer = orders.groupby("customer_id").size()
    return {
        "customers": int(orders.customer_id.nunique()),
        "orders": int(len(orders)),
        "single_order_customers_share": float((per_customer == 1).mean()),
        "orders_from_customers_with_5_plus": float(per_customer[per_customer >= 5].sum() / per_customer.sum()),
        "new_customer_cohort": int(len(cohort)),
        "new_customers_returning_within_30_days": float(len(returned) / len(cohort)),
        "orders_per_customer_median": float(per_customer.median()),
    }


def context(orders):
    hours = orders.hour.value_counts(normalize=True).sort_index()
    top = orders.primary_cuisine.value_counts().head(10).index
    mix = pd.crosstab(orders.slot, orders.primary_cuisine, normalize="index")
    leaders = {str(slot): {name: round(float(share), 4) for name, share in
                           mix.loc[slot].sort_values(ascending=False).head(3).items()} for slot in mix.index}
    # Lift: share of a cuisine in a slot divided by its share of the whole day.
    overall = orders.primary_cuisine.value_counts(normalize=True)
    lift = (mix[top] / overall[top]).round(2)
    local = orders.dropna(subset=["vendor_geohash"])
    # Popularity is local: compare each region's top 20 vendors with the city-wide top 20.
    city_top = set(orders.vendor_id.value_counts().head(20).index)
    overlaps = []
    for _, group in orders.groupby("geohash"):
        if len(group) >= 5000:
            overlaps.append(len(set(group.vendor_id.value_counts().head(20).index) & city_top) / 20)
    return {
        "hour_share": {int(hour): round(float(share), 4) for hour, share in hours.items()},
        "lunch_11_13_share": float(hours.loc[11:13].sum()),
        "dinner_17_20_share": float(hours.loc[17:20].sum()),
        "slot_order_share": {str(k): round(float(v), 4) for k, v in orders.slot.value_counts(normalize=True).items()},
        "slot_leaders": leaders,
        "cuisine_lift_by_slot": {str(slot): {name: float(value) for name, value in row.items()} for slot, row in lift.iterrows()},
        "same_geohash_share": float((local.geohash == local.vendor_geohash).mean()),
        "customer_regions": int(orders.geohash.nunique()),
        "regions_with_5000_orders": len(overlaps),
        "regional_top20_overlap_with_city_top20": {"median": float(np.median(overlaps)), "min": float(min(overlaps)),
                                                    "max": float(max(overlaps))},
        **demand_concentration(orders),
    }, lift


def demand_concentration(orders):
    """How flat restaurant demand is, and whether the all-time top restaurants keep their demand over time."""
    counts = orders.vendor_id.value_counts()
    top10 = set(counts.head(10).index)
    periods = [(0, 20), (21, 40), (41, 61), (62, 75)]
    recent_top10 = set(orders[orders.order_day >= 62].vendor_id.value_counts().head(10).index)
    return {
        "top10_restaurants_order_share": float(counts.head(10).sum() / counts.sum()),
        "top10_restaurant_orders_each": [int(counts.iloc[0]), int(counts.iloc[9])],
        "all_time_top10_share_by_period": {f"{first}-{last}": round(float(
            orders[(orders.order_day >= first) & (orders.order_day <= last)].vendor_id.isin(top10).mean()), 5)
            for first, last in periods},
        "all_time_top10_last_order_day": sorted(int(day) for day in orders[orders.vendor_id.isin(top10)]
                                                .groupby("vendor_id").order_day.max()),
        "top10_last_14_days_overlap_with_all_time_top10": len(top10 & recent_top10),
    }


def catalog(items, products, orders):
    counts = items.groupby(["vendor_id", "product_id"]).size().sort_values(ascending=False)
    shares = counts.cumsum() / counts.sum()
    vendor_counts = orders.vendor_id.value_counts()
    return {
        "catalog_items": int(len(products)),
        "items_ever_ordered": int(len(counts)),
        "never_ordered_share": float(1 - len(counts) / len(products)),
        "top_1pct_items_order_share": float(shares.iloc[int(len(counts) * 0.01) - 1]),
        "top_10pct_items_order_share": float(shares.iloc[int(len(counts) * 0.10) - 1]),
        "vendors_with_orders": int(len(vendor_counts)),
        "top_10pct_vendors_order_share": float(vendor_counts.head(int(len(vendor_counts) * 0.1)).sum() / vendor_counts.sum()),
        "items_per_order_mean": float(items.groupby("order_id").size().mean()),
    }, counts


def price(items, products, vendors):
    from meal_discovery.pricing import price_band
    priced = products.merge(vendors[["vendor_id", "primary_cuisine"]], on="vendor_id")
    priced["level"] = [price_band(p, c)["level"] for p, c in zip(priced.unit_price, priced.primary_cuisine)]
    ordered = items.merge(priced, on=["vendor_id", "product_id"])
    catalog_mix = priced.level.value_counts(normalize=True, dropna=False)
    order_mix = ordered.level.value_counts(normalize=True, dropna=False)
    label = lambda value: "unknown" if pd.isna(value) else str(int(value))  # noqa: E731
    return {
        "catalog_band_share": {label(k): round(float(v), 4) for k, v in catalog_mix.items()},
        "ordered_item_band_share": {label(k): round(float(v), 4) for k, v in order_mix.items()},
        "note": "Bands are tertiles of recorded prices within each cuisine; unknown = price recorded as 0.",
    }


def charts(out, explore, ctx, lift, counts, price_mix):
    out.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"text.parse_math": False, "font.family": "DejaVu Sans", "font.size": 11, "axes.spines.top": False,
                         "axes.spines.right": False, "axes.edgecolor": MUTED, "axes.labelcolor": INK,
                         "xtick.color": INK, "ytick.color": INK, "figure.dpi": 150})

    figure, axis = plt.subplots(figsize=(7.5, 4.2))
    rows = explore["by_prior_orders"]
    values = [row["new_vendor_share"] * 100 for row in rows]
    bars = axis.bar([row["prior_orders"] for row in rows], values, color=BRAND, width=0.6)
    axis.bar_label(bars, labels=[f"{v:.0f}%" for v in values], padding=3, color=INK, fontweight="bold")
    axis.set_ylim(0, 100)
    axis.set_xlabel("Pedidos anteriores do cliente (janela de 30+ dias)")
    axis.set_ylabel("Pedidos em restaurante nunca usado (%)")
    axis.set_title("Mesmo clientes frequentes trocam de restaurante", loc="left", fontweight="bold", color=INK)
    figure.tight_layout()
    figure.savefig(out / "exploration-by-history.png")
    plt.close(figure)

    figure, axis = plt.subplots(figsize=(8, 4.6))
    shown = lift.T
    image = axis.imshow(shown.values, cmap="BrBG", vmin=0, vmax=2, aspect="auto")
    axis.set_xticks(range(len(shown.columns)), labels=[str(c) for c in shown.columns])
    axis.set_yticks(range(len(shown.index)), labels=shown.index)
    for (row, column), value in np.ndenumerate(shown.values):
        axis.text(column, row, f"{value:.1f}×", ha="center", va="center", fontsize=8,
                  color="white" if abs(value - 1) > 0.6 else INK)
    axis.set_title("O que se pede muda com o horário (vs. média do dia)", loc="left",
                   fontweight="bold", color=INK)
    figure.colorbar(image, ax=axis, shrink=0.8)
    figure.tight_layout()
    figure.savefig(out / "cuisine-by-time-slot.png")
    plt.close(figure)

    figure, axis = plt.subplots(figsize=(7.5, 4.2))
    cumulative = (counts.cumsum() / counts.sum()).values
    x = np.arange(1, len(cumulative) + 1) / len(cumulative) * 100
    axis.plot(x, cumulative * 100, color=BRAND, linewidth=2.5)
    axis.plot([0, 100], [0, 100], color=MUTED, linestyle="--", linewidth=1)
    axis.set_xlabel("Itens já pedidos, do mais ao menos pedido (%)")
    axis.set_ylabel("Pedidos acumulados (%)")
    axis.set_title("Poucos itens concentram a demanda", loc="left", fontweight="bold", color=INK)
    figure.tight_layout()
    figure.savefig(out / "long-tail.png")
    plt.close(figure)

    figure, axis = plt.subplots(figsize=(7.5, 3.6))
    labels = {"1": "$ barato", "2": "$$ médio", "3": "$$$ mais caro", "unknown": "sem preço"}
    keys = ["1", "2", "3", "unknown"]
    y = np.arange(2)
    left = np.zeros(2)
    for key, color in zip(keys, [BRAND, GOLD, ACCENT, MUTED]):
        widths = np.array([price_mix["catalog_band_share"].get(key, 0), price_mix["ordered_item_band_share"].get(key, 0)]) * 100
        axis.barh(y, widths, left=left, color=color, label=labels[key])
        for index, width in enumerate(widths):
            if width > 6:
                axis.text(left[index] + width / 2, index, f"{width:.0f}%", ha="center", va="center", color="white",
                          fontweight="bold")
        left += widths
    axis.set_yticks(y, labels=["Catálogo", "Itens pedidos"])
    axis.invert_yaxis()
    axis.set_xlim(0, 100)
    axis.legend(ncols=4, loc="upper center", bbox_to_anchor=(0.5, -0.12), frameon=False)
    axis.set_title("Faixa de preço: catálogo vs. o que é pedido", loc="left", fontweight="bold", color=INK)
    figure.tight_layout()
    figure.savefig(out / "price-bands.png")
    plt.close(figure)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=ROOT / "data/processed/singapore-official-v1.sqlite")
    parser.add_argument("--output", type=Path, default=ROOT / "evaluations/results/business-analysis-v1.json")
    parser.add_argument("--charts", type=Path, default=ROOT / "docs/analysis")
    args = parser.parse_args()
    manifest, orders, items, vendors, products = load(args.database)
    explore = exploration(orders, items)
    ctx, lift = context(orders)
    catalog_stats, counts = catalog(items, products, orders)
    price_mix = price(items, products, vendors)
    charts(args.charts, explore, ctx, lift, counts, price_mix)
    result = {"schema_version": 1, "analysis_version": "business-analysis-v1",
              "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "data_kind": manifest["data_kind"], "city": manifest["city"], "source_hashes": manifest["source_hashes"],
              "relative_days": manifest["relative_days"], "lookback_start_day": LOOKBACK_START,
              "customers_and_retention": retention(orders), "exploration": explore, "context": ctx,
              "catalog": catalog_stats, "price_bands": price_mix,
              "limitations": ["76 observed days; behaviour before day 0 is unknown, so history-based numbers use days 30+.",
                              "Vendor identifiers are outlets; chain_id groups outlets of the same brand when present.",
                              "Geohash is the anonymized order region (~5 km cells), not an exact address.",
                              "Observational data: shares describe behaviour, they do not prove causes."]}
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("customers_and_retention", "exploration", "catalog", "price_bands")},
                     ensure_ascii=False, indent=1))
    print(json.dumps({k: v for k, v in ctx.items() if k not in ("hour_share", "cuisine_lift_by_slot")}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
