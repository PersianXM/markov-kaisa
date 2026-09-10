"""Unit tests for configuration loading and League directory resolution."""

import unittest
from markov.config import normalize_champion, apply_champion, detect_league_root


class TestConfig(unittest.TestCase):
    def test_normalize_champion(self):
        self.assertEqual(normalize_champion("kaisa"), "kaisa")
        self.assertEqual(normalize_champion("Kai'Sa"), "kaisa")
        self.assertEqual(normalize_champion("Tristana"), "tristana")
        self.assertEqual(normalize_champion("trist"), "tristana")
        self.assertEqual(normalize_champion(""), "kaisa")
        self.assertEqual(normalize_champion(None), "kaisa")

    def test_apply_champion(self):
        cfg = {"league_root": "G:\\Riot Games\\League of Legends"}
        updated = apply_champion(cfg, "kaisa")
        self.assertEqual(updated["champion"], "kaisa")
        self.assertEqual(updated["champion_id"], 145)
        self.assertIn("Kaisa", updated["itemset_dir"])

    def test_detect_league_root_returns_path(self):
        root = detect_league_root("G:\\Riot Games\\League of Legends")
        self.assertTrue(str(root).endswith("League of Legends"))


if __name__ == "__main__":
    unittest.main()
