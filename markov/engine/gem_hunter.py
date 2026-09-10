"""Gem Hunter pipeline for discovering high-utility underpicked item sets."""

from __future__ import annotations

import math
import uuid
from typing import Any

from markov.data.ddragon import item_name, path_name
from markov.engine.aggregation import actually_built
from markov.engine.evolution import track_evolution_progress
from markov.engine.math_utils import hierarchical_tilde, late_utility, lookup
from markov.engine.stagewise import (
    joint_finish,
    live_matchup_branches,
)


def gem_uid(slot: int, champ_slug: str = "kaisa") -> str:
    """Generates a deterministic UUID for a gem hunter item set slot."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"markov-{champ_slug}-gem-{slot}"))


def core_identity(path: str) -> frozenset[str]:
    """Returns a frozenset of item IDs from a path, ignoring purchase order."""
    return frozenset(path.split("_"))


def gem_search_config(cfg: dict) -> dict:
    """Gem floors are absolute. Do not rescale the already-thinned U-path floors."""
    out = dict(cfg)
    out["n_min_core"] = float(cfg.get("gem_n_min_core", 120))
    out["n_min_item4"] = float(cfg.get("gem_n_min_item4", 80))
    out["n_min_item5"] = float(cfg.get("gem_n_min_item5", 50))
    out["n_min_item6"] = float(cfg.get("gem_n_min_item6", 40))
    out["n_min_boots"] = float(cfg.get("gem_n_min_boots", 80))
    out["n_min_item2"] = float(cfg.get("gem_n_min_item2", 80))
    return out


def gem_set_title(wr: float, used: set[str] | None = None) -> str:
    """Generates a unique title for a Gem Hunter item set based on winrate."""
    used = used if used is not None else set()
    pct = int(round((wr or 0.0) * 100.0))
    title = f"Gem Hunter {pct}%"
    if title in used:
        tenths = round((wr or 0.0) * 1000.0) / 10.0
        title = f"Gem Hunter {tenths:.1f}%"
    return title


def buy_plan(core: str, finished: dict) -> tuple[list[str], list[str]]:
    """Builds the 7-slot buy order and situational items from a core and finished dict."""
    core_ids = core.split("_")
    buy_order = [
        core_ids[0],
        finished["boots"]["id"],
        core_ids[1],
        core_ids[2],
        finished["item4"]["id"],
        finished["item5"]["id"],
        finished["item6"]["id"],
    ]
    chosen = set(buy_order)
    situational: list[str] = []
    for row in finished.get("leftovers") or []:
        iid = row.get("id")
        if iid and iid not in chosen and iid not in situational and not row.get("fallback"):
            situational.append(iid)
        if len(situational) >= 6:
            break
    return buy_order, situational


def compact_path_decision(
    items: dict[int, str],
    core: str,
    scored: dict,
    finished: dict,
    start: list[str],
    skills: dict | None,
    runes: dict | None,
    branches: list[dict],
    weak_rows: list[dict],
    title: str,
    slot: int,
    share: float,
    gem_score: float,
    lam: float,
    item_details: dict[str, dict] | None = None,
    champ_slug: str = "kaisa",
) -> dict:
    """Builds a compact decision dict for a gem path."""
    buy_ids, situ_ids = buy_plan(core, finished)
    ev_data = {}
    if item_details and champ_slug == "kaisa":
        ev_data = track_evolution_progress(buy_ids, item_details, champion_slug=champ_slug, start_ids=start)

    return {
        "set_title": title,
        "set_uid_key": f"markov-{champ_slug}-gem-{slot}",
        "slot": slot,
        "gem": {
            "G": gem_score,
            "share": share,
            "lambda": lam,
        },
        "item1": {"id": buy_ids[0], "name": item_name(items, buy_ids[0])},
        "core": {
            "path": core,
            "name": path_name(items, core),
            "wr": scored.get("wr"),
            "tilde": scored.get("tilde"),
            "delta": scored.get("delta"),
            "U": scored.get("U"),
            "n": scored.get("n"),
        },
        "boots": {
            "id": finished["boots"]["id"],
            "name": item_name(items, finished["boots"]["id"]),
        },
        "item4": {
            "id": finished["item4"]["id"],
            "name": item_name(items, finished["item4"]["id"]),
        },
        "item5": {
            "id": finished["item5"]["id"],
            "name": item_name(items, finished["item5"]["id"]),
        },
        "item6": {
            "id": finished["item6"]["id"],
            "name": item_name(items, finished["item6"]["id"]),
        },
        "start": [{"id": i, "name": item_name(items, i)} for i in start],
        "buy_order": [{"id": i, "name": item_name(items, i)} for i in buy_ids],
        "situational": [{"id": i, "name": item_name(items, i)} for i in situ_ids],
        "policy_branches": [
            {
                "key": branch["key"],
                "title": branch["title"],
                "source": branch["source"],
                "champions": branch.get("champions") or [],
                "items": [
                    {"id": iid, "name": item_name(items, iid)} for iid in branch["ids"]
                ],
            }
            for branch in branches
            if branch.get("ids")
        ],
        "skills": skills,
        "runes": runes,
        "matchups": [
            {
                "champion": row["name"],
                "n": row["n"],
                "wr": row["vs_wr"],
                "lane": row.get("lane"),
            }
            for row in weak_rows
        ],
        "joint": {
            "u_joint": finished["u_joint"],
            "u45": finished["u45"],
        },
        "evolution": ev_data,
    }


def fetch_gem_prior(cfg: dict, fallback: dict) -> tuple[dict, str, str]:
    """Thicker sample for discovering underpicked cores the chosen rank barely plays."""
    from markov.data.lolalytics import fetch_itemsets

    tier = str(cfg.get("gem_prior_tier") or "platinum_plus")
    region = str(cfg.get("gem_prior_region") or "all")
    tries = ((tier, region), ("platinum_plus", "all"), ("all", "all"))
    seen: set[tuple[str, str]] = set()
    for t, r in tries:
        key = (t.lower(), r.lower())
        if key in seen:
            continue
        seen.add(key)
        try:
            return fetch_itemsets(cfg, t, r), t, r
        except Exception as exc:
            print(f"Gem prior {t}/{r} failed ({exc})")
    return fallback, str(cfg.get("prior_tier") or "emerald"), str(
        cfg.get("fallback_prior_region") or "all"
    )


def score_gem_path(
    silver3: dict,
    prior3: dict,
    path: str,
    p0: float,
    p_avg: float,
    alpha: float,
    lam: float,
    n_min: float,
) -> dict | None:
    """Scores a core path for Gem Hunter using hierarchical shrinkage from a thicker prior."""
    silver_row = lookup(silver3, path)
    prior_row = lookup(prior3, path)
    n_s = silver_row[0] if silver_row else 0.0
    n_p = prior_row[0] if prior_row else 0.0
    if n_p < n_min and n_s < n_min:
        return None
    tilde = hierarchical_tilde(silver_row, prior_row, p0, alpha)
    if tilde is None:
        return None
    if n_p >= n_min and prior_row:
        games, wins = prior_row
    else:
        games, wins = silver_row if silver_row else (n_p, 0.0)
    wr = wins / games if games else 0.0
    utility = late_utility(tilde, games, p_avg, alpha, lam)
    return {
        "wr": wr,
        "tilde": tilde,
        "delta": tilde - p_avg,
        "U": utility,
        "n": games,
        "n_rank": n_s,
        "n_prior": n_p,
        "reject": False,
    }


def rank_gem_cores(
    silver: dict,
    gem_prior: dict,
    p0: float,
    p_avg: float,
    alpha: float,
    lam: float,
    cfg: dict,
    total_prior: float,
    exclude: set[frozenset[str]],
    default_item1: str,
) -> list[tuple[str, dict, float, float]]:
    """Ranks all candidate gem cores by G = U + rarity bonus, excluding the default core."""
    n_min = float(cfg["n_min_core"])
    min_share = float(cfg.get("gem_min_pick_share", 0.0004))
    max_share = float(cfg.get("gem_max_pick_share", 0.12))
    rarity = float(cfg.get("gem_rarity_bonus", 0.005))
    silver3 = actually_built(silver, 3)
    prior3 = actually_built(gem_prior, 3)
    scored: list[tuple[str, dict, float, float]] = []
    for path in set(silver3) | set(prior3):
        ident = core_identity(path)
        if ident in exclude:
            continue
        s = score_gem_path(silver3, prior3, path, p0, p_avg, alpha, lam, n_min)
        if not s or s["U"] is None:
            continue
        share = (s["n"] / total_prior) if total_prior else 0.0
        if share < min_share:
            continue
        rarity_term = rarity * math.log(max(max_share, min_share) / max(share, min_share))
        if share > max_share:
            rarity_term = min(rarity_term, 0.0)
        gem_score = (s["U"] or 0.0) + rarity_term
        scored.append((path, s, share, gem_score))
    scored.sort(key=lambda row: row[3], reverse=True)

    picked: list[tuple[str, dict, float, float]] = []
    seen: set[frozenset[str]] = set()
    want = int(cfg.get("gem_count", 2))

    def take(
        require_positive: bool,
        add: int,
        item1_in: set[str] | None = None,
        item1_not: set[str] | None = None,
    ) -> None:
        added = 0
        for path, s, share, gem_score in scored:
            if share > max_share:
                continue
            if require_positive and (s.get("U") or 0.0) < 0:
                continue
            item1 = path.split("_")[0]
            if item1_in is not None and item1 not in item1_in:
                continue
            if item1_not is not None and item1 in item1_not:
                continue
            ident = core_identity(path)
            if ident in seen or ident in exclude:
                continue
            seen.add(ident)
            picked.append((path, s, share, gem_score))
            added += 1
            if len(picked) >= want or added >= add:
                return

    take(True, 1, item1_in={default_item1})
    if len(picked) < want:
        take(True, 1, item1_not={default_item1})
    if len(picked) < want:
        take(True, want)
    if len(picked) < want:
        take(False, want)
    return picked


def hunt_gem_paths(
    items: dict[int, str],
    cfg: dict,
    silver: dict,
    prior: dict,
    default_core: str,
    p0: float,
    p_avg: float,
    alpha: float,
    lam: float,
    start: list[str],
    skills: dict | None,
    runes: dict | None,
    champions: dict[int, str],
    counter_payload: dict,
    total_n: float,
    weak_rows: list[dict],
    item_details: dict[str, dict] | None = None,
) -> list[dict]:
    """Main Gem Hunter pipeline: finds and builds two underpicked alternative item sets."""
    lam_gem = lam * float(cfg.get("gem_lambda_scale", 0.65))
    alpha_gem = max(80.0, alpha * float(cfg.get("gem_alpha_scale", 0.25)))
    print("Fetching gem prior (thicker sample for underpicked cores)...")
    gem_sets, gem_tier, gem_region = fetch_gem_prior(cfg, prior)
    prior3 = actually_built(gem_sets, 3)
    total_prior = sum(games for games, _wins in prior3.values())
    print(
        f"Gem hunter: prior={gem_tier}/{gem_region}  n={total_prior:.0f}  "
        f"n_min_core={cfg['n_min_core']:g}  alpha={alpha_gem:g}  "
        f"lambda={lam_gem:.3f}"
    )
    ranked = rank_gem_cores(
        silver,
        gem_sets,
        p0,
        p_avg,
        alpha_gem,
        lam_gem,
        cfg,
        total_prior,
        {core_identity(default_core)},
        default_core.split("_")[0],
    )
    gems: list[dict] = []
    used_titles: set[str] = set()
    n_min = float(cfg["n_min_core"])
    silver3 = actually_built(silver, 3)
    champ_slug = cfg.get("champion", "kaisa")

    for slot, (path, scored, share, gem_score) in enumerate(ranked, 1):
        pair = "_".join(path.split("_")[:2])
        print(
            f"  gem {slot}: {path_name(items, path)}  "
            f"U={scored['U']*100:+.2f}  wr={scored['wr']*100:.1f}%  "
            f"share={share*100:.2f}%  G={gem_score*100:+.2f}  "
            f"n_prior={scored.get('n_prior', 0):.0f}  "
            f"n_rank={scored.get('n_rank', 0):.0f}"
        )
        silver_n = lookup(silver3, path)
        primary, secondary = (
            (silver, gem_sets)
            if silver_n and silver_n[0] >= n_min
            else (gem_sets, silver)
        )
        finished = joint_finish(
            items, primary, secondary, path, pair, p0, p_avg, alpha_gem, lam_gem, cfg
        )
        buy_ids, _situ = buy_plan(path, finished)
        branches, _weak = live_matchup_branches(
            cfg,
            champions,
            set(buy_ids),
            payload=counter_payload,
            item_details=item_details,
            core_ids=path.split("_"),
        )
        title = gem_set_title(float(scored.get("wr") or 0.0), used_titles)
        used_titles.add(title)
        gems.append(
            compact_path_decision(
                items,
                path,
                scored,
                finished,
                start,
                skills,
                runes,
                branches,
                weak_rows,
                title,
                slot,
                share,
                gem_score,
                lam_gem,
                item_details=item_details,
                champ_slug=champ_slug,
            )
        )
        print(
            f"    {title}: "
            + " -> ".join(item_name(items, iid) for iid in buy_ids)
        )
    if not gems:
        print("  no underpicked cores cleared the gem floors")
    return gems
