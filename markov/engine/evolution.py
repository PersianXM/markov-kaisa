"""Champion mechanics, stat accumulation, Kai'Sa evolutions, and adaptive item branches."""

from __future__ import annotations

from typing import Any

# Kai'Sa base stat growth constants for evolution breakpoints
KAISA_AD_PER_LEVEL = 2.6
KAISA_AS_PER_LEVEL = 0.018  # 1.8% per level


def get_item_stat(item_detail: dict, stat_key: str) -> float:
    """Safely extracts a numeric stat modifier from an item detail dict."""
    stats = item_detail.get("stats") or {}
    return float(stats.get(stat_key, 0.0))


def calculate_item_stats(item_ids: list[str], item_details: dict[str, dict]) -> dict[str, float]:
    """Calculates cumulative bonus AD, AP, Attack Speed, and total gold cost from item list."""
    total_ad = 0.0
    total_ap = 0.0
    total_as = 0.0
    total_gold = 0.0

    for iid in item_ids:
        detail = item_details.get(str(iid)) or {}
        total_ad += get_item_stat(detail, "FlatPhysicalDamageMod")
        total_ap += get_item_stat(detail, "FlatMagicDamageMod")
        # AS is represented as decimal in DDragon (0.35 = 35%)
        as_val = get_item_stat(detail, "PercentAttackSpeedMod")
        total_as += as_val * 100.0

        gold_info = detail.get("gold") or {}
        total_gold += float(gold_info.get("total", 0.0))

    return {
        "ad": round(total_ad, 1),
        "ap": round(total_ap, 1),
        "as_percent": round(total_as, 1),
        "gold": round(total_gold),
    }


def estimate_kaisa_q_level(bonus_ad_items: float) -> int | None:
    """Estimates the champion level where Kai'Sa reaches 100 bonus AD for Q evolution."""
    if bonus_ad_items >= 100.0:
        return 1
    needed = 100.0 - bonus_ad_items
    # League stat growth formula at level L: growth_multiplier = (L - 1) * (0.7025 + 0.0175 * (L - 1))
    for level in range(2, 19):
        growth_mult = (level - 1) * (0.7025 + 0.0175 * (level - 1))
        gained_ad = growth_mult * KAISA_AD_PER_LEVEL
        if gained_ad >= needed:
            return level
    return None


def estimate_kaisa_e_level(bonus_as_items_pct: float) -> int | None:
    """Estimates the champion level where Kai'Sa reaches 100% bonus AS for E evolution."""
    if bonus_as_items_pct >= 100.0:
        return 1
    needed = 100.0 - bonus_as_items_pct
    for level in range(2, 19):
        growth_mult = (level - 1) * (0.7025 + 0.0175 * (level - 1))
        gained_as_pct = growth_mult * (KAISA_AS_PER_LEVEL * 100.0)
        if gained_as_pct >= needed:
            return level
    return None


def track_evolution_progress(
    buy_order_ids: list[str],
    item_details: dict[str, dict],
    champion_slug: str = "kaisa",
    start_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Evaluates step-by-step stat accumulation and evolution completion for Kai'Sa."""
    if champion_slug != "kaisa":
        return {"supported": False}

    current_ids = list(start_ids or ["1055"])  # Default Doran's Blade
    milestones: list[dict[str, Any]] = []

    q_evolved = False
    q_step = None
    q_level = None

    w_evolved = False
    w_step = None

    e_evolved = False
    e_step = None
    e_level = None

    for idx, item_id in enumerate(buy_order_ids, 1):
        current_ids.append(item_id)
        stats = calculate_item_stats(current_ids, item_details)
        detail = item_details.get(str(item_id)) or {}
        name = detail.get("name", str(item_id))

        # Check Q (100 AD)
        if not q_evolved:
            lvl = estimate_kaisa_q_level(stats["ad"])
            if lvl is not None:
                q_evolved = True
                q_step = f"Item {idx} ({name})"
                q_level = lvl

        # Check W (100 AP - purely from items, no level scaling)
        if not w_evolved and stats["ap"] >= 100.0:
            w_evolved = True
            w_step = f"Item {idx} ({name})"

        # Check E (100% AS)
        if not e_evolved:
            lvl_e = estimate_kaisa_e_level(stats["as_percent"])
            if lvl_e is not None:
                e_evolved = True
                e_step = f"Item {idx} ({name})"
                e_level = lvl_e

        milestones.append({
            "step": idx,
            "item_id": item_id,
            "item_name": name,
            "ad": stats["ad"],
            "ap": stats["ap"],
            "as_percent": stats["as_percent"],
            "gold": stats["gold"],
        })

    return {
        "supported": True,
        "q": {
            "evolved": q_evolved,
            "step": q_step,
            "level_estimate": q_level,
            "final_ad": milestones[-1]["ad"] if milestones else 0.0,
        },
        "w": {
            "evolved": w_evolved,
            "step": w_step,
            "final_ap": milestones[-1]["ap"] if milestones else 0.0,
        },
        "e": {
            "evolved": e_evolved,
            "step": e_step,
            "level_estimate": e_level,
            "final_as_percent": milestones[-1]["as_percent"] if milestones else 0.0,
        },
        "milestones": milestones,
    }


def determine_damage_profile(core_item_ids: list[str], item_details: dict[str, dict]) -> str:
    """Classifies a build into 'ad_crit', 'ap_burst', or 'on_hit_hybrid'."""
    total_ad = 0.0
    total_ap = 0.0
    total_as = 0.0

    for iid in core_item_ids:
        detail = item_details.get(str(iid)) or {}
        total_ad += get_item_stat(detail, "FlatPhysicalDamageMod")
        total_ap += get_item_stat(detail, "FlatMagicDamageMod")
        total_as += get_item_stat(detail, "PercentAttackSpeedMod") * 100.0

    if total_ap >= total_ad * 1.3:
        return "ap_burst"
    if total_as >= 60.0 and (total_ap >= 40.0 or "3302" in core_item_ids or "3153" in core_item_ids):
        return "on_hit_hybrid"
    return "ad_crit"


def get_early_components(
    first_item_ids: list[str],
    item_details: dict[str, dict],
    max_components: int = 6,
) -> list[str]:
    """Extracts high-priority component items needed to construct the early items."""
    components: list[str] = []
    seen: set[str] = set()

    for item_id in first_item_ids:
        detail = item_details.get(str(item_id)) or {}
        for sub_id in detail.get("from") or []:
            sub_id = str(sub_id)
            if sub_id not in seen:
                seen.add(sub_id)
                components.append(sub_id)
                if len(components) >= max_components:
                    return components
    return components


def get_adaptive_counter_items(
    profile: str,
    chosen_ids: set[str],
    item_details: dict[str, dict],
) -> dict[str, list[str]]:
    """Selects situational counter items strictly compatible with the build's damage profile."""
    # Profiles:
    # AD/Crit:
    #   tanks: Lord Dominik's Regards (3036), Mortal Reminder (3033), Blade of the Ruined King (3153)
    #   burst: Immortal Shieldbow (6673), Guardian Angel (3026), Bloodthirster (3072)
    #   ap: Maw of Malmortius (3156), Wit's End (3091), Mercurial Scimitar (3139)
    # AP:
    #   tanks: Cryptbloom (3137), Void Staff (3135), Liandry's Torment (3151)
    #   burst: Zhonya's Hourglass (3157), Banshee's Veil (3102)
    #   ap: Banshee's Veil (3102), Kaenic Rookern (6701)
    # On-Hit/Hybrid:
    #   tanks: Terminus (3302), Blade of the Ruined King (3153), Lord Dominik's Regards (3036)
    #   burst: Zhonya's Hourglass (3157), Guardian Angel (3026), Immortal Shieldbow (6673)
    #   ap: Wit's End (3091), Banshee's Veil (3102), Maw of Malmortius (3156)

    pools = {
        "ad_crit": {
            "vs_tanks": ["3036", "3033", "3153"],
            "vs_burst": ["6673", "3026", "3072"],
            "vs_ap": ["3156", "3091", "3139"],
        },
        "ap_burst": {
            "vs_tanks": ["3137", "3135", "3151"],
            "vs_burst": ["3157", "3102"],
            "vs_ap": ["3102", "6701"],
        },
        "on_hit_hybrid": {
            "vs_tanks": ["3302", "3153", "3036"],
            "vs_burst": ["3157", "3026", "6673"],
            "vs_ap": ["3091", "3102", "3156"],
        },
    }

    selected_pool = pools.get(profile, pools["ad_crit"])
    result = {}
    for key, ids in selected_pool.items():
        filtered = [iid for iid in ids if iid not in chosen_ids]
        result[key] = filtered[:2]
    return result
