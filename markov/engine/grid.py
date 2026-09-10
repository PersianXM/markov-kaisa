"""Hyperparameter grid evaluation and holdout consensus."""

from __future__ import annotations

from collections import Counter

from markov.engine.aggregation import actually_built
from markov.engine.math_utils import score_path
from markov.engine.stagewise import rank_paths

HYPER_GRID = (
    (400.0, 0.30),
    (400.0, 0.55),
    (800.0, 0.55),
    (800.0, 0.80),
    (1600.0, 0.55),
    (1600.0, 0.80),
)


def compute_hyper_grid(silver: dict, p0: float, p_avg: float, cfg: dict) -> dict:
    """Evaluates the top core across a grid of (alpha, lambda) hyperparameters."""
    cores = actually_built(silver, 3)
    out = {}
    for alpha, lam in HYPER_GRID:
        rows = rank_paths(cores, p0, p_avg, alpha, cfg["n_min_core"], lam)
        if not rows:
            continue
        path, s = rows[0]
        out[f"{alpha:g}_{lam:g}"] = {
            "alpha": alpha,
            "lambda": lam,
            "core": path,
            "U": s["U"],
            "n": s["n"],
            "tilde": s["tilde"],
        }
    return out


def consensus_hyperparams(
    grid: dict,
    default_a: float,
    default_l: float,
) -> tuple[float, float, dict]:
    """Selects hyperparameters by modal-core consensus across the grid."""
    if not grid:
        return default_a, default_l, {
            "status": "default",
            "alpha": default_a,
            "lambda": default_l,
            "reason": "Empty α/λ grid.",
        }
    votes: Counter[str] = Counter()
    for spec in grid.values():
        core = spec.get("core")
        if core:
            votes[core] += 1
    if not votes:
        return default_a, default_l, {
            "status": "default",
            "alpha": default_a,
            "lambda": default_l,
        }
    modal = votes.most_common(1)[0][0]
    best = None
    best_dist = None
    for spec in grid.values():
        if spec.get("core") != modal:
            continue
        dist = abs(float(spec["alpha"]) - default_a) + abs(float(spec["lambda"]) - default_l)
        if best is None or dist < best_dist:
            best = spec
            best_dist = dist
    assert best is not None
    return float(best["alpha"]), float(best["lambda"]), {
        "status": "grid_consensus",
        "alpha": float(best["alpha"]),
        "lambda": float(best["lambda"]),
        "core": modal,
        "votes": votes[modal],
        "cells": len(grid),
        "reason": "Same-day modal core across the α/λ grid.",
    }


def select_hyperparams(
    history: list[dict],
    today: str,
    silver: dict,
    p0: float,
    p_avg: float,
    cfg: dict,
    grid: dict,
) -> tuple[float, float, dict]:
    """Selects alpha and lambda using holdout validation or grid consensus."""
    from markov.engine.validation import previous_calendar_entry

    default_a = float(cfg.get("alpha_rank", 800))
    default_l = float(cfg.get("lambda_risk", 0.55))
    prev = previous_calendar_entry(history, today, cfg.get("tier"), champion=cfg.get("champion"))
    if prev and prev.get("grid"):
        best = None
        for spec in prev["grid"].values():
            core = spec.get("core")
            alpha = float(spec["alpha"])
            lam = float(spec["lambda"])
            today_s = score_path(
                actually_built(silver, 3), core, p0, p_avg, alpha, cfg["n_min_core"], lam
            )
            if not today_s or today_s["U"] is None:
                continue
            row = {
                "status": "holdout",
                "alpha": alpha,
                "lambda": lam,
                "core": core,
                "U": today_s["U"],
                "n": today_s["n"],
            }
            if best is None or row["U"] > best["U"]:
                best = row
        if best is not None:
            return best["alpha"], best["lambda"], best
    return consensus_hyperparams(grid, default_a, default_l)
