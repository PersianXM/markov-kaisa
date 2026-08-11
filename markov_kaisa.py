#!/usr/bin/env python3
"""Generate the Markov Kai'Sa item set from Lolalytics and install it."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import urllib.request
import uuid
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
OUTPUT_DIR = ROOT / "output"
HISTORY_DIR = ROOT / "history"
HISTORY_PATH = HISTORY_DIR / "daily.jsonl"
BLACKLIST_PATH = HISTORY_DIR / "blacklist.json"
DDRAGON_TIMEOUT = 25
LOL_TIMEOUT = 45
UA = {
    "User-Agent": "MarkovKaisa/1.0",
    "Referer": "https://lolalytics.com/lol/kaisa/build/",
    "Origin": "https://lolalytics.com",
    "Accept": "application/json,text/html,*/*",
}


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def http_bytes(url: str, timeout: int = LOL_TIMEOUT) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def http_json(url: str, timeout: int = LOL_TIMEOUT) -> dict:
    return json.loads(http_bytes(url, timeout=timeout).decode("utf-8", "ignore"))


def http_text(url: str, timeout: int = LOL_TIMEOUT) -> str:
    return http_bytes(url, timeout=timeout).decode("utf-8", "ignore")


def load_items() -> dict[int, str]:
    versions = http_json(
        "https://ddragon.leagueoflegends.com/api/versions.json",
        timeout=DDRAGON_TIMEOUT,
    )
    ver = versions[0]
    data = http_json(
        f"https://ddragon.leagueoflegends.com/cdn/{ver}/data/en_US/item.json",
        timeout=DDRAGON_TIMEOUT,
    )["data"]
    return {int(k): v["name"] for k, v in data.items()}


def item_name(items: dict[int, str], item_id: str) -> str:
    try:
        return items.get(int(item_id), item_id)
    except ValueError:
        return item_id


def path_name(items: dict[int, str], path: str) -> str:
    return " -> ".join(item_name(items, p) for p in path.split("_"))


def is_boots(items: dict[int, str], item_id: str) -> bool:
    name = item_name(items, item_id).lower()
    return any(
        key in name
        for key in ("boot", "greaves", "treads", "gluttonous")
    )


def ddragon_patch() -> str:
    versions = http_json(
        "https://ddragon.leagueoflegends.com/api/versions.json",
        timeout=DDRAGON_TIMEOUT,
    )
    return ".".join(str(versions[0]).split(".")[:2])


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
    html = http_text(url)
    match = re.search(
        r'kaisa_[^"]*?_(\d+\.\d+)(?:_|")',
        html,
        re.I,
    )
    if not match:
        match = re.search(r"Patch(?:</[^>]+>)?\s*(\d+\.\d+)", html, re.I)
    if match:
        patch = match.group(1)
        print(f"Live patch from Lolalytics: {patch}")
        return patch

    patch = ddragon_patch()
    print(f"Live patch from Data Dragon: {patch}")
    return patch


def fetch_itemsets(cfg: dict, tier: str, region: str) -> dict:
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
    url = (
        f"https://lolalytics.com/lol/{cfg['champion']}/build/"
        f"?tier={cfg['tier']}&region={cfg['region']}"
        f"&lane={cfg['lane']}&patch={cfg['patch']}"
    )
    html = http_text(url)
    p0 = 0.50
    p_avg = 0.50
    m = re.search(r"has a (\d+\.\d+)% win rate", html)
    if m:
        p0 = float(m.group(1)) / 100.0
    m = re.search(r"Average[^\d]{0,80}(\d+\.\d+)%", html)
    if m:
        p_avg = float(m.group(1)) / 100.0
    return p0, p_avg


def max_set_depth(itemsets: dict, boot: bool = False) -> int:
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


def shrink(wins: float, games: float, p0: float, alpha: float) -> float:
    return (wins + alpha * p0) / (games + alpha)


def ci95(p: float, n: float) -> float:
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


def rank_paths(
    agg: dict,
    p0: float,
    p_avg: float,
    alpha: float,
    n_min: float,
    lam: float = 0.55,
) -> list[tuple[str, dict]]:
    rows: list[tuple[str, dict]] = []
    for path, (games, wins) in agg.items():
        s = score(wins, games, p0, p_avg, alpha, n_min, lam)
        if s and not s["reject"] and s["U"] is not None:
            rows.append((path, s))
    rows.sort(key=lambda row: row[1]["U"], reverse=True)
    return rows


def champion_sample_n(itemsets: dict) -> float:
    return sum(games for games, _wins in actually_built(itemsets, 1).values())


def apply_share_floor(
    rows: list[tuple[str, dict]],
    total_n: float,
    share: float,
) -> list[tuple[str, dict]]:
    if total_n <= 0 or not rows:
        return rows
    floor = share * total_n
    kept = [row for row in rows if row[1]["n"] >= floor]
    return kept if kept else rows


def most_common_extension(
    agg: dict,
    prefix: str,
    exclude: set[str] | None = None,
) -> dict | None:
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


def hierarchical_tilde(
    silver: tuple[float, float] | None,
    prior: tuple[float, float] | None,
    p0: float,
    alpha: float,
) -> float | None:
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


def lookup(agg: dict, key: str) -> tuple[float, float] | None:
    if key not in agg:
        return None
    return agg[key]


def compact_score(s: dict | None) -> dict | None:
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


def score_path(
    agg: dict,
    path: str,
    p0: float,
    p_avg: float,
    alpha: float,
    n_min: float,
    lam: float = 0.55,
) -> dict | None:
    found = lookup(agg, path)
    if not found:
        return None
    games, wins = found
    return score(wins, games, p0, p_avg, alpha, n_min, lam)


def load_history() -> list[dict]:
    if not HISTORY_PATH.exists():
        return []
    rows = []
    for line in HISTORY_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def previous_calendar_entry(history: list[dict], today: str, tier: str | None = None) -> dict | None:
    prior = [
        row
        for row in history
        if row.get("date")
        and row["date"] < today
        and (tier is None or row.get("tier") == tier)
    ]
    return prior[-1] if prior else None


def verdict_from_delta(delta_u: float | None) -> str:
    if delta_u is None:
        return "unknown"
    if delta_u <= -0.01:
        return "faded"
    if delta_u >= 0.01:
        return "improved"
    if abs(delta_u) < 0.005:
        return "stable"
    return "mild"


def compare_metric(label: str, yesterday: dict | None, today: dict | None) -> dict:
    y = compact_score(yesterday) if yesterday else None
    t = compact_score(today) if today else None
    if y is None or t is None or y.get("U") is None or t.get("U") is None:
        return {
            "label": label,
            "yesterday": y,
            "today": t,
            "delta_U": None,
            "delta_tilde": None,
            "delta_n": None if y is None or t is None else (t.get("n") or 0) - (y.get("n") or 0),
            "verdict": "missing" if t is None else "unknown",
        }
    delta_u = t["U"] - y["U"]
    return {
        "label": label,
        "yesterday": y,
        "today": t,
        "delta_U": delta_u,
        "delta_tilde": t["tilde"] - y["tilde"],
        "delta_n": (t.get("n") or 0) - (y.get("n") or 0),
        "verdict": verdict_from_delta(delta_u),
    }


def rescore_selection(
    selection: dict,
    silver: dict,
    p0: float,
    p_avg: float,
    alpha: float,
    cfg: dict,
    lam: float = 0.55,
) -> dict:
    item1 = selection.get("item1")
    pair = selection.get("pair")
    core = selection.get("core")
    return {
        "item1": score_path(
            actually_built(silver, 1), item1, p0, p_avg, alpha, cfg["n_min_item1"], lam
        )
        if item1
        else None,
        "pair": score_path(
            actually_built(silver, 2), pair, p0, p_avg, alpha, cfg["n_min_item2"], lam
        )
        if pair
        else None,
        "core": score_path(
            actually_built(silver, 3), core, p0, p_avg, alpha, cfg["n_min_core"], lam
        )
        if core
        else None,
    }


def validate_against_previous(
    previous: dict | None,
    silver: dict,
    p0: float,
    p_avg: float,
    alpha: float,
    cfg: dict,
    today_selection: dict,
    lam: float = 0.55,
) -> dict:
    if previous is None:
        return {
            "status": "waiting",
            "message": "No previous calendar-day snapshot. Tomorrow this run will be validated.",
        }

    prev_sel = previous.get("selection") or {}
    prev_scores = previous.get("scores") or {}
    today_scores = rescore_selection(prev_sel, silver, p0, p_avg, alpha, cfg, lam)
    checks = [
        compare_metric("item1", prev_scores.get("item1"), today_scores.get("item1")),
        compare_metric("pair", prev_scores.get("pair"), today_scores.get("pair")),
        compare_metric("core", prev_scores.get("core"), today_scores.get("core")),
    ]
    core_check = checks[2]
    policy_changed = prev_sel.get("core") != today_selection.get("core")
    return {
        "status": "compared",
        "previous_date": previous.get("date"),
        "previous_patch": previous.get("patch"),
        "previous_core": prev_sel.get("core_name") or prev_sel.get("core"),
        "policy_changed": policy_changed,
        "checks": checks,
        "core_verdict": core_check["verdict"],
        "note": (
            "Compared yesterday's chosen paths on today's cumulative sample. "
            "Lolalytics is not a pure next-day holdout; n usually grows."
        ),
    }


def append_history(entry: dict) -> None:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    with HISTORY_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def load_blacklist() -> dict:
    if not BLACKLIST_PATH.exists():
        return {"cores": []}
    try:
        return json.loads(BLACKLIST_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"cores": []}


def save_blacklist(data: dict) -> None:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    BLACKLIST_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def active_blacklist(today: str) -> set[str]:
    banned: set[str] = set()
    for row in load_blacklist().get("cores") or []:
        core = row.get("core")
        until = row.get("until")
        if core and until and until > today:
            banned.add(core)
    return banned


def update_blacklist(
    history: list[dict],
    today: str,
    tier: str,
    cfg: dict,
) -> dict | None:
    streak_n = int(cfg.get("fade_blacklist_streak", 3))
    days = int(cfg.get("fade_blacklist_days", 7))
    compared = [
        row
        for row in history
        if row.get("tier") == tier
        and row.get("date")
        and (row.get("validation") or {}).get("status") == "compared"
    ]
    if len(compared) < streak_n:
        return None
    last = compared[-streak_n:]
    cores = [(row.get("selection") or {}).get("core") for row in last]
    if not cores[0] or any(core != cores[0] for core in cores):
        return None
    if any((row.get("validation") or {}).get("core_verdict") != "faded" for row in last):
        return None
    core = cores[0]
    until = (date.fromisoformat(today) + timedelta(days=days)).isoformat()
    data = load_blacklist()
    others = [row for row in data.get("cores") or [] if row.get("core") != core]
    entry = {
        "core": core,
        "from": today,
        "until": until,
        "reason": f"{streak_n} consecutive faded validations",
    }
    others.append(entry)
    data["cores"] = others
    save_blacklist(data)
    return entry


START_ITEM_RE = re.compile(
    r"(\d{4,6}),(\d+\.\d{2}),(1086|1055|1054|1056|1083)(?:,(2003|2010|2031))?"
)
HYPER_GRID = (
    (400.0, 0.30),
    (400.0, 0.55),
    (800.0, 0.55),
    (800.0, 0.80),
    (1600.0, 0.55),
    (1600.0, 0.80),
)


def fetch_champion_page(cfg: dict, patch: str | None = None) -> str:
    url = (
        f"https://lolalytics.com/lol/{cfg['champion']}/build/"
        f"?tier={cfg['tier']}&region={cfg['region']}&lane={cfg['lane']}"
    )
    if patch:
        url += f"&patch={patch}"
    return http_text(url)


def parse_start_sets(html: str) -> list[tuple[list[str], float, float]]:
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
SKILL_RE = re.compile(r'"(QEW|QWE|EQW|EWQ|WQE|WEQ)",(\d+),(\d+\.\d+)')
KEYSTONE_PAGE_RE = re.compile(r"(8008|8005|8010),(\d{4}),(\d{4}),(\d{4})")
SECONDARY_RE = re.compile(r"(83\d{2}),(83\d{2})")
VS_TANKS = ("3036", "3302", "6672", "3153")
VS_BURST = ("3026", "3156", "3111", "3140")
VS_AP = ("3157", "3102", "3222")


def parse_skill_order(
    html: str,
    p0: float,
    p_avg: float,
    alpha: float,
    lam: float,
    n_min: float = 2000,
) -> dict | None:
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


def parse_hard_matchups(html: str, limit: int = 4) -> list[dict]:
    found: dict[str, dict] = {}
    for match in re.finditer(
        r'"([a-z]{3,16})",(\d{3,7}),(\d+\.\d{2})',
        html,
    ):
        slug = match.group(1)
        games = float(match.group(2))
        wr = float(match.group(3))
        if slug in {"kaisa", "bottom", "silver", "gold", "emerald", "ranked", "euw"}:
            continue
        if games < 400 or wr < 35 or wr > 65:
            continue
        prev = found.get(slug)
        if prev is None or games > prev["n"]:
            found[slug] = {"champion": slug, "n": games, "wr": wr / 100.0}
    hard = [row for row in found.values() if row["wr"] < 0.48]
    hard.sort(key=lambda row: (row["wr"], -row["n"]))
    return hard[:limit]


def policy_situational(chosen: set[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for name, prefs in (
        ("vs_tanks", VS_TANKS),
        ("vs_burst", VS_BURST),
        ("vs_ap", VS_AP),
    ):
        picked = [iid for iid in prefs if iid not in chosen][:2]
        out[name] = picked
    return out


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
    one = pick_sixth_legendary(
        silver_sets, prior_sets, core, item4, item5, owned, p0, p_avg, alpha, n_min, lam
    )
    if not one:
        return []
    # Reuse presence tallies by asking pick for each leftover after excluding the winner iteratively.
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
    boots = list_boot_candidates(items, silver, pair, p0, p_avg, alpha, lam, 800, 4)
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


def compute_hyper_grid(silver: dict, p0: float, p_avg: float, cfg: dict) -> dict:
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
    default_a = float(cfg.get("alpha_rank", 800))
    default_l = float(cfg.get("lambda_risk", 0.55))
    prev = previous_calendar_entry(history, today, cfg.get("tier"))
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


def choose_boots(
    items: dict[int, str],
    itemsets: dict,
    first_two: str,
    p0: float,
    p_avg: float,
    alpha: float,
) -> str:
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


def late_utility(tilde: float, games: float, p_avg: float, alpha: float, lam: float = 0.55) -> float:
    return (tilde - p_avg) - lam * ci95(tilde, games + alpha)


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
    prefix5 = f"{core}_{item4}_{item5}"
    exact = pick_late_item(
        actually_built(silver_sets, 6),
        actually_built(prior_sets, 6),
        prefix5,
        p0,
        p_avg,
        alpha,
        n_min,
        exclude=owned,
        lam=lam,
    )
    if exact:
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


def build_decision(cfg: dict, items: dict[int, str]) -> tuple[dict, dict, float, float, float]:
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
    grid = compute_hyper_grid(silver, p0, p_avg, cfg)
    alpha, lam, hyper = select_hyperparams(history, today, silver, p0, p_avg, cfg, grid)
    print(
        f"Baseline p0={p0:.4f}  p_avg={p_avg:.4f}  "
        f"alpha={alpha:g}  lambda={lam:g}  ({hyper.get('status')})"
    )

    total_n = champion_sample_n(silver)
    item1_rows = apply_share_floor(
        rank_paths(actually_built(silver, 1), p0, p_avg, alpha, cfg["n_min_item1"], lam),
        total_n,
        float(cfg.get("min_pick_share_item1", 0.03)),
    )
    if not item1_rows:
        raise RuntimeError("No reliable Item 1 candidates.")
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
        print("Start: no set met n floor; fallback Doran's Bow")

    skills = parse_skill_order(html, p0, p_avg, alpha, lam, cfg.get("n_min_start", 2000))
    runes = parse_runes(html)
    matchups = parse_hard_matchups(html)

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
    policy = policy_situational(chosen)

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
        "buy_order": [{"id": i, "name": item_name(items, i)} for i in buy_order],
        "situational": [{"id": i, "name": item_name(items, i)} for i in situational],
        "policy": {
            key: [{"id": i, "name": item_name(items, i)} for i in ids]
            for key, ids in policy.items()
        },
        "skills": skills,
        "runes": runes,
        "matchups": matchups,
        "joint": {
            "u_joint": finished["u_joint"],
            "u45": finished["u45"],
            "u_total": best_bundle["u_total"],
        },
        "grid": grid,
    }
    return decision, silver, p0, p_avg, alpha


def make_itemset(cfg: dict, decision: dict) -> dict:
    def block(title: str, ids: list[str]) -> dict:
        return {
            "type": title,
            "hideIfSummonerSpell": "",
            "showIfSummonerSpell": "",
            "items": [{"id": item_id, "count": 1} for item_id in ids],
        }

    buy_ids = [row["id"] for row in decision["buy_order"]]
    start_ids = [row["id"] for row in decision["start"]]
    situ_ids = [row["id"] for row in decision["situational"]]
    policy = decision.get("policy") or {}
    return {
        "title": cfg["build_title"],
        "type": "custom",
        "map": "any",
        "mode": "any",
        "sortrank": 0,
        "startedFrom": "blank",
        "uid": str(uuid.uuid5(uuid.NAMESPACE_URL, "markov-kaisa-itemset")),
        "associatedChampions": [cfg["champion_id"]],
        "associatedMaps": cfg["associated_maps"],
        "preferredItemSlots": [],
        "blocks": [
            block("Starting", start_ids),
            block("Buy order (default)", buy_ids),
            block("Late swaps (replace item 4-6)", situ_ids),
            block("Vs tanks (replace late, not core)", [row["id"] for row in policy.get("vs_tanks") or []]),
            block("Vs burst (replace late, not core)", [row["id"] for row in policy.get("vs_burst") or []]),
            block("Vs AP (replace late, not core)", [row["id"] for row in policy.get("vs_ap") or []]),
            block("Wards", ["3340", "3364"]),
        ],
    }


def league_client_running() -> bool:
    try:
        import subprocess

        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq LeagueClient.exe"],
            capture_output=True,
            text=True,
            timeout=8,
        )
        return "LeagueClient.exe" in (result.stdout or "")
    except Exception:
        return False


def upsert_client_index(cfg: dict, itemset: dict) -> Path:
    index_path = Path(cfg["itemsets_index"])
    if index_path.exists():
        backup = index_path.with_suffix(".json.bak")
        backup.write_bytes(index_path.read_bytes())
        data = json.loads(index_path.read_text(encoding="utf-8"))
    else:
        data = {"accountId": 0, "itemSets": [], "timestamp": 0}

    sets = list(data.get("itemSets") or [])
    replaced = False
    for i, existing in enumerate(sets):
        if existing.get("uid") == itemset["uid"] or existing.get("title") == itemset["title"]:
            sets[i] = itemset
            replaced = True
            break
    if not replaced:
        sets.append(itemset)

    data["itemSets"] = sets
    data["timestamp"] = int(datetime.now(timezone.utc).timestamp() * 1000)
    index_path.write_text(json.dumps(data, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    return index_path


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def install_itemset(cfg: dict, itemset: dict) -> tuple[Path, Path]:
    dest_dir = Path(cfg["itemset_dir"])
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / cfg["itemset_filename"]
    dest.write_text(json.dumps(itemset, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    index_path = upsert_client_index(cfg, itemset)
    return dest, index_path


def print_summary(cfg: dict, decision: dict, dest: Path, index_path: Path) -> None:
    print()
    print("=" * 64)
    print(f"  {cfg['build_title']}")
    print(f"  {cfg['tier'].title()} / {cfg['region'].upper()} / Patch {cfg['patch']}")
    ctx = decision.get("context") or {}
    if ctx.get("alpha") is not None:
        print(f"  alpha={ctx['alpha']:g}  lambda={ctx.get('lambda')}  {ctx.get('hyper', {}).get('status', '')}")
    print("=" * 64)
    print("Start  : " + ", ".join(row["name"] for row in decision.get("start") or []))
    print(f"Item 1 : {decision['item1']['name']}")
    print(f"Boots  : {decision['boots']['name']}")
    print(f"Core   : {decision['core']['name']}")
    print(
        f"         tilde={decision['core']['tilde']*100:.2f}%  "
        f"U={decision['core']['U']*100:+.2f}  n={decision['core']['n']:.0f}"
    )
    print("Buy order:")
    for i, row in enumerate(decision["buy_order"], 1):
        print(f"  {i}. {row['name']}")
    validation = decision.get("validation") or {}
    print("\nDaily validation")
    if validation.get("status") == "waiting":
        print(f"  {validation.get('message')}")
    elif validation.get("status") == "compared":
        print(f"  Previous snapshot: {validation.get('previous_date')}  patch {validation.get('previous_patch')}")
        print(f"  Yesterday's core: {validation.get('previous_core')}")
        if validation.get("policy_changed"):
            print("  Policy changed: today's selected core is different.")
        for check in validation.get("checks") or []:
            y = check.get("yesterday") or {}
            t = check.get("today") or {}
            du = check.get("delta_U")
            du_txt = "n/a" if du is None else f"{du*100:+.2f}pp"
            yn = y.get("n")
            tn = t.get("n")
            yu = y.get("U")
            tu = t.get("U")
            yu_txt = "n/a" if yu is None else f"{yu*100:+.2f}"
            tu_txt = "n/a" if tu is None else f"{tu*100:+.2f}"
            print(
                f"  {check['label']:<6} {check['verdict']:<8} "
                f"U {yu_txt} -> {tu_txt}  dU={du_txt}  "
                f"n {yn if yn is not None else '-'} -> {tn if tn is not None else '-'}"
            )
        print(f"  {validation.get('note')}")
    policy = decision.get("policy") or {}
    if policy:
        print("\nMatchup branches")
        for key, rows in policy.items():
            print(f"  {key}: " + ", ".join(row["name"] for row in rows))
    if decision.get("matchups"):
        print(
            "Hard lanes: "
            + ", ".join(
                f"{row['champion']} {row['wr']*100:.1f}%"
                for row in decision["matchups"]
            )
        )
    print(f"\nChampion file:\n  {dest}")
    print(f"Client index:\n  {index_path}")
    if league_client_running():
        print("\nLeague is open. Close the client completely, then reopen it.")
        print("Otherwise the client may overwrite ItemSets.json on exit.")
    else:
        print("\nOpen League and select Kai'Sa. The set appears under Item Sets.")


LOLALYTICS_TIERS = (
    "iron",
    "bronze",
    "silver",
    "gold",
    "platinum",
    "emerald",
    "diamond",
    "master",
    "grandmaster",
    "challenger",
    "platinum_plus",
    "emerald_plus",
    "diamond_plus",
    "master_plus",
    "all",
)


def prior_for_tier(tier: str) -> tuple[str, str]:
    """Pair the chosen rank with a thicker nearby prior, not a fixed Silver setup."""
    name = (tier or "silver").lower()
    if name in {"iron", "bronze", "silver", "gold"}:
        return "emerald", "all"
    if name in {"platinum", "emerald", "platinum_plus"}:
        return "diamond", "all"
    if name in {"diamond", "emerald_plus", "diamond_plus"}:
        return "master", "all"
    return "all", "all"


def pick_tier_menu(default: str = "silver", out_path: Path | None = None) -> str | None:
    """Interactive up/down rank picker for the Windows launcher."""
    tiers = list(LOLALYTICS_TIERS)
    try:
        idx = tiers.index(default.lower())
    except ValueError:
        idx = tiers.index("silver")

    labels = {
        "iron": "Iron",
        "bronze": "Bronze",
        "silver": "Silver  (default)",
        "gold": "Gold",
        "platinum": "Platinum",
        "emerald": "Emerald",
        "diamond": "Diamond",
        "master": "Master",
        "grandmaster": "Grandmaster",
        "challenger": "Challenger",
        "platinum_plus": "Platinum+",
        "emerald_plus": "Emerald+",
        "diamond_plus": "Diamond+",
        "master_plus": "Master+",
        "all": "All ranks",
    }
    header = "  Use Up / Down to choose rank, Enter to confirm, Esc to cancel"
    menu_lines = 3 + len(tiers)
    stream = sys.stdout

    def draw() -> None:
        stream.write(f"\n{header}\n\n")
        for i, tier in enumerate(tiers):
            name = labels.get(tier, tier)
            if i == idx:
                stream.write(f"  >  {name}\n")
            else:
                stream.write(f"     {name}\n")
        stream.flush()

    def commit(chosen: str | None) -> str | None:
        if chosen and out_path is not None:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(chosen + "\n", encoding="utf-8")
        return chosen

    if not sys.stdin.isatty():
        print(default)
        return commit(default)

    try:
        import msvcrt
    except ImportError:
        print(default)
        return commit(default)

    first = True
    while True:
        if not first:
            stream.write(f"\033[{menu_lines}A")
        first = False
        draw()

        key = msvcrt.getch()
        if key in (b"\x00", b"\xe0"):
            arrow = msvcrt.getch()
            if arrow == b"H":
                idx = (idx - 1) % len(tiers)
            elif arrow == b"P":
                idx = (idx + 1) % len(tiers)
            continue
        if key in (b"\r", b"\n"):
            chosen = tiers[idx]
            stream.write(f"\n  Selected: {labels.get(chosen, chosen)}\n")
            stream.flush()
            return commit(chosen)
        if key == b"\x1b":
            stream.write("\n  Cancelled.\n")
            stream.flush()
            return commit(None)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate the Markov Kai'Sa item set.")
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
    cfg = load_config()
    args = parse_args()
    if args.pick_tier:
        chosen = pick_tier_menu(
            str(cfg.get("tier") or "silver"),
            out_path=OUTPUT_DIR / "selected_rank.txt",
        )
        return 0 if chosen else 1
    if args.tier:
        cfg["tier"] = args.tier
        print(f"Rank override from launcher: {args.tier}")
    cfg["prior_tier"], cfg["fallback_prior_region"] = prior_for_tier(cfg["tier"])
    print(f"Prior for late items: {cfg['prior_tier']} / {cfg['fallback_prior_region']}")
    try:
        items = load_items()
        decision, silver, p0, p_avg, alpha = build_decision(cfg, items)
        today = date.today().isoformat()
        selection = {
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
        previous = previous_calendar_entry(history, today, cfg.get("tier"))
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
        append_history(snapshot)
        dest, index_path = install_itemset(cfg, itemset)
        print_summary(cfg, decision, dest, index_path)
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
