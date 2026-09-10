"""End-to-end Markov decision pipeline orchestration."""

from __future__ import annotations

from datetime import date, datetime, timezone

from markov.data.ddragon import is_boots, item_name, load_champions, path_name
from markov.data.lolalytics import (
    choose_start_items,
    fetch_baseline,
    fetch_champion_page,
    fetch_counters,
    fetch_itemsets,
    parse_runes,
    parse_skill_order,
    resolve_live_patch,
)
from markov.engine.aggregation import (
    actually_built,
    apply_share_floor,
    champion_sample_n,
    scale_sample_floors,
)
from markov.engine.evolution import (
    get_early_components,
    track_evolution_progress,
)
from markov.engine.gem_hunter import gem_search_config, hunt_gem_paths
from markov.engine.grid import compute_hyper_grid, select_hyperparams
from markov.engine.math_utils import score
from markov.engine.stagewise import joint_finish, live_matchup_branches, rank_paths
from markov.engine.validation import active_blacklist, load_history


def build_decision(
    cfg: dict,
    items: dict[int, str],
    item_details: dict[str, dict] | None = None,
) -> tuple[dict, dict, float, float, float]:
    """Main decision pipeline: fetches data, scores paths, evaluates evolutions, and selects build."""
    item_details = item_details or {}
    html = fetch_champion_page(cfg)
    cfg["patch"] = resolve_live_patch(cfg)
    print(f"Fetching {cfg['tier'].title()} {cfg['region'].upper()} item sets...")
    silver = fetch_itemsets(cfg, cfg["tier"], cfg["region"])
    print(f"Fetching {cfg['prior_tier'].title()} {cfg['prior_region'].upper()} prior...")
    try:
        prior = fetch_itemsets(cfg, cfg["prior_tier"], cfg["prior_region"])
    except Exception as exc:
        print(f"Primary prior failed ({exc}); using Global Emerald.")
        prior = fetch_itemsets(cfg, cfg["prior_tier"], cfg["fallback_prior_region"])

    print("Fetching champion baseline...")
    p0, p_avg = fetch_baseline(cfg)
    today = date.today().isoformat()
    history = load_history()
    total_n = champion_sample_n(silver)
    cfg, scaled_floors = scale_sample_floors(cfg, total_n)
    if scaled_floors:
        print(f"Early patch sample n={total_n:.0f}. Scaled n floors:")
        for key, (old, new) in scaled_floors.items():
            print(f"  {key}: {old:g} -> {new:g}")
    grid = compute_hyper_grid(silver, p0, p_avg, cfg)
    alpha, lam, hyper = select_hyperparams(history, today, silver, p0, p_avg, cfg, grid)
    print(
        f"Baseline p0={p0:.4f}  p_avg={p_avg:.4f}  "
        f"alpha={alpha:g}  lambda={lam:g}  ({hyper.get('status')})"
    )
    item1_rows = apply_share_floor(
        rank_paths(actually_built(silver, 1), p0, p_avg, alpha, cfg["n_min_item1"], lam),
        total_n,
        float(cfg.get("min_pick_share_item1", 0.03)),
    )
    if not item1_rows:
        raw = actually_built(silver, 1)
        if not raw:
            raise RuntimeError("No Item 1 data from Lolalytics.")
        path, (games, wins) = max(raw.items(), key=lambda row: row[1][0])
        scored = score(wins, games, p0, p_avg, alpha, 0, lam) or {
            "wr": wins / games if games else 0.0,
            "tilde": 0.5,
            "delta": 0.0,
            "ci": 0.0,
            "U": 0.0,
            "n": games,
            "reject": False,
        }
        scored["U"] = scored.get("U") or 0.0
        scored["reject"] = False
        item1_rows = [(path, scored)]
        print(f"Item 1 below floor; using most common n={games:.0f}")
    item1 = item1_rows[0][0]

    item2_all = apply_share_floor(
        rank_paths(actually_built(silver, 2), p0, p_avg, alpha, cfg["n_min_item2"], lam),
        total_n,
        float(cfg.get("min_pick_share_pair", 0.015)),
    )
    item2_rows = [row for row in item2_all if row[0].startswith(item1 + "_")]
    if not item2_rows:
        raise RuntimeError("No reliable Item 2 candidates.")
    pair = item2_rows[0][0]

    core_all = apply_share_floor(
        rank_paths(actually_built(silver, 3), p0, p_avg, alpha, cfg["n_min_core"], lam),
        total_n,
        float(cfg.get("min_pick_share_core", 0.01)),
    )
    banned = active_blacklist(today)
    if banned:
        print("Blacklisted cores: " + ", ".join(path_name(items, c) for c in sorted(banned)))
    core_pool = [row for row in core_all if row[0] not in banned] or core_all
    greedy = [row for row in core_pool if row[0].startswith(pair + "_")]
    if not greedy and not core_pool:
        raise RuntimeError("No reliable core candidates.")
    greedy_core = (greedy or core_pool)[0][0]

    k = int(cfg.get("core_search_k", 3))
    candidates: list[tuple[str, dict]] = []
    seen: set[str] = set()
    for row in (greedy + core_pool):
        if row[0] in seen:
            continue
        candidates.append(row)
        seen.add(row[0])
        if len(candidates) >= k:
            break
    if not candidates:
        raise RuntimeError("No reliable core candidates.")

    print(f"Joint search over top {len(candidates)} cores x boots x Item4/5/6...")
    best_bundle = None
    for path, scored in candidates:
        pair_c = "_".join(path.split("_")[:2])
        finished = joint_finish(
            items, silver, prior, path, pair_c, p0, p_avg, alpha, lam, cfg
        )
        u_total = 0.55 * (scored["U"] or 0.0) + 0.45 * finished["u_joint"]
        print(
            f"  {path_name(items, path)}  U_core={scored['U']*100:+.2f}  "
            f"U_joint={finished['u_joint']*100:+.2f}  U_total={u_total*100:+.2f}"
        )
        bundle = {
            "core": path,
            "score": scored,
            "pair": pair_c,
            "finished": finished,
            "u_total": u_total,
        }
        if best_bundle is None or u_total > best_bundle["u_total"]:
            best_bundle = bundle

    assert best_bundle is not None
    selected_core = best_bundle["core"]
    core_score = best_bundle["score"]
    pair = best_bundle["pair"]
    finished = best_bundle["finished"]
    item1 = selected_core.split("_")[0]
    item1_match = next((row for row in item1_rows if row[0] == item1), item1_rows[0])
    item2_match = next((row for row in item2_all if row[0] == pair), item2_rows[0])

    boots = finished["boots"]["id"]
    item4 = finished["item4"]["id"]
    item5 = finished["item5"]["id"]
    item6 = finished["item6"]["id"]
    print(
        f"Selected core {path_name(items, selected_core)}  "
        f"boots={item_name(items, boots)}  "
        f"4={item_name(items, item4)}  "
        f"5={item_name(items, item5)}  "
        f"6={item_name(items, item6)}"
    )

    start, start_score = choose_start_items(
        html, p0, p_avg, alpha, lam, cfg.get("n_min_start", 2000)
    )
    if start_score:
        print(
            f"Start n>={cfg.get('n_min_start', 2000)}: "
            f"{' + '.join(item_name(items, i) for i in start)} "
            f"U={start_score['U']*100:+.2f} n={start_score['n']:.0f}"
        )
    else:
        print("Start: no set met n floor; fallback Doran's Blade + Potion")

    skills = parse_skill_order(html, p0, p_avg, alpha, lam, cfg.get("n_min_start", 2000))
    runes = parse_runes(html)

    core_ids = selected_core.split("_")
    buy_order = [core_ids[0], boots, core_ids[1], core_ids[2], item4, item5, item6]
    chosen = set(buy_order)
    situational = []
    for row in finished.get("leftovers") or []:
        iid = row.get("id")
        if iid and iid not in chosen and iid not in situational and not row.get("fallback"):
            situational.append(iid)
        if len(situational) >= 6:
            break

    print("Fetching live counters for late-item branches...")
    champions = load_champions()
    try:
        counter_payload = fetch_counters(cfg)
    except Exception as exc:
        print(f"Counter fetch failed ({exc}); using archetype branches only.")
        counter_payload = {}

    branches, weak_rows = live_matchup_branches(
        cfg,
        champions,
        chosen,
        payload=counter_payload,
        item_details=item_details,
        core_ids=core_ids,
    )
    if weak_rows:
        print(
            "Hard lanes (live): "
            + ", ".join(
                f"{row['name']} vsWR={row['vs_wr']*100:.1f}% n={row['n']:.0f}"
                for row in weak_rows
            )
        )
    for branch in branches:
        if branch["ids"]:
            print(
                f"  {branch['title']}: "
                + ", ".join(item_name(items, iid) for iid in branch["ids"])
            )

    # Calculate Early Components for Item 1 and Item 2
    early_comp_ids = get_early_components([core_ids[0], core_ids[1]], item_details, max_components=6)
    early_comp_details = [
        {
            "id": cid,
            "name": item_name(items, cid),
            "gold": item_details.get(str(cid), {}).get("gold", {}),
        }
        for cid in early_comp_ids
    ]

    # Evaluate Kai'Sa Evolutions if applicable
    evolution_data = {}
    if cfg.get("champion") == "kaisa" and item_details:
        evolution_data = track_evolution_progress(
            buy_order,
            item_details,
            champion_slug=cfg["champion"],
            start_ids=start,
        )
        # If Q evolves late, suggest top AD components to rush Q evolve
        if not evolution_data.get("q", {}).get("evolved") or (evolution_data.get("q", {}).get("level_estimate", 18) > 9):
            evolution_data["q_rush_items"] = [cid for cid in early_comp_ids if float((item_details.get(str(cid), {}).get("stats", {})).get("FlatPhysicalDamageMod", 0)) >= 20][:3]

    buy_order_with_gold = []
    total_build_gold = 0
    for iid in buy_order:
        detail = item_details.get(str(iid)) or {}
        g_val = detail.get("gold", {}).get("total", 0)
        total_build_gold += int(g_val or 0)
        buy_order_with_gold.append({
            "id": iid,
            "name": item_name(items, iid),
            "gold": g_val,
        })

    decision = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "context": {
            "tier": cfg["tier"],
            "region": cfg["region"],
            "patch": cfg["patch"],
            "p0": p0,
            "p_avg": p_avg,
            "alpha": alpha,
            "lambda": lam,
            "hyper": hyper,
            "sample_n": total_n,
            "blacklisted": sorted(banned),
        },
        "item1": {"id": item1, "name": item_name(items, item1), **item1_match[1]},
        "item2": {
            "id": pair.split("_")[1],
            "path": pair,
            "name": path_name(items, pair),
            **item2_match[1],
        },
        "core": {
            "path": selected_core,
            "name": path_name(items, selected_core),
            "greedy": path_name(items, greedy_core),
            **{k: core_score[k] for k in ("wr", "tilde", "delta", "U", "n")},
        },
        "boots": {"id": boots, "name": item_name(items, boots)},
        "item4": {"id": item4, "name": item_name(items, item4)},
        "item5": {"id": item5, "name": item_name(items, item5)},
        "item6": {"id": item6, "name": item_name(items, item6)},
        "start": [{"id": i, "name": item_name(items, i)} for i in start],
        "buy_order": buy_order_with_gold,
        "total_gold": total_build_gold,
        "early_components": early_comp_ids,
        "early_components_details": early_comp_details,
        "situational": [{"id": i, "name": item_name(items, i)} for i in situational],
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
        "policy": {
            branch["key"]: [
                {"id": iid, "name": item_name(items, iid)} for iid in branch["ids"]
            ]
            for branch in branches
            if branch.get("ids")
        },
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
            "u_total": best_bundle["u_total"],
        },
        "evolution": evolution_data,
        "grid": grid,
    }

    gem_cfg = gem_search_config(cfg)
    decision["gems"] = hunt_gem_paths(
        items,
        gem_cfg,
        silver,
        prior,
        selected_core,
        p0,
        p_avg,
        alpha,
        lam,
        start,
        skills,
        runes,
        champions,
        counter_payload,
        total_n,
        weak_rows,
        item_details=item_details,
    )
    return decision, silver, p0, p_avg, alpha
