"""Lolalytics API and HTML scraping client."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from markov.data.ddragon import ddragon_patch, http_json, http_text

START_ITEM_RE = re.compile(
    r"(\d{4,6}),(\d+\.\d{2}),(1086|1055|1054|1056|1083)(?:,(2003|2010|2031))?"
)
SKILL_RE = re.compile(r'"(QEW|QWE|EQW|EWQ|WQE|WEQ)",(\d+),(\d+\.\d+)')
KEYSTONE_PAGE_RE = re.compile(r"(8008|8005|8010),(\d{4}),(\d{4}),(\d{4})")
SECONDARY_RE = re.compile(r"(83\d{2}),(83\d{2})")

RUNE_NAMES = {
    "8005": "Press the Attack",
    "8008": "Lethal Tempo",
    "8009": "Presence of Mind",
    "8010": "Conqueror",
    "8014": "Coup de Grace",
    "8017": "Cut Down",
    "8299": "Last Stand",
    "8304": "Magical Footwear",
    "8313": "Perfect Timing",
    "8345": "Biscuit Delivery",
    "8347": "Cosmic Insight",
    "9103": "Legend: Alacrity",
    "9104": "Legend: Haste",
    "9105": "Legend: Bloodline",
    "9111": "Triumph",
    "5001": "Health",
    "5005": "Attack Speed",
    "5007": "Ability Haste",
    "5008": "Adaptive Force",
}


def resolve_live_patch(cfg: dict) -> str:
    """Read the patch Lolalytics is currently serving (not a hardcoded value)."""
    configured = str(cfg.get("patch", "auto")).strip().lower()
    if configured not in {"", "auto", "latest", "current"}:
        print(f"Using configured patch {configured}")
        return configured

    url = (
        f"https://lolalytics.com/lol/{cfg['champion']}/build/"
        f"?tier={cfg['tier']}&region={cfg['region']}&lane={cfg['lane']}"
    )
    try:
        html = http_text(url, timeout=12, referer=url)
        match = re.search(
            rf"{cfg['champion']}_[^\"]*?_(\d+\.\d+)(?:_|\")",
            html,
            re.I,
        )
        if not match:
            match = re.search(r"Patch(?:</[^>]+>)?\s*(\d+\.\d+)", html, re.I)
        if match:
            patch = match.group(1)
            print(f"Live patch from Lolalytics: {patch}")
            return patch
    except Exception:
        pass

    patch = ddragon_patch()
    print(f"Live patch from Data Dragon: {patch}")
    return patch


def fetch_itemsets(cfg: dict, tier: str, region: str) -> dict:
    """Fetches Actually-Built item set data from Lolalytics API."""
    url = (
        "https://a1.lolalytics.com/mega/?ep=build-itemset&v=1"
        f"&patch={cfg['patch']}&c={cfg['champion']}&lane={cfg['lane']}"
        f"&tier={tier}&queue={cfg['queue']}&region={region}"
    )
    raw = http_json(url)
    if "itemSets" not in raw:
        raise RuntimeError(f"No itemSets in response for {tier}/{region}")
    return raw["itemSets"]


def fetch_baseline(cfg: dict) -> tuple[float, float]:
    """Scrapes the champion's baseline winrate and average tier winrate."""
    url = (
        f"https://lolalytics.com/lol/{cfg['champion']}/build/"
        f"?tier={cfg['tier']}&region={cfg['region']}"
        f"&lane={cfg['lane']}&patch={cfg['patch']}"
    )
    p0 = 0.50
    p_avg = 0.50
    try:
        html = http_text(url, timeout=12, referer=url)
        m = re.search(r"has a (\d+\.\d+)% win rate", html)
        if m:
            p0 = float(m.group(1)) / 100.0
        m = re.search(r"Average[^\d]{0,80}(\d+\.\d+)%", html)
        if m:
            p_avg = float(m.group(1)) / 100.0
    except Exception:
        pass
    return p0, p_avg


def fetch_champion_page(cfg: dict, patch: str | None = None) -> str:
    """Fetches the Lolalytics build page HTML for the champion."""
    url = (
        f"https://lolalytics.com/lol/{cfg['champion']}/build/"
        f"?tier={cfg['tier']}&region={cfg['region']}&lane={cfg['lane']}"
    )
    if patch:
        url += f"&patch={patch}"
    try:
        return http_text(url, timeout=15, referer=url)
    except Exception:
        return ""


def parse_start_sets(html: str) -> list[tuple[list[str], float, float]]:
    """Parses starting item sets from Lolalytics HTML using regex."""
    seen: dict[tuple[str, ...], tuple[list[str], float, float]] = {}
    for match in START_ITEM_RE.finditer(html):
        games = float(match.group(1))
        wr = float(match.group(2))
        ids = [match.group(3)]
        if match.group(4):
            ids.append(match.group(4))
        key = tuple(ids)
        prev = seen.get(key)
        if prev is None or games > prev[1]:
            seen[key] = (ids, games, wr)
    return list(seen.values())


def choose_start_items(
    html: str,
    p0: float,
    p_avg: float,
    alpha: float,
    lam: float,
    n_min: float,
) -> tuple[list[str], dict | None]:
    """Selects the best starting items by scoring parsed start sets."""
    from markov.engine.math_utils import score

    best_ids = ["1055", "2003"]
    best_score = None
    for ids, games, wr in parse_start_sets(html):
        wins = wr / 100.0 * games
        s = score(wins, games, p0, p_avg, alpha, n_min, lam)
        if not s or s["U"] is None:
            continue
        if best_score is None or s["U"] > best_score["U"]:
            best_score = s
            best_ids = list(ids)
    potions = {"2003", "2010", "2031"}
    if not any(item_id in potions for item_id in best_ids):
        best_ids = [best_ids[0], "2003"]
    return best_ids, best_score


def parse_skill_order(
    html: str,
    p0: float,
    p_avg: float,
    alpha: float,
    lam: float,
    n_min: float = 2000,
) -> dict | None:
    """Parses and scores skill level-up orders from HTML."""
    from markov.engine.math_utils import score

    best = None
    for match in SKILL_RE.finditer(html):
        order = match.group(1)
        games = float(match.group(2))
        wr = float(match.group(3))
        scored = score(wr / 100.0 * games, games, p0, p_avg, alpha, n_min, lam)
        if not scored or scored["U"] is None:
            continue
        if best is None or scored["U"] > best["U"]:
            best = {"order": order, **scored}
    return best


def parse_runes(html: str) -> dict | None:
    """Parses the most common rune page from HTML."""
    pages: Counter[tuple[str, ...]] = Counter()
    for match in KEYSTONE_PAGE_RE.finditer(html):
        pages[match.groups()] += 1
    if not pages:
        return None
    page = pages.most_common(1)[0][0]
    seconds: Counter[tuple[str, ...]] = Counter()
    for match in SECONDARY_RE.finditer(html):
        seconds[match.groups()] += 1
    secondary = seconds.most_common(1)[0][0] if seconds else ("8345", "8304")
    ids = list(page) + list(secondary)
    names = [RUNE_NAMES.get(iid, iid) for iid in ids]
    return {
        "ids": ids,
        "names": names,
        "keystone": RUNE_NAMES.get(page[0], page[0]),
        "title": " / ".join(names[:4]),
        "secondary": " / ".join(names[4:]),
    }


def fetch_counters(cfg: dict) -> dict:
    """Fetches counter and matchup data from Lolalytics API."""
    url = (
        "https://a1.lolalytics.com/mega/?ep=counter&v=1"
        f"&patch={cfg['patch']}&c={cfg['champion']}&lane={cfg['lane']}"
        f"&tier={cfg['tier']}&queue={cfg['queue']}&region={cfg['region']}"
    )
    return http_json(url)
