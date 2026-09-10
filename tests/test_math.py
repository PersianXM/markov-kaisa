"""Unit tests for empirical Bayes mathematical formulas."""

import unittest
from markov.engine.math_utils import shrink, ci95, score, score_path


class TestMathUtils(unittest.TestCase):
    def test_shrink_pulls_towards_prior(self):
        # 10 wins out of 10 games with prior 0.5 and alpha 10
        # Formula: (10 + 10 * 0.5) / (10 + 10) = 15 / 20 = 0.75
        shrunk = shrink(10.0, 10.0, 0.50, 10.0)
        self.assertAlmostEqual(shrunk, 0.75, places=4)

    def test_ci95_decreases_with_sample_size(self):
        ci_small = ci95(0.5, 100)
        ci_large = ci95(0.5, 10000)
        self.assertGreater(ci_small, ci_large)
        # CI for 50% at n=100: 1.96 * sqrt(0.25 / 100) = 1.96 * 0.05 = 0.098
        self.assertAlmostEqual(ci_small, 0.098, places=3)

    def test_score_rejects_under_sample_floor(self):
        s = score(wins=5.0, games=10.0, p0=0.5, p_avg=0.5, alpha=100.0, n_min=50.0)
        self.assertIsNotNone(s)
        self.assertTrue(s["reject"])
        self.assertIsNone(s["U"])

    def test_score_calculates_valid_utility(self):
        s = score(wins=600.0, games=1000.0, p0=0.5, p_avg=0.5, alpha=200.0, n_min=100.0, lam=0.55)
        self.assertIsNotNone(s)
        self.assertFalse(s["reject"])
        self.assertIsNotNone(s["U"])
        self.assertGreater(s["U"], 0.0)


if __name__ == "__main__":
    unittest.main()
