"""Which restaurants and items should the app show? Replayed against real next orders.

Protocol (frozen in configs/discovery-experiment-v1.json before any run):
  validation   history through day 61, targets = first order per customer on days 62-75
  final test   history through day 75, targets = first order per customer in the official
               DHRD test file (days 76-90), run once with --final-test

Restaurant models: city popularity, region popularity, region x time-slot popularity,
the customer's own restaurants, and a LightGBM LambdaRank ranker that combines them.
Item models reuse the same signals. Results are split by segment: new customers (cold),
returning customers going back to a known restaurant, and returning customers trying a
new one, which the business analysis shows is most returning orders.

Run: python analysis/discovery_experiment.py            (validation)
     python analysis/discovery_experiment.py --final-test
"""

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from math import log2
from pathlib import Path
import sqlite3
from time import perf_counter

import lightgbm as lgb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs/discovery-experiment-v1.json"
TEST_FILE = ROOT / "data/raw/dhrd-official-v1/data_sg/orders_sg_test.txt"
SLOT_EDGES = [-1, 5, 10, 13, 16, 20, 23]
SLOT_NAMES = ["madrugada", "manha", "almoco", "tarde", "jantar", "noite"]
FEATURES = ["visits", "days_since_visit", "visit_share", "chain_visits", "customer_orders", "cuisine_share",
            "pop_city", "pop_recent", "pop_region", "pop_region_slot", "region_slot_share", "slot_share",
            "same_region", "cuisine_slot_lift", "rank_region_slot", "rank_region"]


def slot_of(hours):
    return pd.cut(hours, SLOT_EDGES, labels=SLOT_NAMES).astype(str)


def load(database):
    connection = sqlite3.connect(Path(database).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        manifest = json.loads(connection.execute("SELECT value FROM metadata WHERE key='manifest'").fetchone()[0])
        if manifest.get("data_kind") != "official_dhrd":
            raise SystemExit("The experiment runs only on the verified official dataset")
        orders = pd.read_sql("""SELECT o.order_id, o.customer_id, o.order_day, o.order_time, c.geohash
                                FROM orders o JOIN order_context c USING(order_id)""", connection)
        items = pd.read_sql("SELECT order_id, vendor_id, product_id FROM order_items", connection)
        vendors = pd.read_sql("""SELECT v.vendor_id, v.primary_cuisine, x.chain_id, x.geohash AS vendor_geohash
                                 FROM vendors v LEFT JOIN vendor_context x USING(vendor_id)""", connection)
    finally:
        connection.close()
    orders = orders.merge(items.drop_duplicates("order_id")[["order_id", "vendor_id"]], on="order_id")
    return manifest, prepare(orders, vendors), items, vendors


def prepare(orders, vendors):
    orders = orders.merge(vendors, on="vendor_id", how="left")
    orders["slot"] = slot_of(orders.order_time.str[:2].astype(int))
    orders["chain"] = orders.chain_id.fillna("vendor:" + orders.vendor_id)
    return orders.sort_values(["order_day", "order_time", "order_id"]).reset_index(drop=True)


def load_test(vendors):
    raw = pd.read_csv(TEST_FILE, usecols=["customer_id", "geohash", "order_id", "vendor_id", "product_id",
                                          "order_time", "order_day"], dtype=str)
    raw["order_id"] = "test:" + raw.order_id  # identifiers restart in the test file
    raw["order_day"] = raw.order_day.str.extract(r"(\d+)")[0].astype(int)
    items = raw[["order_id", "vendor_id", "product_id"]].drop_duplicates()
    orders = raw.drop_duplicates("order_id")[["order_id", "customer_id", "order_day", "order_time", "geohash", "vendor_id"]]
    return prepare(orders, vendors), items


def targets_of(orders, items, first_day, last_day):
    window = orders[(orders.order_day >= first_day) & (orders.order_day <= last_day)]
    first = window.drop_duplicates("customer_id").copy()
    basket = items[items.order_id.isin(first.order_id)].groupby("order_id").apply(
        lambda frame: set(zip(frame.vendor_id, frame.product_id)), include_groups=False)
    first["items"] = first.order_id.map(basket)
    return first.reset_index(drop=True).rename_axis("tid").reset_index()


class History:
    """Everything a model may know at the cutoff: orders and items up to and including that day."""

    def __init__(self, orders, items, cutoff, with_items=True):
        self.cutoff = cutoff
        hist = orders[orders.order_day <= cutoff]
        self.customer_vendor = hist.groupby(["customer_id", "vendor_id"]).agg(
            visits=("order_id", "size"), last_day=("order_day", "max")).reset_index()
        self.customer_orders = hist.groupby("customer_id").size().rename("customer_orders")
        self.customer_cuisine = hist.groupby(["customer_id", "primary_cuisine"]).size().rename("cuisine_orders").reset_index()
        self.customer_chain = hist.groupby(["customer_id", "chain"]).size().rename("chain_visits").reset_index()
        self.pop_city = hist.groupby("vendor_id").size().rename("pop_city")
        self.pop_recent = hist[hist.order_day > cutoff - 14].groupby("vendor_id").size().rename("pop_recent")
        self.pop_region = hist.groupby(["geohash", "vendor_id"]).size().rename("pop_region").reset_index()
        self.pop_region_slot = hist.groupby(["geohash", "slot", "vendor_id"]).size().rename("pop_region_slot").reset_index()
        self.region_slot_total = hist.groupby(["geohash", "slot"]).size().rename("region_slot_total").reset_index()
        self.pop_slot = hist.groupby(["vendor_id", "slot"]).size().rename("vendor_slot_orders").reset_index()
        cuisine_day = hist.primary_cuisine.value_counts(normalize=True)
        cuisine_slot = pd.crosstab(hist.slot, hist.primary_cuisine, normalize="index")
        self.cuisine_slot_lift = (cuisine_slot / cuisine_day).stack().rename("cuisine_slot_lift").reset_index()
        self.pop_region = self._ranked(self.pop_region, ["geohash"], "rank_region")
        self.pop_region_slot = self._ranked(self.pop_region_slot, ["geohash", "slot"], "rank_region_slot")
        self.city_order = list(self.pop_city.sort_values(ascending=False, kind="stable").index)
        if with_items:
            self._items(items, hist)

    @staticmethod
    def _ranked(frame, keys, name):
        frame = frame.sort_values(keys + [frame.columns[-1], "vendor_id"], ascending=[True] * len(keys) + [False, True])
        return frame.assign(**{name: frame.groupby(keys).cumcount() + 1})

    def _items(self, items, hist):
        """Item-level popularity and per-customer item history, for the item models only."""
        lines = items.merge(hist[["order_id", "customer_id", "order_day", "geohash", "slot"]], on="order_id")
        self.customer_items = lines.groupby(["customer_id", "vendor_id", "product_id"]).agg(
            count=("order_id", "size"), last_day=("order_day", "max")).reset_index().sort_values(
            ["customer_id", "count", "last_day", "vendor_id", "product_id"], ascending=[True, False, False, True, True])
        item_city = lines.groupby(["vendor_id", "product_id"]).size().sort_values(ascending=False, kind="stable")
        self.items_city = list(item_city.index[:200])
        item_region_slot = lines.groupby(["geohash", "slot", "vendor_id", "product_id"]).size().rename("n").reset_index()
        item_region_slot = item_region_slot.sort_values(["geohash", "slot", "n", "vendor_id", "product_id"],
                                                        ascending=[True, True, False, True, True])
        self.items_region_slot = {key: list(zip(group.vendor_id, group.product_id))[:30]
                                  for key, group in item_region_slot.groupby(["geohash", "slot"])}
        item_region = lines.groupby(["geohash", "vendor_id", "product_id"]).size().rename("n").reset_index()
        item_region = item_region.sort_values(["geohash", "n", "vendor_id", "product_id"], ascending=[True, False, True, True])
        self.items_region = {key: list(zip(group.vendor_id, group.product_id))[:30]
                             for key, group in item_region.groupby("geohash")}
        vendor_items = lines.groupby(["vendor_id", "product_id"]).size().rename("n").reset_index().sort_values(
            ["vendor_id", "n", "product_id"], ascending=[True, False, True])
        self.vendor_top_items = {vendor: list(group.product_id)[:5] for vendor, group in vendor_items.groupby("vendor_id")}
        self.customer_item_lists = {customer: list(zip(group.vendor_id, group.product_id))
                                    for customer, group in self.customer_items.groupby("customer_id")}


def top_lists(history, targets, config):
    """Each popularity model as a ranked list per target, with back-off to wider contexts."""
    sizes = config["ranker"]["candidates"]
    region_slot = {key: list(group.vendor_id)[:max(sizes["region_slot"], 10)]
                   for key, group in history.pop_region_slot.groupby(["geohash", "slot"])}
    region = {key: list(group.vendor_id)[:max(sizes["region"], 10)] for key, group in history.pop_region.groupby("geohash")}
    visited = history.customer_vendor.sort_values(["customer_id", "visits", "last_day", "vendor_id"],
                                                  ascending=[True, False, False, True])
    visited = {customer: list(group.vendor_id) for customer, group in visited.groupby("customer_id")}
    city = history.city_order
    lists = defaultdict(list)
    for row in targets.itertuples():
        local_slot = region_slot.get((row.geohash, row.slot), [])
        local = region.get(row.geohash, [])
        lists["popular_global"].append(city[:10])
        lists["popular_region"].append(fill(local, city))
        lists["popular_region_slot"].append(fill(local_slot, local, city))
        lists["repeat_then_region_slot"].append(fill(visited.get(row.customer_id, []), local_slot, local, city))
        lists["_candidates"].append(dict.fromkeys(visited.get(row.customer_id, [])[:sizes["history"]] +
                                                  local_slot[:sizes["region_slot"]] + local[:sizes["region"]] +
                                                  city[:sizes["city"]]))
    return lists


def fill(*sources, k=10):
    ranked = []
    for source in sources:
        for value in source:
            if value not in ranked:
                ranked.append(value)
                if len(ranked) == k:
                    return ranked
    return ranked


def candidate_frame(history, targets, candidates, vendors):
    frame = pd.DataFrame([(tid, vendor) for tid, chosen in zip(targets.tid, candidates) for vendor in chosen],
                         columns=["tid", "vendor_id"])
    frame = frame.merge(targets[["tid", "customer_id", "geohash", "slot", "vendor_id"]].rename(
        columns={"vendor_id": "target_vendor"}), on="tid")
    frame = frame.merge(vendors[["vendor_id", "primary_cuisine", "chain_id", "vendor_geohash"]], on="vendor_id", how="left")
    frame["chain"] = frame.chain_id.fillna("vendor:" + frame.vendor_id)
    frame = frame.merge(history.customer_vendor, on=["customer_id", "vendor_id"], how="left")
    frame = frame.merge(history.customer_orders, left_on="customer_id", right_index=True, how="left")
    frame = frame.merge(history.customer_cuisine, on=["customer_id", "primary_cuisine"], how="left")
    frame = frame.merge(history.customer_chain, on=["customer_id", "chain"], how="left")
    frame = frame.merge(history.pop_city, left_on="vendor_id", right_index=True, how="left")
    frame = frame.merge(history.pop_recent, left_on="vendor_id", right_index=True, how="left")
    frame = frame.merge(history.pop_region, on=["geohash", "vendor_id"], how="left")
    frame = frame.merge(history.pop_region_slot, on=["geohash", "slot", "vendor_id"], how="left")
    frame = frame.merge(history.region_slot_total, on=["geohash", "slot"], how="left")
    frame = frame.merge(history.pop_slot, on=["vendor_id", "slot"], how="left")
    frame = frame.merge(history.cuisine_slot_lift, on=["slot", "primary_cuisine"], how="left")
    counts = ["visits", "customer_orders", "cuisine_orders", "chain_visits", "pop_city", "pop_recent", "pop_region",
              "pop_region_slot", "region_slot_total", "vendor_slot_orders"]
    frame[counts] = frame[counts].fillna(0)
    frame["days_since_visit"] = np.where(frame.visits > 0, history.cutoff - frame.last_day, np.nan)
    frame["visit_share"] = frame.visits / frame.customer_orders.replace(0, np.nan)
    frame["cuisine_share"] = frame.cuisine_orders / frame.customer_orders.replace(0, np.nan)
    frame["region_slot_share"] = frame.pop_region_slot / frame.region_slot_total.replace(0, np.nan)
    frame["slot_share"] = frame.vendor_slot_orders / frame.pop_city.replace(0, np.nan)
    frame["same_region"] = (frame.vendor_geohash == frame.geohash).astype(int)
    frame["chain_visits"] = frame.chain_visits - frame.visits
    frame["label"] = (frame.vendor_id == frame.target_vendor).astype(int)
    return frame.sort_values(["tid", "vendor_id"]).reset_index(drop=True)


def fit_ranker(frame, config):
    settings = {key: value for key, value in config["ranker"].items() if key not in {"library", "objective", "candidates", "seed"}}
    # Only targets whose real restaurant is among the candidates carry a learning signal.
    useful = frame[frame.groupby("tid").label.transform("max") == 1]
    rounds = settings.pop("n_estimators")
    params = {"objective": "lambdarank", "metric": "ndcg", "eval_at": [10], "seed": config["ranker"]["seed"],
              "deterministic": True, "verbosity": -1, **settings}
    data = lgb.Dataset(useful[FEATURES], useful.label, group=useful.groupby("tid", sort=False).size().values)
    return lgb.train(params, data, num_boost_round=rounds), int(useful.tid.nunique())


def ranked_by_model(model, frame):
    frame = frame.assign(score=model.predict(frame[FEATURES]))
    frame = frame.sort_values(["tid", "score", "vendor_id"], ascending=[True, False, True])
    return {tid: list(group.vendor_id) for tid, group in frame.groupby("tid", sort=False)}


def item_lists(history, targets, ranked_vendors):
    lists = defaultdict(list)
    for row in targets.itertuples():
        own = history.customer_item_lists.get(row.customer_id, [])
        local = history.items_region_slot.get((row.geohash, row.slot), [])
        region = history.items_region.get(row.geohash, [])
        lists["popular_global"].append(history.items_city[:10])
        lists["repeat_then_global"].append(fill(own, history.items_city))
        lists["popular_region_slot"].append(fill(local, region, history.items_city))
        lists["repeat_then_region_slot"].append(fill(own, local, region, history.items_city))
        lists["repeat_6_plus_discovery_4"].append(fill(own[:6], local, region, own, history.items_city))
        chosen = []
        for vendor in ranked_vendors.get(row.tid, []):
            mine = [item for item in own if item[0] == vendor]
            theirs = [(vendor, product) for product in history.vendor_top_items.get(vendor, [])]
            chosen.extend(fill(mine, theirs, k=3))
            if len(chosen) >= 10:
                break
        lists["ranker_items"].append(fill(chosen, local, region, history.items_city))
    return lists


def segment_of(targets, history):
    known = set(history.customer_orders.index)
    pairs = set(zip(history.customer_vendor.customer_id, history.customer_vendor.vendor_id))
    return np.array(["cold" if customer not in known else "warm_repeat" if (customer, vendor) in pairs else "warm_new"
                     for customer, vendor in zip(targets.customer_id, targets.vendor_id)])


def restaurant_scores(ranked, truth, segments):
    rows = []
    for ranking, target in zip(ranked, truth):
        position = ranking[:10].index(target) + 1 if target in ranking[:10] else None
        rows.append((position is not None, 1 / position if position else 0.0))
    return summarize(rows, segments, ("hit@10", "mrr@10"))


def item_scores(ranked, baskets, segments):
    rows = []
    for ranking, basket in zip(ranked, baskets):
        hits = [item in basket for item in ranking[:10]]
        dcg = sum(hit / log2(index + 2) for index, hit in enumerate(hits))
        ideal = sum(1 / log2(index + 2) for index in range(min(10, len(basket))))
        rows.append((sum(hits) / len(basket), float(any(hits)), dcg / ideal))
    return summarize(rows, segments, ("recall@10", "hit@10", "ndcg@10"))


def summarize(rows, segments, names):
    values = np.array(rows, dtype=float)
    result = {"all": {"customers": len(values), **{name: round(float(values[:, i].mean()), 5) for i, name in enumerate(names)}}}
    for segment in ("cold", "warm_repeat", "warm_new"):
        mask = segments == segment
        result[segment] = {"customers": int(mask.sum()),
                           **{name: round(float(values[mask, i].mean()), 5) for i, name in enumerate(names)}}
    return result


def run(stage, config, orders, items, test_orders=None, test_items=None, vendors=None, log=print):
    dev, val, final = config["development"], config["validation"], config["final_test"]
    if stage == "validation":
        fit_history, fit_targets = dev["history_end_day_inclusive"], dev["targets_days_inclusive"]
        eval_cutoff = val["history_end_day_inclusive"]
        all_orders, all_items = orders, items
        eval_targets = targets_of(orders, items, *val["targets_days_inclusive"])
    else:
        fit_history, fit_targets = val["history_end_day_inclusive"], val["targets_days_inclusive"]
        eval_cutoff = final["history_end_day_inclusive"]
        all_orders, all_items = pd.concat([orders, test_orders]), pd.concat([items, test_items])
        eval_targets = targets_of(test_orders, test_items, 76, 90)
    started = perf_counter()
    train_history = History(orders, items, fit_history, with_items=False)
    train_targets = targets_of(orders, items, *fit_targets)
    train_frame = candidate_frame(train_history, train_targets, top_lists(train_history, train_targets, config)["_candidates"], vendors)
    model, fitted_on = fit_ranker(train_frame, config)
    log(f"ranker fitted on {fitted_on:,} targets in {perf_counter() - started:.0f}s")
    history = History(all_orders, all_items, eval_cutoff)
    lists = top_lists(history, eval_targets, config)
    frame = candidate_frame(history, eval_targets, lists.pop("_candidates"), vendors)
    by_model = ranked_by_model(model, frame)
    lists["ranker"] = [by_model.get(tid, [])[:10] for tid in eval_targets.tid]
    # Product policy: keep 4 of 10 positions for discovery in the region and time slot.
    lists["ranker_6_plus_discovery_4"] = [fill(ranked[:6], local, ranked) for ranked, local in
                                          zip(lists["ranker"], lists["popular_region_slot"])]
    segments = segment_of(eval_targets, history)
    truth = list(eval_targets.vendor_id)
    restaurants = {name: restaurant_scores(ranked, truth, segments) for name, ranked in lists.items()}
    coverage = frame.groupby("tid").label.max().reindex(eval_targets.tid, fill_value=0)
    items_ranked = item_lists(history, eval_targets, by_model)
    baskets = list(eval_targets["items"])
    item_results = {name: item_scores(ranked, baskets, segments) for name, ranked in items_ranked.items()}
    importance = dict(sorted(zip(FEATURES, (int(v) for v in model.feature_importance("gain"))),
                             key=lambda pair: -pair[1]))
    return {
        "stage": stage, "history_end_day_inclusive": eval_cutoff,
        "targets": {"customers": int(len(eval_targets)),
                    "segments": {name: int((segments == name).sum()) for name in ("cold", "warm_repeat", "warm_new")},
                    "candidate_recall": round(float(coverage.mean()), 5)},
        "ranker": {"fitted_on_history_end_day": fit_history, "fitted_on_targets_days": fit_targets,
                   "fitted_targets_with_positive": fitted_on, "feature_gain": importance},
        "restaurants": restaurants, "items": item_results,
        "runtime_seconds": round(perf_counter() - started, 1),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=ROOT / "data/processed/singapore-official-v1.sqlite")
    parser.add_argument("--final-test", action="store_true", help="Evaluate once on the official test file")
    args = parser.parse_args()
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    manifest, orders, items, vendors = load(args.database)
    test_orders = test_items = None
    stage = "final_test" if args.final_test else "validation"
    if args.final_test:
        if hashlib.sha256(TEST_FILE.read_bytes()).hexdigest() != manifest["official_test_reference"]["sha256"]:
            raise SystemExit("Official test file does not match the pinned hash")
        test_orders, test_items = load_test(vendors)
    result = run(stage, config, orders, items, test_orders, test_items, vendors)
    output = ROOT / f"evaluations/results/discovery-{'test' if args.final_test else 'validation'}-v1.json"
    result = {"schema_version": 1, "protocol_version": config["protocol_version"],
              "protocol_sha256": hashlib.sha256(CONFIG.read_bytes()).hexdigest(),
              "implementation_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "data_kind": manifest["data_kind"], "city": manifest["city"], "source_hashes": manifest["source_hashes"],
              **result, "limitations": config["limitations"]}
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("targets", "restaurants", "items", "ranker", "runtime_seconds")}, indent=1))


if __name__ == "__main__":
    main()
