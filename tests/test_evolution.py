"""Unit tests for Kai'Sa evolution mechanics and damage profiling."""

import unittest
from markov.engine.evolution import (
    calculate_item_stats,
    determine_damage_profile,
    estimate_kaisa_q_level,
    estimate_kaisa_e_level,
    get_early_components,
    track_evolution_progress,
)


class TestEvolution(unittest.TestCase):
    def setUp(self):
        # Sample mock items
        self.mock_items = {
            "1055": {  # Doran's Blade
                "name": "Doran's Blade",
                "gold": {"total": 450},
                "stats": {"FlatPhysicalDamageMod": 10},
                "from": [],
            },
            "3031": {  # Infinity Edge
                "name": "Infinity Edge",
                "gold": {"total": 3500},
                "stats": {"FlatPhysicalDamageMod": 75},
                "from": ["1038", "1037", "1018"],
            },
            "1037": {  # Pickaxe
                "name": "Pickaxe",
                "gold": {"total": 875},
                "stats": {"FlatPhysicalDamageMod": 25},
                "from": [],
            },
            "3006": {  # Berserker's Greaves
                "name": "Berserker's Greaves",
                "gold": {"total": 1100},
                "stats": {"PercentAttackSpeedMod": 0.35},
                "from": ["1001", "1042"],
            },
            "3115": {  # Nashor's Tooth
                "name": "Nashor's Tooth",
                "gold": {"total": 3000},
                "stats": {"FlatMagicDamageMod": 90, "PercentAttackSpeedMod": 0.50},
                "from": ["3108", "1043"],
            },
        }

    def test_calculate_item_stats(self):
        stats = calculate_item_stats(["3031", "3006"], self.mock_items)
        self.assertEqual(stats["ad"], 75.0)
        self.assertEqual(stats["as_percent"], 35.0)
        self.assertEqual(stats["gold"], 4600)

    def test_kaisa_q_evolution_level_estimate(self):
        # With 85 bonus AD from items, needs 15 AD from level growth
        # Growth per level is ~2.6, so ~level 8
        lvl = estimate_kaisa_q_level(85.0)
        self.assertIsNotNone(lvl)
        self.assertTrue(5 <= lvl <= 10)

    def test_kaisa_q_instant_evolution_at_100_ad(self):
        lvl = estimate_kaisa_q_level(105.0)
        self.assertEqual(lvl, 1)

    def test_track_evolution_progress(self):
        # Doran's Blade (10) + Infinity Edge (75) + Pickaxe (25) = 110 AD -> Q evolved!
        res = track_evolution_progress(
            ["3031", "3006", "1037"],
            self.mock_items,
            champion_slug="kaisa",
            start_ids=["1055"],
        )
        self.assertTrue(res["supported"])
        self.assertTrue(res["q"]["evolved"])

    def test_determine_damage_profile(self):
        # AD Crit profile
        profile_ad = determine_damage_profile(["3031"], self.mock_items)
        self.assertEqual(profile_ad, "ad_crit")

        # AP profile
        profile_ap = determine_damage_profile(["3115"], self.mock_items)
        self.assertEqual(profile_ap, "ap_burst")

    def test_get_early_components(self):
        # Infinity Edge builds from 1038, 1037, 1018
        comps = get_early_components(["3031"], self.mock_items)
        self.assertIn("1038", comps)
        self.assertIn("1037", comps)


if __name__ == "__main__":
    unittest.main()
