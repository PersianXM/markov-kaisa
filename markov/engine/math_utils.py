"""Empirical Bayes statistical formulas and path scoring."""

from __future__ import annotations

import math


def shrink(wins: float, games: float, p0: float, alpha: float) -> float:
    """Computes empirical Bayes shrinkage estimate of winrate.

    Formula: (wins + alpha * p0) / (games + alpha)
    """
    return (wins + alpha * p0) / (games + alpha)


def ci95(p: float, n: float) -> float:
    """Computes 95% confidence interval half-width for a proportion.

    Formula: 1.96 * sqrt(p * (1 - p) / n)
    """
    return 1.96 * math.sqrt(max(p * (1.0 - p), 1e-9) / max(n, 1.0))


def score(
    wins: float,
    games: float,
    p0: float,
    p_avg: float,
    alpha: float,
    n_min: float,
    lam: float = 0.55,
) -> dict | None:
    """Scores an item path computing shrunk WR, delta, CI, and utility U.

    Formula: U = delta - lam * CI
    """
    if games <= 0:
        return None
    wr = wins / games
    tilde = shrink(wins, games, p0, alpha)
    delta = tilde - p_avg
    risk = ci95(tilde, games + alpha)
    return {
        "wr": wr,
        "tilde": tilde,
        "delta": delta,
        "ci": risk,
        "U": None if games < n_min else delta - lam * risk,
        "n": games,
        "reject": games < n_min,
    }


def compact_score(s: dict | None) -> dict | None:
    """Extracts a compact subset of score fields for serialization."""
    if not s:
        return None
    return {
        "wr": s.get("wr"),
        "tilde": s.get("tilde"),
        "delta": s.get("delta"),
        "U": s.get("U"),
        "n": s.get("n"),
        "reject": s.get("reject", False),
    }


def lookup(agg: dict, key: str) -> tuple[float, float] | None:
    """Looks up a path key in an aggregated dict, returning (games, wins) or None."""
    if key not in agg:
        return None
    return agg[key]


def score_path(
    agg: dict,
    path: str,
    p0: float,
    p_avg: float,
    alpha: float,
    n_min: float,
    lam: float = 0.55,
) -> dict | None:
    """Looks up and scores a specific path in an aggregated dict."""
    found = lookup(agg, path)
    if not found:
        return None
    games, wins = found
    return score(wins, games, p0, p_avg, alpha, n_min, lam)


def hierarchical_tilde(
    silver: tuple[float, float] | None,
    prior: tuple[float, float] | None,
    p0: float,
    alpha: float,
) -> float | None:
    """Computes hierarchical shrinkage estimate combining rank data with a broader prior."""
    if silver is None and prior is None:
        return None
    if silver is None:
        games_p, wins_p = prior
        return wins_p / games_p if games_p else None
    games_s, wins_s = silver
    if prior is None or prior[0] <= 0:
        return shrink(wins_s, games_s, p0, alpha)
    p_prior = prior[1] / prior[0]
    local_alpha = 400.0 if games_s >= 800 else 800.0 if games_s >= 200 else 1200.0
    local_alpha = max(local_alpha, alpha)
    return (wins_s + local_alpha * p_prior) / (games_s + local_alpha)


def late_utility(tilde: float, games: float, p_avg: float, alpha: float, lam: float = 0.55) -> float:
    """Computes utility U for a late item given its hierarchical tilde estimate."""
    return (tilde - p_avg) - lam * ci95(tilde, games + alpha)
