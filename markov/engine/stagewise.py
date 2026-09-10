"""Stagewise Markov decision chain and joint finish solver."""

from __future__ import annotations

from markov.data.ddragon import is_boots, item_name
from markov.engine.aggregation import actually_built
from markov.engine.evolution import (
    determine_damage_profile,
    get_adaptive_counter_items,
)
from markov.engine.math_utils import (
    hierarchical_tilde,
    late_utility,
    lookup,
    score,
    score_path,
)

ITEMS_BY_TAG = {
    "hypercarry": ("3036", "3302", "3026"),
    "tanky_dps": ("3036", "3153", "3302"),
    "crit_adc": ("3026", "3036", "3072"),
    "poke_adc": ("3026", "3036"),
    "ap_burst": ("3102", "3156", "3157"),
    "tank": ("3036", "3302", "3153"),
    "assassin": ("3026", "3156", "3139"),
    "support": ("3026", "3102"),
    "generic": ("3026", "3036"),
}

CHAMP_TAGS = {
    22: {"crit_adc"},  # Ashe
    51: {"crit_adc"},  # Caitlyn
    81: {"poke_adc"},  # Ezreal
    202: {"crit_adc"},  # Jhin
    222: {"crit_adc", "hypercarry"},  # Jinx
    429: {"crit_adc"},  # Kalista
    96: {"hypercarry", "tanky_dps"},  # Kog'Maw
    236: {"crit_adc"},  # Lucian
    21: {"crit_adc"},  # Miss Fortune
    145: {"generic"},  # Kai'Sa
    360: {"crit_adc"},  # Samira
    15: {"crit_adc"},  # Sivir
    901: {"poke_adc"},  # Smolder
    18: {"crit_adc"},  # Tristana
    29: {"crit_adc"},  # Twitch
    110: {"poke_adc"},  # Varus
    67: {"crit_adc"},  # Vayne
    498: {"crit_adc"},  # Xayah
    221: {"crit_adc"},  # Zeri
    523: {"crit_adc"},  # Aphelios
    235: {"support"},  # Senna
    800: {"ap_burst"},  # Mel
    99: {"ap_burst"},  # Lux
    101: {"ap_burst"},  # Xerath
    112: {"ap_burst"},  # Viktor
    157: {"assassin"},  # Yasuo
    238: {"assassin"},  # Zed
    91: {"assassin"},  # Talon
    55: {"assassin"},  # Katarina
    121: {"assassin"},  # Khazix
    64: {"assassin"},  # Lee Sin
    86: {"tank"},  # Garen
    54: {"tank"},  # Malphite
    122: {"tank"},  # Darius
    14: {"tank"},  # Sion
}


def rank_paths(
    agg: dict,
    p0: float,
    p_avg: float,
    alpha: float,
    n_min: float,
    lam: float = 0.55,
) -> list[tuple[str, dict]]:
    """Ranks all paths at a given depth by utility U, filtering by sample floor n_min."""
    rows: list[tuple[str, dict]] = []
    for path, (games, wins) in agg.items():
        s = score(wins, games, p0, p_avg, alpha, n_min, lam)
        if s and not s["reject"] and s["U"] is not None:
            rows.append((path, s))
    rows.sort(key=lambda row: row[1]["U"], reverse=True)
    return rows


def most_common_extension(
    agg: dict,
    prefix: str,
    exclude: set[str] | None = None,
) -> dict | None:
    """Finds the most popular next item extending a prefix path as a robust fallback."""
    exclude = exclude or set()
    best_id = None
    best_n = -1.0
    for path, (games, _wins) in agg.items():
        if prefix and not path.startswith(prefix + "_"):
            continue
        last = path.split("_")[-1]
        if last in exclude:
            continue
        if games > best_n:
            best_n = games
            best_id = last
    if best_id is None:
        return None
    return {
        "id": best_id,
        "U": 0.0,
        "n": best_n,
        "fallback": True,
        "source": "most_common",
    }


def most_common_sixth(silver: dict, core: str, owned: set[str]) -> dict | None:
    """Finds the most common 6th item among builds containing a given core."""
    core_ids = core.split("_")
    counts: dict[str, float] = {}
    for path, (games, _wins) in actually_built(silver, 5).items():
        ids = path.split("_")
        if not all(part in ids for part in core_ids):
            continue
        for iid in ids:
            if iid in owned:
                continue
            counts[iid] = counts.get(iid, 0.0) + games
    if not counts:
        return None
    best_id = max(counts, key=counts.get)
    return {
        "id": best_id,
        "U": 0.0,
        "n": counts[best_id],
        "fallback": True,
        "source": "most_common",
    }


def list_boot_candidates(
    items: dict[int, str],
    itemsets: dict,
    first_two: str,
    p0: float,
    p_avg: float,
    alpha: float,
    lam: float,
    n_min: float = 800,
    limit: int = 4,
) -> list[dict]:
    """Lists and scores boot options compatible with the first two core items."""
    a, b = first_two.split("_")[:2]
    found: list[dict] = []
    seen: set[str] = set()
    for path, (games, wins) in actually_built(itemsets, 3, boot=True).items():
        ids = path.split("_")
        if a not in ids or b not in ids:
            continue
        s = score(wins, games, p0, p_avg, alpha, n_min, lam)
        if not s or s["U"] is None:
            continue
        boots = [item_id for item_id in ids if is_boots(items, item_id)]
        if not boots or boots[0] in seen:
            continue
        seen.add(boots[0])
        found.append({"id": boots[0], "U": s["U"], "n": s["n"], "tilde": s["tilde"]})
    found.sort(key=lambda row: row["U"], reverse=True)
    return found[:limit]


def choose_boots(
    items: dict[int, str],
    itemsets: dict,
    first_two: str,
    p0: float,
    p_avg: float,
    alpha: float,
) -> str:
    """Legacy boot selection: picks the highest-U boots for a given first-two pair."""
    a, b = first_two.split("_")[:2]
    boot3 = actually_built(itemsets, 3, boot=True)
    best_id = "3006"
    best_u = None
    for path, (games, wins) in boot3.items():
        ids = path.split("_")
        if a not in ids or b not in ids:
            continue
        s = score(wins, games, p0, p_avg, alpha, 800)
        if not s or s["U"] is None:
            continue
        boots = [item_id for item_id in ids if is_boots(items, item_id)]
        if not boots:
            continue
        if best_u is None or s["U"] > best_u:
            best_u = s["U"]
            best_id = boots[0]
    return best_id


def pick_late_item(
    silver_agg: dict,
    prior_agg: dict,
    prefix: str,
    p0: float,
    p_avg: float,
    alpha: float,
    n_min: float,
    exclude: set[str] | None = None,
    lam: float = 0.55,
) -> dict | None:
    """Picks the single best late item extending a prefix path."""
    rows = list_late_items(
        silver_agg, prior_agg, prefix, p0, p_avg, alpha, n_min, exclude, lam, 1
    )
    return rows[0] if rows else None


def choose_late_items(
    silver_sets: dict,
    prior_sets: dict,
    core: str,
    p0: float,
    p_avg: float,
    alpha: float,
    n_min4: float,
    n_min5: float,
) -> tuple[dict | None, dict | None]:
    """Selects items 4 and 5 sequentially after the core."""
    item4 = pick_late_item(
        actually_built(silver_sets, 4),
        actually_built(prior_sets, 4),
        core,
        p0,
        p_avg,
        alpha,
        n_min4,
    )
    prefix = core + (f"_{item4['id']}" if item4 else "")
    exclude = {item4["id"]} if item4 else set()
    item5 = pick_late_item(
        actually_built(silver_sets, 5),
        actually_built(prior_sets, 5),
        prefix,
        p0,
        p_avg,
        alpha,
        n_min5,
        exclude=exclude,
    )
    return item4, item5


def list_late_items(
    silver_agg: dict,
    prior_agg: dict,
    prefix: str,
    p0: float,
    p_avg: float,
    alpha: float,
    n_min: float,
    exclude: set[str] | None = None,
    lam: float = 0.55,
    limit: int = 1,
) -> list[dict]:
    """Lists and ranks late items extending a prefix path using hierarchical empirical Bayes."""
    exclude = exclude or set()
    found: list[dict] = []
    for path, (games, wins) in silver_agg.items():
        if not path.startswith(prefix + "_"):
            continue
        last = path.split("_")[-1]
        if last in exclude or games < n_min:
            continue
        tilde = hierarchical_tilde((games, wins), lookup(prior_agg, path), p0, alpha)
        if tilde is None:
            continue
        found.append(
            {
                "id": last,
                "path": path,
                "n": games,
                "wr": wins / games,
                "tilde": tilde,
                "U": late_utility(tilde, games, p_avg, alpha, lam),
            }
        )
    found.sort(key=lambda row: row["U"], reverse=True)
    return found[:limit]


def pick_sixth_legendary(
    silver_sets: dict,
    prior_sets: dict,
    core: str,
    item4: str,
    item5: str,
    owned: set[str],
    p0: float,
    p_avg: float,
    alpha: float,
    n_min: float,
    lam: float = 0.55,
) -> dict | None:
    """Picks the 6th legendary item using exact depth-6 data or late-presence fallback."""
    prefix5 = f"{core}_{item4}_{item5}"
    exact_list = list_late_items(
        actually_built(silver_sets, 6),
        actually_built(prior_sets, 6),
        prefix5,
        p0,
        p_avg,
        alpha,
        n_min,
        exclude=owned,
        lam=lam,
        limit=1,
    )
    if exact_list:
        exact = exact_list[0]
        exact["source"] = "itemSet6"
        return exact

    def accumulate(itemsets: dict, depth: int, boot: bool) -> dict[str, list[float]]:
        tallies: dict[str, list[float]] = {}
        for path, (games, wins) in actually_built(itemsets, depth, boot=boot).items():
            ids = path.split("_")
            if not path.startswith(core + "_"):
                continue
            for iid in ids:
                if iid in owned:
                    continue
                bucket = tallies.setdefault(iid, [0.0, 0.0])
                bucket[0] += games
                bucket[1] += wins
        return tallies

    silver_t = accumulate(silver_sets, 5, False)
    prior_t = accumulate(prior_sets, 5, False)
    for extra_s, extra_p in (
        (accumulate(silver_sets, 6, True), accumulate(prior_sets, 6, True)),
    ):
        for iid, (g, w) in extra_s.items():
            bucket = silver_t.setdefault(iid, [0.0, 0.0])
            bucket[0] += g
            bucket[1] += w
        for iid, (g, w) in extra_p.items():
            bucket = prior_t.setdefault(iid, [0.0, 0.0])
            bucket[0] += g
            bucket[1] += w

    best: dict | None = None
    for iid, (games, wins) in silver_t.items():
        if games < n_min:
            continue
        prior = tuple(prior_t[iid]) if iid in prior_t else None
        tilde = hierarchical_tilde((games, wins), prior, p0, alpha)
        if tilde is None:
            continue
        utility = late_utility(tilde, games, p_avg, alpha, lam)
        cand = {
            "id": iid,
            "path": f"{prefix5}_{iid}",
            "n": games,
            "wr": wins / games,
            "tilde": tilde,
            "U": utility,
            "source": "late-presence",
        }
        if best is None or utility > best["U"]:
            best = cand
    return best


def list_sixth_candidates(
    silver_sets: dict,
    prior_sets: dict,
    core: str,
    item4: str,
    item5: str,
    owned: set[str],
    p0: float,
    p_avg: float,
    alpha: float,
    n_min: float,
    lam: float,
    limit: int = 3,
) -> list[dict]:
    """Lists candidate 6th items by iteratively picking the best remaining."""
    one = pick_sixth_legendary(
        silver_sets, prior_sets, core, item4, item5, owned, p0, p_avg, alpha, n_min, lam
    )
    if not one:
        return []
    rows = [one]
    blocked = set(owned)
    blocked.add(one["id"])
    for _ in range(limit - 1):
        nxt = pick_sixth_legendary(
            silver_sets, prior_sets, core, item4, item5, blocked, p0, p_avg, alpha, n_min, lam
        )
        if not nxt:
            break
        rows.append(nxt)
        blocked.add(nxt["id"])
    return rows


def joint_finish(
    items: dict[int, str],
    silver: dict,
    prior: dict,
    core: str,
    pair: str,
    p0: float,
    p_avg: float,
    alpha: float,
    lam: float,
    cfg: dict,
) -> dict:
    """Searches over all combinations of boots, items 4-6 to find the optimal joint finish."""
    boots = list_boot_candidates(
        items, silver, pair, p0, p_avg, alpha, lam, float(cfg.get("n_min_boots", 800)), 4
    )
    if not boots:
        boots = [
            most_common_extension(actually_built(silver, 3, boot=True), pair)
            or {"id": "3006", "U": 0.0, "n": 0, "fallback": True, "source": "most_common"}
        ]

    i4s = list_late_items(
        actually_built(silver, 4),
        actually_built(prior, 4),
        core,
        p0,
        p_avg,
        alpha,
        cfg["n_min_item4"],
        set(),
        lam,
        5,
    )
    if not i4s:
        i4s = [
            most_common_extension(actually_built(silver, 4), core)
            or {"id": "3157", "U": 0.0, "n": 0, "fallback": True, "source": "most_common"}
        ]

    silver5 = actually_built(silver, 5)
    prior5 = actually_built(prior, 5)
    best = None
    leftovers: list[dict] = []

    for boot in boots:
        for i4 in i4s:
            i5s = list_late_items(
                silver5,
                prior5,
                f"{core}_{i4['id']}",
                p0,
                p_avg,
                alpha,
                cfg["n_min_item5"],
                {i4["id"]},
                lam,
                4,
            )
            if not i5s:
                i5s = [
                    most_common_extension(silver5, f"{core}_{i4['id']}", {i4["id"]})
                    or {"id": "3089", "U": 0.0, "n": 0, "fallback": True, "source": "most_common"}
                ]
            leftovers.extend(i5s)
            for i5 in i5s:
                owned = set(core.split("_") + [boot["id"], i4["id"], i5["id"]])
                i6s = list_sixth_candidates(
                    silver,
                    prior,
                    core,
                    i4["id"],
                    i5["id"],
                    owned,
                    p0,
                    p_avg,
                    alpha,
                    cfg["n_min_item6"],
                    lam,
                    3,
                )
                if not i6s:
                    i6s = [
                        most_common_sixth(silver, core, owned)
                        or {"id": "4645", "U": 0.0, "n": 0, "fallback": True, "source": "most_common"}
                    ]
                leftovers.extend(i6s)
                for i6 in i6s:
                    path45 = f"{core}_{i4['id']}_{i5['id']}"
                    scored45 = score_path(
                        silver5, path45, p0, p_avg, alpha, cfg["n_min_item5"], lam
                    )
                    u45 = scored45["U"] if scored45 and scored45["U"] is not None else (i4.get("U") or 0.0)
                    u_joint = 0.50 * u45 + 0.25 * (boot.get("U") or 0.0) + 0.25 * (i6.get("U") or 0.0)
                    cand = {
                        "boots": boot,
                        "item4": i4,
                        "item5": i5,
                        "item6": i6,
                        "u_joint": u_joint,
                        "u45": u45,
                    }
                    if best is None or u_joint > best["u_joint"]:
                        best = cand

    assert best is not None
    best["leftovers"] = leftovers
    return best


def champion_tags(cid: int, default_lane: str | None = None) -> set[str]:
    """Returns archetype tags for a champion ID."""
    if cid in CHAMP_TAGS:
        return set(CHAMP_TAGS[cid])
    lane = (default_lane or "").lower()
    if lane == "bottom":
        return {"crit_adc"}
    if lane == "middle":
        return {"ap_burst"}
    if lane == "support":
        return {"support"}
    if lane in {"jungle", "top"}:
        return {"assassin", "tank"}
    return {"generic"}


def items_for_tags(tags: set[str], chosen: set[str], limit: int = 3) -> list[str]:
    """Returns situational item IDs appropriate for given archetype tags."""
    picked: list[str] = []
    for tag in tags:
        for iid in ITEMS_BY_TAG.get(tag, ()):
            if iid in chosen or iid in picked:
                continue
            picked.append(iid)
            if len(picked) >= limit:
                return picked
    for iid in ITEMS_BY_TAG["generic"]:
        if iid in chosen or iid in picked:
            continue
        picked.append(iid)
        if len(picked) >= limit:
            break
    return picked


def short_champ_name(name: str) -> str:
    """Shortens a champion display name for compact branch labels."""
    cleaned = name.replace("'", "").replace(".", "")
    parts = cleaned.split()
    if len(parts) >= 2:
        return "".join(p[:3] for p in parts)[:8]
    return cleaned[:8]


def live_matchup_branches(
    cfg: dict,
    champions: dict[int, str],
    chosen: set[str],
    n_min: float = 80,
    weak_limit: int = 3,
    payload: dict | None = None,
    item_details: dict[str, dict] | None = None,
    core_ids: list[str] | None = None,
) -> tuple[list[dict], list[dict]]:
    """Build pre-game late-item branches from live Lolalytics counters with damage-profile adaptivity."""
    if payload is None:
        try:
            from markov.data.lolalytics import fetch_counters

            payload = fetch_counters(cfg)
        except Exception as exc:
            print(f"Counter fetch failed ({exc}); using archetype branches only.")
            payload = {}

    rows = list(payload.get("counters") or [])
    stats = payload.get("stats") or {}
    weak_ids = [int(x) for x in (stats.get("counters") or {}).get("weak") or []]
    by_cid = {int(row["cid"]): row for row in rows if "cid" in row}

    weak_rows: list[dict] = []
    for cid in weak_ids:
        row = by_cid.get(cid)
        if not row:
            continue
        games = float(row.get("n") or 0)
        if games < n_min:
            continue
        weak_rows.append(
            {
                "id": cid,
                "name": champions.get(cid, str(cid)),
                "vs_wr": float(row.get("vsWr") or 50) / 100.0,
                "n": games,
                "lane": row.get("defaultLane") or stats.get("vsLane") or "bottom",
            }
        )
    if not weak_rows:
        ranked = []
        for row in rows:
            games = float(row.get("n") or 0)
            if games < n_min:
                continue
            cid = int(row["cid"])
            ranked.append(
                {
                    "id": cid,
                    "name": champions.get(cid, str(cid)),
                    "vs_wr": float(row.get("vsWr") or 50) / 100.0,
                    "n": games,
                    "lane": row.get("defaultLane") or "bottom",
                }
            )
        ranked.sort(key=lambda r: (r["vs_wr"], -r["n"]))
        weak_rows = ranked[:weak_limit]
    else:
        weak_rows.sort(key=lambda r: (r["vs_wr"], -r["n"]))
        weak_rows = weak_rows[:weak_limit]

    branches: list[dict] = []
    if weak_rows:
        tags: set[str] = set()
        for row in weak_rows:
            tags |= champion_tags(row["id"], row.get("lane"))
        ids = items_for_tags(tags, chosen, limit=3)
        label = "/".join(short_champ_name(row["name"]) for row in weak_rows)
        branches.append(
            {
                "key": "vs_weak",
                "title": f"Vs {label} (late)",
                "ids": ids,
                "source": "live_counter",
                "champions": [row["name"] for row in weak_rows],
            }
        )

    # Determine adaptive archetype items matched to build damage profile
    damage_profile = "ad_crit"
    if item_details and core_ids:
        damage_profile = determine_damage_profile(core_ids, item_details)

    adaptive_items = get_adaptive_counter_items(
        damage_profile, chosen, item_details or {}
    )

    archetype_titles = {
        "vs_tanks": "Vs tanks (late)",
        "vs_burst": "Vs burst (late)",
        "vs_ap": "Vs AP (late)",
    }

    for key, title in archetype_titles.items():
        ids = adaptive_items.get(key, [])
        branches.append(
            {
                "key": key,
                "title": title,
                "ids": ids,
                "source": f"adaptive_{damage_profile}",
                "champions": [],
            }
        )

    return branches, weak_rows
