"""Actually-Built path aggregation and sample floor scaling."""

from __future__ import annotations

import math


def max_set_depth(itemsets: dict, boot: bool = False) -> int:
    """Returns the maximum item set depth available in the API response."""
    prefix = "itemBootSet" if boot else "itemSet"
    depths = []
    for key in itemsets:
        if key.startswith(prefix):
            suffix = key[len(prefix) :]
            if suffix.isdigit():
                depths.append(int(suffix))
    if depths:
        return max(depths)
    return 6 if boot else 5


def actually_built(itemsets: dict, t: int, boot: bool = False) -> dict[str, tuple[float, float]]:
    """Aggregates Actually-Built paths at depth t from deeper item sets."""
    prefix = "itemBootSet" if boot else "itemSet"
    max_i = max_set_depth(itemsets, boot=boot)
    agg: dict[str, list[float]] = {}
    for i in range(t, max_i + 1):
        for row in itemsets.get(f"{prefix}{i}", []):
            path, games, wins = str(row[0]), float(row[1]), float(row[2])
            parts = path.split("_")
            if len(parts) < t:
                continue
            key = "_".join(parts[:t])
            bucket = agg.setdefault(key, [0.0, 0.0])
            bucket[0] += games
            bucket[1] += wins
    return {k: (v[0], v[1]) for k, v in agg.items()}


def champion_sample_n(itemsets: dict) -> float:
    """Returns total sample size for the champion at item-1 depth."""
    return sum(games for games, _wins in actually_built(itemsets, 1).values())


def apply_share_floor(
    rows: list[tuple[str, dict]],
    total_n: float,
    share: float,
) -> list[tuple[str, dict]]:
    """Filters ranked paths by minimum pick share."""
    if total_n <= 0 or not rows:
        return rows
    floor = share * total_n
    kept = [row for row in rows if row[1]["n"] >= floor]
    return kept if kept else rows


def scale_sample_floors(cfg: dict, total_n: float) -> tuple[dict, dict]:
    """Shrinks n_min sample floors when the live patch sample is still thin."""
    specs = (
        ("n_min_start", 0.04, 25.0),
        ("n_min_item1", 0.03, 20.0),
        ("n_min_item2", 0.015, 15.0),
        ("n_min_core", 0.01, 10.0),
        ("n_min_item4", 0.008, 8.0),
        ("n_min_item5", 0.005, 6.0),
        ("n_min_item6", 0.004, 5.0),
        ("n_min_boots", 0.01, 10.0),
    )
    out = dict(cfg)
    if "n_min_boots" not in out:
        out["n_min_boots"] = 800.0
    scaled: dict[str, tuple[float, float]] = {}
    for key, share, abs_min in specs:
        configured = float(out.get(key, abs_min))
        if total_n <= 0:
            effective = abs_min
        else:
            effective = max(abs_min, min(configured, math.ceil(share * total_n)))
        out[key] = effective
        if effective < configured:
            scaled[key] = (configured, effective)
    return out, scaled
