from datetime import datetime, timedelta, timezone
import unittest

from meal_discovery import tools
from meal_discovery.api_models import AssistantContext, RecommendationParams
from meal_discovery.context_popularity import CITY, REGION_NAMES, _artifact, popular_here, regions, slot_at

SG = timezone(timedelta(hours=8))


class ContextPopularityTests(unittest.TestCase):
    def test_slots_follow_singapore_time(self):
        cases = {0: "madrugada", 5: "madrugada", 6: "manha", 11: "almoco", 14: "tarde", 17: "jantar", 20: "jantar",
                 21: "noite", 23: "noite"}
        for hour, slot in cases.items():
            self.assertEqual(slot_at(datetime(2026, 11, 12, hour, 30, tzinfo=SG)), slot)
        # 12:30 UTC is 20:30 in Singapore.
        self.assertEqual(slot_at(datetime(2026, 11, 12, 12, 30, tzinfo=timezone.utc)), "jantar")

    def test_every_region_in_the_artifact_has_a_name_and_every_slot(self):
        data = _artifact()
        self.assertEqual(set(data["region_orders"]), set(REGION_NAMES))
        for scope, lists in data["regions"].items():
            self.assertEqual(len(lists), 6, scope)
        names = [region["name"] for region in regions()]
        self.assertEqual(names, sorted(names))

    def test_lists_are_ranked_and_unknown_regions_use_the_city(self):
        scope, slot, entries = popular_here("w21zt", "jantar")
        self.assertEqual((scope, slot), ("w21zt", "jantar"))
        counts = [count for _, _, count in entries]
        self.assertEqual(counts, sorted(counts, reverse=True))
        self.assertEqual(popular_here("zzzzz", "manha")[0], CITY)
        self.assertEqual(popular_here(None, "manha")[0], CITY)
        with self.assertRaises(ValueError):
            popular_here(None, "brunch")

    def test_region_and_regional_lists_differ_from_the_city(self):
        _, _, city = popular_here(None, "jantar")
        _, _, local = popular_here("w23b1", "jantar")
        overlap = {entry[:2] for entry in city[:20]} & {entry[:2] for entry in local[:20]}
        self.assertLess(len(overlap), 10)

    def test_region_must_look_like_a_geohash(self):
        with self.assertRaises(ValueError):
            RecommendationParams(region="'; DROP")
        with self.assertRaises(ValueError):
            AssistantContext(region="w21z")


class RecommendToolAnswerTests(unittest.TestCase):
    def test_answer_names_the_place_and_time(self):
        item = {"vendor_id": "v", "product_id": "p", "name": "Kopi", "unit_price": 0.001, "primary_cuisine": "coffee",
                "reason": "popular_here"}
        result = {"items": [item], "context": {"region": {"id": "w21zt", "name": "Tampines"}, "slot": "manha",
                                               "slot_label": "de manhã"}}
        captured = {}

        def recommender(arguments):
            captured.update(arguments)
            return result
        outcome = tools.recommend(recommender, AssistantContext(region="w21zt"))
        self.assertIn("em Tampines de manhã", outcome.answer)
        self.assertEqual(captured["region"], "w21zt")
        city = tools.recommend(lambda arguments: {**result, "context": {**result["context"], "region": None}},
                               AssistantContext())
        self.assertIn("em Singapura de manhã", city.answer)


class LocalDemandRankingTests(unittest.TestCase):
    def test_reorders_by_local_demand_and_keeps_bm25_order_on_ties(self):
        from meal_discovery.context_popularity import local_demand, rank_by_local_demand
        demand = local_demand("w21zt", "jantar")
        busiest = max(demand, key=demand.get)
        items = [{"vendor_id": "unknown-a"}, {"vendor_id": "unknown-b"}, {"vendor_id": busiest}]
        ranked = rank_by_local_demand(items, "w21zt", "jantar")
        self.assertEqual([item["vendor_id"] for item in ranked], [busiest, "unknown-a", "unknown-b"])
        self.assertEqual(rank_by_local_demand(items, None, "jantar"), items)

    def test_search_tool_widens_the_pool_and_reports_the_ranking_only_with_a_region(self):
        class Reader:
            def __init__(self):
                self.limits = []

            def search(self, params):
                self.limits.append(params.limit)
                return {"items": [{"vendor_id": "v", "product_id": "p", "name": "Laksa", "unit_price": 0.003,
                                   "primary_cuisine": "laksa"}], "total_matches": 1}
        reader = Reader()
        local = tools.search(reader, AssistantContext(region="w21zt"), "laksa")
        plain = tools.search(reader, AssistantContext(), "laksa")
        self.assertEqual(reader.limits, [50, 6])
        self.assertEqual(local.trace["arguments"]["ranking"], "local_demand")
        self.assertEqual(plain.trace["arguments"]["ranking"], "bm25")
        self.assertIn("sua região", local.answer)


class RegionMentionTests(unittest.TestCase):
    def test_a_named_place_sets_the_region_and_alone_asks_for_what_is_popular_there(self):
        from meal_discovery.policies import apply
        for message, region in (("estou em Tampines", "w21zt"), ("perto de Jurong West", "w21xx"),
                                ("o que tem em alta em Punggol?", "w23bh"), ("in Woodlands please", "w23b1")):
            with self.subTest(message=message):
                result = apply(message, AssistantContext())
                self.assertEqual(result.context.region, region)
                self.assertEqual(result.plan.action, "recommend_items")

    def test_a_dish_with_a_place_keeps_the_dish_for_the_model(self):
        from meal_discovery.policies import apply
        result = apply("laksa barata perto de Orchard", AssistantContext())
        self.assertEqual((result.context.region, result.context.price_level), ("w21z6", 1))
        self.assertEqual(result.planning_message, "laksa")
        self.assertIsNone(apply("quero pizza", AssistantContext()).context.region)
        # The region persists across turns until another place is named.
        follow = apply("agora sushi", AssistantContext(region="w21zt"))
        self.assertEqual(follow.context.region, "w21zt")
