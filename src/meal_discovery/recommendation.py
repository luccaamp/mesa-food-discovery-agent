"""Inspectable training-only reference recommenders, not production-scale ANN."""

from collections import Counter, defaultdict
from functools import lru_cache
from heapq import nsmallest
from itertools import combinations
from math import sqrt

Item = tuple[str, str]
MODELS = ("popularity", "repeat", "item_cosine", "basket_cosine")
DEFAULT_MODELS = ("popularity", "repeat", "basket_cosine")


class Recommender:
    def __init__(self, training_baskets, *, shrinkage: float = 10.0, history_limit: int = 20,
                 neighbor_limit: int = 100, include_user_similarity: bool = True,
                 include_basket_similarity: bool = False, progress=None):
        if shrinkage < 0 or history_limit < 1 or neighbor_limit < 1:
            raise ValueError("Invalid similarity parameters")
        self.shrinkage = shrinkage
        self.history_limit = history_limit
        self.neighbor_limit = neighbor_limit
        self.include_user_similarity = include_user_similarity
        self.include_basket_similarity = include_basket_similarity
        self.popularity = Counter()
        self.history = defaultdict(Counter)
        self.item_users = defaultdict(set)
        self.basket_pairs = defaultdict(Counter)
        self.training_orders = 0
        canonical = {}
        for customer, items in training_baskets:
            unique = {canonical.setdefault(item, item) for item in items}
            self.popularity.update(unique)
            self.history[customer].update(unique)
            if include_user_similarity:
                for item in unique:
                    self.item_users[item].add(customer)
            if include_basket_similarity:
                for left, right in combinations(sorted(unique), 2):
                    self.basket_pairs[left][right] += 1
                    self.basket_pairs[right][left] += 1
            self.training_orders += 1
            if progress and self.training_orders % 100_000 == 0:
                progress(f"Fit {self.training_orders:,} training baskets")
        if not self.popularity:
            raise ValueError("Training period has no items")
        self.catalog = frozenset(self.popularity)
        self.fallback = sorted(self.catalog, key=lambda item: (-self.popularity[item], item))
        self._basket_neighbors = lru_cache(maxsize=4096)(self._compute_basket_neighbors)

    def _compute_basket_neighbors(self, seed):
        def score(item):
            overlap = self.basket_pairs[seed][item]
            cosine = overlap / sqrt(self.popularity[seed] * self.popularity[item])
            return cosine * overlap / (overlap + self.shrinkage)
        pairs = self.basket_pairs.get(seed, {})
        selected = nsmallest(self.neighbor_limit, pairs,
                             key=lambda item: (-score(item), -self.popularity[item], item))
        return tuple((item, score(item)) for item in selected)

    def recommend(self, customer: str, model: str, k: int) -> list[Item]:
        if model not in MODELS or k < 1:
            raise ValueError("Unknown model or invalid k")
        history = self.history.get(customer, Counter())
        if model == "popularity" or not history:
            return self.fallback[:k]
        if model == "repeat":
            ranked = sorted(history, key=lambda item: (-history[item], -self.popularity[item], item))
        elif model == "basket_cosine":
            if not self.include_basket_similarity:
                raise ValueError("Basket similarity was not fitted")
            scores = defaultdict(float)
            seeds = sorted(history, key=lambda item: (-history[item], item))[:self.history_limit]
            for seed in seeds:
                for item, score in self._basket_neighbors(seed):
                    scores[item] += score
            ranked = nsmallest(k, scores, key=lambda item: (-scores[item], -self.popularity[item], item))
        else:
            if not self.include_user_similarity:
                raise ValueError("User-based item similarity was not fitted")
            scores = defaultdict(float)
            seeds = sorted(history, key=lambda item: (-history[item], item))[:self.history_limit]
            for seed in seeds:
                common_users = Counter()
                for peer in sorted(self.item_users[seed]):
                    common_users.update(self.history[peer].keys())
                for item, overlap in common_users.items():
                    if item == seed:
                        continue
                    cosine = overlap / sqrt(len(self.item_users[seed]) * len(self.item_users[item]))
                    scores[item] += cosine * overlap / (overlap + self.shrinkage)
            ranked = nsmallest(k, scores, key=lambda item: (-scores[item], -self.popularity[item], item))
        # Repeats are allowed; use deterministic popularity backfill without duplicate IDs.
        result = ranked[:k]
        selected = set(result)
        for item in self.fallback:
            if len(result) >= k:
                break
            if item not in selected:
                result.append(item)
                selected.add(item)
        return result
