from pathlib import Path
import tempfile
import unittest

from meal_discovery.api_models import AssistantContext
from meal_discovery.catalog import build_catalog, search_catalog
from meal_discovery.policies import apply
from meal_discovery.pricing import _bands, describe, level_clause, price_band
from meal_discovery.singapore import prepare_singapore
from test_singapore import source_fixture


class PriceBandTests(unittest.TestCase):
    def test_bands_are_tertiles_within_the_cuisine(self):
        coffee = _bands()["coffee"]
        cheap, middle = coffee.cuts
        self.assertLess(cheap, middle)
        self.assertEqual(price_band(cheap, "coffee")["level"], 1)
        self.assertEqual(price_band(middle, "coffee")["level"], 2)
        self.assertEqual(price_band(middle + 0.0004, "coffee")["level"], 3)
        # The same price can be cheap for pizza and pricey for coffee: bands are relative to the cuisine.
        self.assertEqual(price_band(0.004, "pizza")["level"], 1)
        self.assertEqual(price_band(0.004, "coffee")["level"], 3)

    def test_share_of_pricier_items_reads_as_a_sentence(self):
        band = price_band(0.0012, "coffee")
        self.assertGreater(band["pricier_share"], 0.5)
        self.assertRegex(describe(band), r"^\$ · mais barato que \d+% dos itens de coffee$")
        expensive = price_band(0.05, "coffee")
        self.assertRegex(describe(expensive), r"^\$\$\$ · mais caro que \d+% dos itens de coffee$")

    def test_a_recorded_zero_is_an_unknown_price_not_a_cheap_one(self):
        for value in (0, None):
            band = price_band(value, "pizza")
            self.assertIsNone(band["level"])
            self.assertEqual(describe(band), "preço não informado")

    def test_unknown_cuisines_fall_back_to_the_whole_catalog(self):
        self.assertEqual(price_band(0.0001, "not-a-cuisine")["level"], 1)
        with self.assertRaises(ValueError):
            level_clause(4)


class PriceBandFilterTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        source_fixture(root / "raw")
        prepare_singapore(root / "raw", root / "source.sqlite", allow_test_data=True)
        self.index = root / "catalog.sqlite"
        build_catalog(root / "source.sqlite", self.index, allow_test_data=True)

    def test_items_carry_a_band_and_the_level_filter_applies_in_sql(self):
        result = search_catalog(self.index, "Test", allow_test_data=True)
        self.assertTrue(all("price_band" in item for item in result["items"]))
        # Fixture prices (1 and 2) sit above every real cuisine's cheapest third.
        self.assertEqual(search_catalog(self.index, "Test", price_level=1, allow_test_data=True)["items"], [])
        self.assertEqual(len(search_catalog(self.index, "Test", price_level=3, allow_test_data=True)["items"]), 2)


class PricePolicyTests(unittest.TestCase):
    def test_cheap_words_set_a_band_and_keep_the_dish(self):
        result = apply("pizza barata", AssistantContext())
        self.assertEqual(result.context.price_level, 1)
        self.assertEqual(result.planning_message, "pizza")

    def test_price_only_follow_up_refines_the_last_search(self):
        result = apply("e mais barato?", AssistantContext(last_query="laksa"))
        self.assertEqual(result.planner, "explicit_filter_refinement")
        self.assertEqual(result.plan.query, "laksa")
        self.assertEqual(result.context.price_level, 1)

    def test_not_too_expensive_is_a_price_request_not_an_exclusion(self):
        result = apply("algo não muito caro", AssistantContext())
        self.assertIsNone(result.answer)
        self.assertEqual(result.context.price_level, 2)
        self.assertEqual(result.planner, "explicit_recommendation")

    def test_any_price_clears_the_band(self):
        result = apply("qualquer preço", AssistantContext(last_query="pizza", price_level=1, max_price=0.01))
        self.assertIsNone(result.context.price_level)
        self.assertIsNone(result.context.max_price)

    def test_currency_budget_points_to_bands_and_diets_stay_guarded(self):
        self.assertIn("barata", apply("até R$ 20", AssistantContext()).answer)
        self.assertIn("não informa ingredientes", apply("sem glúten barato", AssistantContext()).answer)
