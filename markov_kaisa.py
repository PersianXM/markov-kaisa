#!/usr/bin/env python3
"""Markov League Item Set Generator - Main Entry Point.

This script delegates core functionality to the modular `markov` package
while maintaining 100% backward compatibility with CLI arguments and launcher scripts.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from markov.cli import (
    LOLALYTICS_TIERS,
    pick_champion_menu,
    pick_tier_menu,
    print_summary,
    prior_for_tier,
)
from markov.client import (
    drop_itemsets,
    install_itemset,
    league_client_running,
    make_itemset,
    prune_stale_recommended,
    upsert_client_index,
    write_json,
)
from markov.config import (
    BLACKLIST_PATH,
    CHAMPION_ALIASES,
    CONFIG_PATH,
    DDRAGON_TIMEOUT,
    HISTORY_DIR,
    HISTORY_PATH,
    LOL_TIMEOUT,
    OUTPUT_DIR,
    ROOT,
    SUPPORTED_CHAMPIONS,
    UA,
    apply_champion,
    detect_league_root,
    load_config,
    normalize_champion,
)
from markov.data import (
    choose_start_items,
    ddragon_patch,
    fetch_baseline,
    fetch_champion_page,
    fetch_counters,
    fetch_itemsets,
    http_bytes,
    http_json,
    http_text,
    is_boots,
    item_name,
    load_champions,
    load_item_details,
    load_items,
    parse_runes,
    parse_skill_order,
    parse_start_sets,
    path_name,
    read_cache,
    resolve_live_patch,
    write_cache,
)
from markov.engine import (
    CHAMP_TAGS,
    HYPER_GRID,
    ITEMS_BY_TAG,
    active_blacklist,
    actually_built,
    append_history,
    apply_share_floor,
    build_decision,
    buy_plan,
    calculate_item_stats,
    champion_sample_n,
    champion_tags,
    choose_boots,
    choose_late_items,
    ci95,
    compact_path_decision,
    compact_score,
    compare_metric,
    compute_hyper_grid,
    consensus_hyperparams,
    core_identity,
    determine_damage_profile,
    fetch_gem_prior,
    gem_search_config,
    gem_set_title,
    gem_uid,
    get_adaptive_counter_items,
    get_early_components,
    hierarchical_tilde,
    hunt_gem_paths,
    items_for_tags,
    joint_finish,
    late_utility,
    list_boot_candidates,
    list_late_items,
    list_sixth_candidates,
    live_matchup_branches,
    load_blacklist,
    load_history,
    lookup,
    max_set_depth,
    most_common_extension,
    most_common_sixth,
    pick_late_item,
    pick_sixth_legendary,
    previous_calendar_entry,
    rank_gem_cores,
    rank_paths,
    rescore_selection,
    save_blacklist,
    scale_sample_floors,
    score,
    score_gem_path,
    score_path,
    select_hyperparams,
    short_champ_name,
    shrink,
    track_evolution_progress,
    update_blacklist,
    validate_against_previous,
    verdict_from_delta,
)


def parse_args() -> argparse.Namespace:
    """Parses command-line arguments."""
    parser = argparse.ArgumentParser(description="Generate the Markov champion item set.")
    parser.add_argument(
        "--champion",
        "--champ",
        default=None,
        help="Champion to build for (e.g. kaisa, tristana). Default is kaisa.",
    )
    parser.add_argument(
        "--pick-champion",
        "--pick-champ",
        action="store_true",
        help="Interactive up/down menu; writes the chosen champion for RUN.bat.",
    )
    parser.add_argument(
        "--tier",
        choices=LOLALYTICS_TIERS,
        default=None,
        help="Lolalytics rank filter. Default comes from config.json.",
    )
    parser.add_argument(
        "--pick-tier",
        action="store_true",
        help="Interactive up/down menu; writes the chosen tier for RUN.bat.",
    )
    return parser.parse_args()


def main() -> int:
    """Main execution flow for Markov item set generation."""
    cfg = load_config()
    args = parse_args()

    if args.pick_champion:
        chosen = pick_champion_menu(
            str(cfg.get("champion") or "kaisa"),
            out_path=OUTPUT_DIR / "selected_champion.txt",
        )
        return 0 if chosen else 1

    if args.pick_tier:
        chosen = pick_tier_menu(
            str(cfg.get("tier") or "silver"),
            out_path=OUTPUT_DIR / "selected_rank.txt",
        )
        return 0 if chosen else 1

    if args.champion:
        cfg = apply_champion(cfg, args.champion)
        print(f"Champion override from launcher: {cfg['champion_name']} ({cfg['champion']})")
    else:
        cfg = apply_champion(cfg)

    if args.tier:
        cfg["tier"] = args.tier
        print(f"Rank override from launcher: {args.tier}")

    cfg["prior_tier"], cfg["fallback_prior_region"] = prior_for_tier(cfg["tier"])
    print(f"Prior for late items: {cfg['prior_tier']} / {cfg['fallback_prior_region']}")

    try:
        items = load_items()
        item_details = load_item_details()
        decision, silver, p0, p_avg, alpha = build_decision(cfg, items, item_details)

        today = date.today().isoformat()
        selection = {
            "champion": cfg["champion"],
            "item1": decision["item1"]["id"],
            "pair": decision["item2"]["path"],
            "core": decision["core"]["path"],
            "core_name": decision["core"]["name"],
            "boots": decision["boots"]["id"],
            "item4": decision["item4"]["id"],
            "item5": decision["item5"]["id"],
            "item6": decision["item6"]["id"],
            "buy_order": [row["id"] for row in decision["buy_order"]],
        }
        scores = {
            "item1": compact_score(decision["item1"]),
            "pair": compact_score(decision["item2"]),
            "core": compact_score(decision["core"]),
        }

        history = load_history()
        previous = previous_calendar_entry(history, today, cfg.get("tier"), champion=cfg["champion"])
        lam = float((decision.get("context") or {}).get("lambda") or cfg.get("lambda_risk", 0.55))
        validation = validate_against_previous(
            previous, silver, p0, p_avg, alpha, cfg, selection, lam
        )
        decision["validation"] = validation

        bl = update_blacklist(
            history
            + [
                {
                    "date": today,
                    "champion": cfg["champion"],
                    "tier": cfg["tier"],
                    "selection": selection,
                    "validation": validation,
                }
            ],
            today,
            cfg["tier"],
            cfg,
        )
        if bl:
            decision["blacklist"] = bl
            print(f"Blacklisted faded core until {bl['until']}: {bl['core']}")

        snapshot = {
            "date": today,
            "champion": cfg["champion"],
            "generated_at": decision["generated_at"],
            "patch": cfg["patch"],
            "tier": cfg["tier"],
            "region": cfg["region"],
            "alpha": (decision.get("context") or {}).get("alpha"),
            "lambda": lam,
            "selection": selection,
            "scores": scores,
            "validation": validation,
            "grid": decision.get("grid") or {},
        }

        itemset = make_itemset(cfg, decision)
        OUTPUT_DIR.mkdir(exist_ok=True)
        write_json(OUTPUT_DIR / "decision.json", decision)
        write_json(OUTPUT_DIR / "validation.json", validation)
        write_json(OUTPUT_DIR / cfg["itemset_filename"], itemset)

        gem_itemsets: list[tuple[dict, str]] = []
        champ_slug = cfg["champion"]
        for gem in decision.get("gems") or []:
            slot = int(gem.get("slot") or (len(gem_itemsets) + 1))
            gem_set = make_itemset(
                cfg,
                gem,
                title=gem["set_title"],
                uid_key=f"markov-{champ_slug}-gem-{slot}",
                sortrank=slot,
            )
            filename = f"RIOT_ItemSet_GemHunter_{slot}.json"
            write_json(OUTPUT_DIR / filename, gem_set)
            gem_itemsets.append((gem_set, filename))

        append_history(snapshot)
        dest, index_path = install_itemset(cfg, itemset)
        for gem_set, filename in gem_itemsets:
            _gem_dest, index_path = install_itemset(cfg, gem_set, filename=filename)
            print(f"Installed {gem_set['title']}")

        used_uids = {row[0]["uid"] for row in gem_itemsets}
        stale_gem_uids = {gem_uid(slot, champ_slug) for slot in (1, 2)} - used_uids
        drop_itemsets(cfg, stale_gem_uids)

        print_summary(cfg, decision, dest, index_path)
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
