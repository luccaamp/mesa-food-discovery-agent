import unittest
from meal_discovery.discovery import expand_query, guarded_constraint


class FallbackRegressionTests(unittest.TestCase):
    def test_switch_prefix_is_removed_but_unknown_terms_remain(self):
        self.assertEqual(expand_query("Agora quero chá com leite")[0], "tea milk")
        self.assertEqual(expand_query("Agora eu prefiro arroz frito")[0], "rice fried")
        self.assertEqual(expand_query("pizza xyz")[0], "pizza xyz")

    def test_politeness_and_negation(self):
        self.assertEqual(expand_query("Cheese pizza please")[0], "cheese pizza")
        self.assertIsNotNone(guarded_constraint("Agora quero chá sem leite"))
        self.assertFalse(expand_query("Agora quero chá sem leite")[1])

    def test_catalog_search_framing_preserves_unknowns_and_exclusions(self):
        self.assertEqual(expand_query("Gostaria de encontrar sopa de peixe no catálogo")[0], "soup fish")
        self.assertEqual(expand_query("Quero buscar pizza xyz no catálogo!")[0], "pizza xyz")
        self.assertEqual(expand_query("pizza encontrar catalogo")[0], "pizza encontrar catalogo")
        self.assertFalse(expand_query("Gostaria de encontrar sopa sem peixe no catálogo")[1])


if __name__ == "__main__":
    unittest.main()
