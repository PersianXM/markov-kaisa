#!/usr/bin/env python3
"""Generate the Markov Kai'Sa item set from Lolalytics and install it.

This module downloads item set data, computes empirical Bayes estimates of winrates,
and builds optimal item paths for Kai'Sa based on the current patch statistics.
"""

from __future__ import annotations

import argparse
import http.client
import json
import math
import re
import sys
import time
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
DDRAGON_TIMEOUT = 10
LOL_TIMEOUT = 12
UA = {
    "User-Agent": "MarkovLeague/1.0",
    "Origin": "https://lolalytics.com",
    "Accept": "application/json,text/html,*/*",
}

SUPPORTED_CHAMPIONS: dict[str, dict] = {
    "kaisa": {
        "slug": "kaisa",
        "name": "Kai'Sa",
        "id": 145,
        "folder": "Kaisa",
        "title": "Markov Kai'Sa",
        "lane": "bottom",
    },
    "tristana": {
        "slug": "tristana",
        "name": "Tristana",
        "id": 18,
        "folder": "Tristana",
        "title": "Markov Tristana",
        "lane": "bottom",
    },
}

CHAMPION_ALIASES: dict[str, str] = {
    "kaisa": "kaisa",
    "kai'sa": "kaisa",
    "kais": "kaisa",
    "tristana": "tristana",
    "tristina": "tristana",
    "trist": "tristana",
}


def normalize_champion(name: str | None) -> str:
    """Normalizes a champion name input to a canonical slug."""
    if not name:
        return "kaisa"
    cleaned = re.sub(r"[^a-z0-9]", "", str(name).strip().lower())
    return CHAMPION_ALIASES.get(cleaned, CHAMPION_ALIASES.get(str(name).strip().lower(), "kaisa"))


def apply_champion(cfg: dict, champ_input: str | None = None) -> dict:
    """Applies champion metadata to the config dict."""
    slug = normalize_champion(champ_input or cfg.get("champion") or "kaisa")
    meta = SUPPORTED_CHAMPIONS.get(slug, SUPPORTED_CHAMPIONS["kaisa"])
    cfg["champion"] = meta["slug"]
    cfg["champion_name"] = meta["name"]
    cfg["champion_id"] = meta["id"]
    cfg["build_title"] = meta["title"]
    if "lane" not in cfg or not cfg["lane"]:
        cfg["lane"] = meta["lane"]
    if cfg.get("league_root"):
        cfg["itemset_dir"] = str(
            Path(cfg["league_root"]) / "Config" / "Champions" / meta["folder"] / "Recommended"
        )
    return cfg


def load_config() -> dict:
    """Loads config.json from disk."""
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def http_bytes(url: str, timeout: int = LOL_TIMEOUT, referer: str | None = None) -> bytes:
    """Fetches raw bytes from a URL with retries."""
    if "ddragon.leagueoflegends.com" in url:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept": "application/json,text/html,*/*",
        }
    else:
        headers = dict(UA)
        headers["Referer"] = referer or "https://lolalytics.com/"
    req = urllib.request.Request(url, headers=headers)
    last_err = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as exc:
            last_err = exc
            time.sleep(0.5)
    raise last_err or RuntimeError(f"Failed to fetch {url}")


def http_json(url: str, timeout: int = LOL_TIMEOUT, referer: str | None = None) -> dict:
    """Fetches and parses JSON from a URL."""
    return json.loads(http_bytes(url, timeout=timeout, referer=referer).decode("utf-8", "ignore"))


def http_text(url: str, timeout: int = LOL_TIMEOUT, referer: str | None = None) -> str:
    """Fetches text from a URL."""
    return http_bytes(url, timeout=timeout, referer=referer).decode("utf-8", "ignore")


_ITEMS_CACHE: dict[int, str] | None = None
_CHAMPIONS_CACHE: dict[int, str] | None = None


def load_items() -> dict[int, str]:
    """Loads DDragon item ID-to-name mapping with disk cache."""
    global _ITEMS_CACHE
    if _ITEMS_CACHE is not None:
        return _ITEMS_CACHE
    cache_file = OUTPUT_DIR / "cache_items.json"
    if cache_file.exists():
        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            _ITEMS_CACHE = {int(k): str(v) for k, v in data.items()}
            return _ITEMS_CACHE
        except Exception:
            pass
    try:
        versions = http_json(
            "https://ddragon.leagueoflegends.com/api/versions.json",
            timeout=10,
        )
        for ver in versions[:3]:
            try:
                data = http_json(
                    f"https://ddragon.leagueoflegends.com/cdn/{ver}/data/en_US/item.json",
                    timeout=20,
                )["data"]
                _ITEMS_CACHE = {int(k): v["name"] for k, v in data.items()}
                cache_file.parent.mkdir(parents=True, exist_ok=True)
                cache_file.write_text(json.dumps(_ITEMS_CACHE, ensure_ascii=False), encoding="utf-8")
                return _ITEMS_CACHE
            except Exception:
                continue
    except Exception:
        pass
    return {}


def load_champions() -> dict[int, str]:
    """Loads DDragon champion ID-to-name mapping with disk cache."""
    global _CHAMPIONS_CACHE
    if _CHAMPIONS_CACHE is not None:
        return _CHAMPIONS_CACHE
    cache_file = OUTPUT_DIR / "cache_champions.json"
    if cache_file.exists():
        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            _CHAMPIONS_CACHE = {int(k): str(v) for k, v in data.items()}
            return _CHAMPIONS_CACHE
        except Exception:
            pass
    try:
        versions = http_json(
            "https://ddragon.leagueoflegends.com/api/versions.json",
            timeout=10,
        )
        for ver in versions[:3]:
            try:
                data = http_json(
                    f"https://ddragon.leagueoflegends.com/cdn/{ver}/data/en_US/champion.json",
                    timeout=20,
                )["data"]
                _CHAMPIONS_CACHE = {int(v["key"]): v["name"] for v in data.values()}
                cache_file.parent.mkdir(parents=True, exist_ok=True)
                cache_file.write_text(json.dumps(_CHAMPIONS_CACHE, ensure_ascii=False), encoding="utf-8")
                return _CHAMPIONS_CACHE
            except Exception:
                continue
    except Exception:
        pass
    return {145: "Kai'Sa", 18: "Tristana"}


def item_name(items: dict[int, str], item_id: str) -> str:
    """Resolves an item ID to its display name."""
    try:
        return items.get(int(item_id), item_id)
    except ValueError:
        return item_id


def path_name(items: dict[int, str], path: str) -> str:
    """Converts an underscore-separated item path to display names."""
    return " -> ".join(item_name(items, p) for p in path.split("_"))


def is_boots(items: dict[int, str], item_id: str) -> bool:
    """Checks whether an item ID corresponds to boots."""
    name = item_name(items, item_id).lower()
    return any(
        key in name
        for key in ("boot", "greaves", "treads", "gluttonous")
    )


def ddragon_patch() -> str:
    """Returns the current live patch version from Data Dragon."""
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
    """Scrapes the champion's baseline winrate and average winrate from Lolalytics."""
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
    """Scores an item path computing shrunk WR, delta, CI, and U.

    U = delta - lam * CI
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


def rank_paths(
    agg: dict,
    p0: float,
    p_avg: float,
    alpha: float,
    n_min: float,
    lam: float = 0.55,
) -> list[tuple[str, dict]]:
    """Ranks all paths at a given depth by U, filtering by n_min."""
    rows: list[tuple[str, dict]] = []
    for path, (games, wins) in agg.items():
        s = score(wins, games, p0, p_avg, alpha, n_min, lam)
        if s and not s["reject"] and s["U"] is not None:
            rows.append((path, s))
    rows.sort(key=lambda row: row[1]["U"], reverse=True)
    return rows


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
    """Shrink n_min when the live patch sample is still thin."""
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


def most_common_extension(
    agg: dict,
    prefix: str,
    exclude: set[str] | None = None,
) -> dict | None:
    """Finds the most popular next item after a prefix path."""
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


def lookup(agg: dict, key: str) -> tuple[float, float] | None:
    """Looks up a path key in an aggregated dict, returning (games, wins) or None."""
    if key not in agg:
        return None
    return agg[key]


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


def load_history() -> list[dict]:
    """Loads the daily validation history from the JSONL file."""
    if not HISTORY_PATH.exists():
        return []
    rows = []
    for line in HISTORY_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def previous_calendar_entry(
    history: list[dict],
    today: str,
    tier: str | None = None,
    champion: str | None = None,
) -> dict | None:
    """Finds the most recent history entry before today, optionally filtered by tier/champion."""
    prior = [
        row
        for row in history
        if row.get("date")
        and row["date"] < today
        and (tier is None or row.get("tier") == tier)
        and (champion is None or row.get("champion", "kaisa") == champion)
    ]
    return prior[-1] if prior else None


def verdict_from_delta(delta_u: float | None) -> str:
    """Maps a delta-U value to a human-readable verdict string."""
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
    """Compares a metric between yesterday's and today's score dictionaries."""
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
    """Rescores a previous day's selected paths against current data."""
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
    """Validates today's build against the previous day's snapshot."""
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
    """Appends a snapshot entry to the daily history JSONL file."""
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    with HISTORY_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def load_blacklist() -> dict:
    """Loads the core blacklist from disk."""
    if not BLACKLIST_PATH.exists():
        return {"cores": []}
    try:
        return json.loads(BLACKLIST_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"cores": []}


def save_blacklist(data: dict) -> None:
    """Saves the core blacklist to disk."""
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    BLACKLIST_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def active_blacklist(today: str) -> set[str]:
    """Returns the set of currently blacklisted core paths."""
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
    """Checks for consecutive faded verdicts and blacklists the core if warranted."""
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
    try:
        return http_text(url, timeout=15, referer=url)
    except Exception:
        return ""


def parse_start_sets(html: str) -> list[tuple[list[str], float, float]]:
    """Parses starting item sets from Lolalytics HTML using regex.

    Args:
        html: The HTML content to parse.

    Returns:
        A list of tuples containing item IDs, game count, and win rate.
    """
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
    """Selects the best starting items by scoring parsed start sets.

    Args:
        html: The HTML content to parse.
        p0: Baseline win rate.
        p_avg: Average win rate.
        alpha: Smoothing hyperparameter.
        lam: Regularization hyperparameter.
        n_min: Minimum games threshold.

    Returns:
        A tuple of selected item IDs and their score dictionary.
    """
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
VS_TANKS = ("3036", "3302", "3153")
VS_BURST = ("3026", "3156", "3139")
VS_AP = ("3102", "3156", "3157")
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


def parse_skill_order(
    html: str,
    p0: float,
    p_avg: float,
    alpha: float,
    lam: float,
    n_min: float = 2000,
) -> dict | None:
    """Parses and scores skill level-up orders from HTML.

    Args:
        html: The HTML content to parse.
        p0: Baseline win rate.
        p_avg: Average win rate.
        alpha: Smoothing hyperparameter.
        lam: Regularization hyperparameter.
        n_min: Minimum games threshold.

    Returns:
        A dictionary with the best skill order and its score, or None.
    """
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
    """Parses the most common rune page from HTML.

    Args:
        html: The HTML content to parse.

    Returns:
        A dictionary with rune IDs, names, keystone, and titles, or None.
    """
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
    """Fetches counter/matchup data from Lolalytics API.

    Args:
        cfg: Configuration dictionary with request parameters.

    Returns:
        The JSON response from the API.
    """
    url = (
        "https://a1.lolalytics.com/mega/?ep=counter&v=1"
        f"&patch={cfg['patch']}&c={cfg['champion']}&lane={cfg['lane']}"
        f"&tier={cfg['tier']}&queue={cfg['queue']}&region={cfg['region']}"
    )
    return http_json(url)


def champion_tags(cid: int, default_lane: str | None = None) -> set[str]:
    """Returns archetype tags for a champion ID.

    Args:
        cid: The champion ID.
        default_lane: Optional default lane if champion is not hardcoded.

    Returns:
        A set of tag strings.
    """
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
    """Returns situational item IDs appropriate for given archetype tags.

    Args:
        tags: Set of archetype tags.
        chosen: Set of item IDs already chosen.
        limit: Maximum number of item IDs to return.

    Returns:
        A list of item IDs.
    """
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
    """Shortens a champion display name for compact branch labels.

    Args:
        name: The full champion name.

    Returns:
        A shortened version of the name.
    """
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
) -> tuple[list[dict], list[dict]]:
    """Build pre-game late-item branches from live Lolalytics counters."""
    if payload is None:
        try:
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
        # Fall back to lowest Kai'Sa winrate lanes with enough games.
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

    for key, title, prefs in (
        ("vs_tanks", "Vs tanks (late)", VS_TANKS),
        ("vs_burst", "Vs burst (late)", VS_BURST),
        ("vs_ap", "Vs AP (late)", VS_AP),
    ):
        ids = [iid for iid in prefs if iid not in chosen][:2]
        branches.append(
            {
                "key": key,
                "title": title,
                "ids": ids,
                "source": "archetype",
                "champions": [],
            }
        )
    return branches, weak_rows


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
    """Lists and scores boot options compatible with the first two core items.

    Args:
        items: Dictionary mapping item IDs to names.
        itemsets: Dictionary of item set frequencies.
        first_two: Prefix string of the first two item IDs.
        p0: Baseline win rate.
        p_avg: Average win rate.
        alpha: Smoothing hyperparameter.
        lam: Regularization hyperparameter.
        n_min: Minimum games threshold.
        limit: Maximum number of boot candidates to return.

    Returns:
        A list of dictionaries containing boot IDs and their scores.
    """
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
    """Lists candidate 6th items by iteratively picking the best remaining.

    Args:
        silver_sets: Dictionary of current patch item set frequencies.
        prior_sets: Dictionary of previous patch item set frequencies.
        core: The core item prefix string.
        item4: The 4th item ID.
        item5: The 5th item ID.
        owned: Set of currently owned item IDs.
        p0: Baseline win rate.
        p_avg: Average win rate.
        alpha: Smoothing hyperparameter.
        n_min: Minimum games threshold.
        lam: Regularization hyperparameter.
        limit: Maximum number of candidates to return.

    Returns:
        A list of dictionaries containing 6th item candidates and their scores.
    """
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
    """Searches over all combinations of boots, items 4-6 to find the best joint finish.
    
    This function explores the Cartesian product of the top candidates for boots, 4th, 
    and 5th items to construct possible late-game paths. For each path, it selects the best
    6th item and scores the entire finish based on utility sums, returning the optimal combination.

    Args:
        items: Dictionary mapping item IDs to names.
        silver: Current patch item sets.
        prior: Previous patch item sets.
        core: Core items prefix string.
        pair: First two items prefix string.
        p0: Baseline win rate.
        p_avg: Average win rate.
        alpha: Smoothing hyperparameter.
        lam: Regularization hyperparameter.
        cfg: Configuration dictionary containing minimum game thresholds.

    Returns:
        A dictionary describing the best joint finish path and its overall score.
    """
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


def compute_hyper_grid(silver: dict, p0: float, p_avg: float, cfg: dict) -> dict:
    """Evaluates the top core across a grid of (alpha, lambda) hyperparameters.

    Args:
        silver: Dictionary of item set frequencies.
        p0: Baseline win rate.
        p_avg: Average win rate.
        cfg: Configuration dictionary with minimum core threshold.

    Returns:
        A dictionary mapping hyperparameter combinations to their best core.
    """
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
    """Selects hyperparameters by modal-core consensus across the grid.

    Args:
        grid: Dictionary from compute_hyper_grid.
        default_a: Default alpha value.
        default_l: Default lambda value.

    Returns:
        A tuple of chosen alpha, lambda, and metadata dict.
    """
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
    """Selects alpha and lambda using holdout validation or grid consensus.

    Args:
        history: List of historical run dictionaries.
        today: Current date string.
        silver: Current item sets.
        p0: Baseline win rate.
        p_avg: Average win rate.
        cfg: Configuration dictionary.
        grid: Evaluated hyperparameter grid.

    Returns:
        A tuple of selected alpha, lambda, and metadata dict.
    """
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
    """Legacy boot selection: picks the highest-U boots for a given first-two pair.

    Args:
        items: Dictionary mapping item IDs to names.
        itemsets: Dictionary of item set frequencies.
        first_two: Prefix string of the first two item IDs.
        p0: Baseline win rate.
        p_avg: Average win rate.
        alpha: Smoothing hyperparameter.

    Returns:
        The selected boot item ID string.
    """
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
    """Computes U for a late item given its hierarchical tilde estimate.

    Args:
        tilde: Hierarchical win rate estimate.
        games: Number of games.
        p_avg: Average win rate.
        alpha: Smoothing hyperparameter.
        lam: Regularization hyperparameter.

    Returns:
        The late utility score.
    """
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
    """Lists and ranks late items extending a prefix path using hierarchical tilde.

    Args:
        silver_agg: Current patch aggregated items.
        prior_agg: Previous patch aggregated items.
        prefix: Prefix string of already built items.
        p0: Baseline win rate.
        p_avg: Average win rate.
        alpha: Smoothing hyperparameter.
        n_min: Minimum games threshold.
        exclude: Set of item IDs to exclude.
        lam: Regularization hyperparameter.
        limit: Maximum number of items to return.

    Returns:
        A list of dictionaries with item IDs and scores.
    """
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
    """Picks the single best late item extending a prefix path.

    Args:
        silver_agg: Current patch aggregated items.
        prior_agg: Previous patch aggregated items.
        prefix: Prefix string of already built items.
        p0: Baseline win rate.
        p_avg: Average win rate.
        alpha: Smoothing hyperparameter.
        n_min: Minimum games threshold.
        exclude: Set of item IDs to exclude.
        lam: Regularization hyperparameter.

    Returns:
        A dictionary with the chosen item ID and score, or None.
    """
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
    """Selects items 4 and 5 sequentially after the core.

    Args:
        silver_sets: Current patch item sets.
        prior_sets: Previous patch item sets.
        core: The core items prefix string.
        p0: Baseline win rate.
        p_avg: Average win rate.
        alpha: Smoothing hyperparameter.
        n_min4: Minimum games threshold for 4th item.
        n_min5: Minimum games threshold for 5th item.

    Returns:
        A tuple of the chosen 4th and 5th items as dicts, or Nones.
    """
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
    """Picks the 6th legendary item using exact data or late-presence fallback.

    Args:
        silver_sets: Current patch item sets.
        prior_sets: Previous patch item sets.
        core: The core items prefix string.
        item4: The 4th item ID string.
        item5: The 5th item ID string.
        owned: Set of currently owned item IDs.
        p0: Baseline win rate.
        p_avg: Average win rate.
        alpha: Smoothing hyperparameter.
        n_min: Minimum games threshold.
        lam: Regularization hyperparameter.

    Returns:
        A dictionary containing the chosen 6th item and its score, or None.
    """
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
    """Main decision pipeline: fetches data, scores paths, selects the full 7-slot build.
    
    This function orchestrates the entire build generation process. It fetches live data, 
    evaluates hyperparameter grids to find optimal regularization, and incrementally scores
    build paths from item 1 to 6 (plus boots) to output the best joint build.

    Args:
        cfg: Configuration dictionary containing thresholds and parameters.
        items: Dictionary mapping item IDs to names.

    Returns:
        A tuple containing the final run dictionary, live build decisions, 
        and values for alpha, lambda, and p0.
    """
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
        cfg, champions, chosen, payload=counter_payload
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
        # Backward-compatible map for older summary keys.
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
    )
    return decision, silver, p0, p_avg, alpha


def gem_uid(slot: int, champ_slug: str = "kaisa") -> str:
    """Generates a deterministic UUID for a gem hunter item set slot."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"markov-{champ_slug}-gem-{slot}"))


def core_identity(path: str) -> frozenset[str]:
    """Returns a frozenset of item IDs from a path, ignoring order."""
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
    """Builds the 7-slot buy order and situational items from a core + finished dict."""
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
) -> dict:
    """Builds a compact decision dict for a gem path (mirrors the main decision format)."""
    buy_ids, situ_ids = buy_plan(core, finished)
    return {
        "set_title": title,
        "set_uid_key": f"markov-kaisa-gem-{slot}",
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
    }


def fetch_gem_prior(cfg: dict, fallback: dict) -> tuple[dict, str, str]:
    """Thicker sample for discovering underpicked cores the chosen rank barely plays."""
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
    """Scores a core path for Gem Hunter using hierarchical tilde from a thicker prior."""
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
            cfg, champions, set(buy_ids), payload=counter_payload
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
            )
        )
        print(
            f"    {title}: "
            + " -> ".join(item_name(items, iid) for iid in buy_ids)
        )
    if not gems:
        print("  no underpicked cores cleared the gem floors")
    return gems


def make_itemset(
    cfg: dict,
    decision: dict,
    title: str | None = None,
    uid_key: str | None = None,
    sortrank: int = 0,
) -> dict:
    """Constructs a League client item set JSON payload from a decision dict."""
    def block(block_title: str, ids: list[str]) -> dict:
        return {
            "type": block_title,
            "hideIfSummonerSpell": "",
            "showIfSummonerSpell": "",
            "items": [{"id": item_id, "count": 1} for item_id in ids],
        }

    champ_slug = cfg.get("champion", "kaisa")
    actual_uid_key = uid_key or f"markov-{champ_slug}-itemset"
    buy_ids = [row["id"] for row in decision["buy_order"]]
    start_ids = [row["id"] for row in decision["start"]]
    situ_ids = [row["id"] for row in decision["situational"]]
    branches = decision.get("policy_branches") or []
    blocks = [
        block("Starting", start_ids),
        block("Buy order (default)", buy_ids),
        block("Late swaps (replace item 4-6)", situ_ids),
    ]
    for branch in branches:
        ids = [row["id"] for row in branch.get("items") or []]
        if ids:
            blocks.append(block(branch["title"], ids))
    blocks.append(block("Wards", ["3340", "3364"]))
    return {
        "title": title or decision.get("set_title") or cfg["build_title"],
        "type": "custom",
        "map": "any",
        "mode": "any",
        "sortrank": sortrank,
        "startedFrom": "blank",
        "uid": str(uuid.uuid5(uuid.NAMESPACE_URL, actual_uid_key)),
        "associatedChampions": [cfg["champion_id"]],
        "associatedMaps": cfg["associated_maps"],
        "preferredItemSlots": [],
        "blocks": blocks,
    }


def league_client_running() -> bool:
    """Checks if the League client process is currently running."""
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
    """Inserts or updates an item set in the client's ItemSets.json index."""
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
    """Writes a dict as formatted JSON to a file path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def prune_stale_recommended(cfg: dict, itemset: dict, keep_name: str | None = None) -> list[Path]:
    """Removes old item set files that match the current set's UID or title."""
    dest_dir = Path(cfg["itemset_dir"])
    keep = {Path(cfg["itemset_filename"]).name, "RIOT_ItemSet_GemHunter_1.json", "RIOT_ItemSet_GemHunter_2.json"}
    if keep_name:
        keep.add(Path(keep_name).name)
    uid = itemset.get("uid")
    title = itemset.get("title")
    removed: list[Path] = []
    if not dest_dir.is_dir():
        return removed
    for path in dest_dir.glob("*.json"):
        if path.name in keep:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("uid") == uid or data.get("title") == title:
            path.unlink()
            removed.append(path)
    return removed


def install_itemset(
    cfg: dict,
    itemset: dict,
    filename: str | None = None,
) -> tuple[Path, Path]:
    """Writes an item set file and upserts it into the client index."""
    dest_dir = Path(cfg["itemset_dir"])
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / (filename or cfg["itemset_filename"])
    dest.write_text(json.dumps(itemset, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    stale = prune_stale_recommended(cfg, itemset, keep_name=dest.name)
    for path in stale:
        print(f"Removed leftover item set: {path}")
    index_path = upsert_client_index(cfg, itemset)
    return dest, index_path


def drop_itemsets(cfg: dict, uids: set[str]) -> None:
    """Removes item sets by UID from both the index and champion directory."""
    if not uids:
        return
    index_path = Path(cfg["itemsets_index"])
    if index_path.exists():
        data = json.loads(index_path.read_text(encoding="utf-8"))
        before = list(data.get("itemSets") or [])
        kept = [row for row in before if row.get("uid") not in uids]
        if len(kept) != len(before):
            data["itemSets"] = kept
            data["timestamp"] = int(datetime.now(timezone.utc).timestamp() * 1000)
            index_path.write_text(
                json.dumps(data, separators=(",", ":"), ensure_ascii=False),
                encoding="utf-8",
            )
    dest_dir = Path(cfg["itemset_dir"])
    if not dest_dir.is_dir():
        return
    for path in dest_dir.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("uid") in uids:
            path.unlink()
            print(f"Removed leftover item set: {path}")


def print_summary(cfg: dict, decision: dict, dest: Path, index_path: Path) -> None:
    """Prints a formatted summary of the build decision to stdout."""
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
    policy_branches = decision.get("policy_branches") or []
    if policy_branches:
        print("\nMatchup branches (pre-built late swaps)")
        for branch in policy_branches:
            champs = branch.get("champions") or []
            suffix = f"  [{', '.join(champs)}]" if champs else ""
            print(
                f"  {branch['title']}: "
                + ", ".join(row["name"] for row in branch.get("items") or [])
                + suffix
            )
    elif decision.get("policy"):
        print("\nMatchup branches")
        for key, rows in (decision.get("policy") or {}).items():
            print(f"  {key}: " + ", ".join(row["name"] for row in rows))
    if decision.get("matchups"):
        print(
            "Hard lanes: "
            + ", ".join(
                f"{row['champion']} {row['wr']*100:.1f}%"
                for row in decision["matchups"]
            )
        )
    gems = decision.get("gems") or []
    if gems:
        print("\nGem Hunter")
        for gem in gems:
            g = gem.get("gem") or {}
            share = g.get("share")
            share_txt = "n/a" if share is None else f"{share*100:.1f}%"
            gu = (gem.get("core") or {}).get("U")
            tu = "n/a" if gu is None else f"{gu*100:+.2f}"
            gg = g.get("G")
            gg_txt = "n/a" if gg is None else f"{gg*100:+.2f}"
            print(f"  {gem.get('set_title')}")
            print(
                f"    core {(gem.get('core') or {}).get('name')}  "
                f"U={tu}  G={gg_txt}  share={share_txt}  "
                f"n={(gem.get('core') or {}).get('n')}"
            )
            print(
                "    buy: "
                + " -> ".join(row["name"] for row in gem.get("buy_order") or [])
            )
    champ_name = cfg.get("champion_name") or cfg.get("champion", "Kai'Sa").title()
    print(f"\nChampion file:\n  {dest}")
    print(f"Client index:\n  {index_path}")
    if league_client_running():
        print("\nLeague is open. Close the client completely, then reopen it.")
        print("Otherwise the client may overwrite ItemSets.json on exit.")
    else:
        print(f"\nOpen League and select {champ_name}. The sets appear under Item Sets.")
        print(f"{cfg['build_title']} is the U path. Gem Hunter sets are named by core winrate.")


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


def pick_champion_menu(default: str = "kaisa", out_path: Path | None = None) -> str | None:
    """Interactive up/down champion picker for the Windows launcher."""
    champions = ["kaisa", "tristana"]
    normalized = normalize_champion(default)
    try:
        idx = champions.index(normalized)
    except ValueError:
        idx = 0

    labels = {
        "kaisa": "Kai'Sa  (default)",
        "tristana": "Tristana",
    }
    coral_bg = "\033[48;2;232;90;60m"
    ink = "\033[38;2;26;26;26m"
    coral = "\033[38;2;232;90;60m"
    dim = "\033[38;2;120;112;100m"
    reset = "\033[0m"
    header = "  Up / Down  =  move     Enter  =  pick     Esc  =  cancel"
    menu_lines = 4 + len(champions)
    stream = sys.stdout

    def draw() -> None:
        stream.write(f"\n{coral}  pick a champion brick{reset}\n")
        stream.write(f"{dim}{header}{reset}\n\n")
        for i, c in enumerate(champions):
            name = f"{labels.get(c, c):<22}"
            if i == idx:
                stream.write(f"  {coral_bg}{ink}  #  {name}{reset}\n")
            else:
                stream.write(f"  {dim}  .  {name}{reset}\n")
        stream.flush()

    def commit(chosen: str | None) -> str | None:
        if chosen and out_path is not None:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(chosen + "\n", encoding="utf-8")
        return chosen

    if not sys.stdin.isatty():
        print(normalized)
        return commit(normalized)

    try:
        import msvcrt
    except ImportError:
        print(normalized)
        return commit(normalized)

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
                idx = (idx - 1) % len(champions)
            elif arrow == b"P":
                idx = (idx + 1) % len(champions)
            continue
        if key in (b"\r", b"\n"):
            chosen = champions[idx]
            stream.write(f"\n  {coral}#{reset}  selected  {labels.get(chosen, chosen)}\n")
            stream.flush()
            return commit(chosen)
        if key == b"\x1b":
            stream.write("\n  Cancelled.\n")
            stream.flush()
            return commit(None)


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
    coral_bg = "\033[48;2;232;90;60m"
    ink = "\033[38;2;26;26;26m"
    cream = "\033[38;2;246;241;231m"
    coral = "\033[38;2;232;90;60m"
    dim = "\033[38;2;120;112;100m"
    reset = "\033[0m"
    header = "  Up / Down  =  move     Enter  =  pick     Esc  =  cancel"
    menu_lines = 4 + len(tiers)
    stream = sys.stdout

    def draw() -> None:
        stream.write(f"\n{coral}  pick a rank brick{reset}\n")
        stream.write(f"{dim}{header}{reset}\n\n")
        for i, tier in enumerate(tiers):
            name = f"{labels.get(tier, tier):<22}"
            if i == idx:
                stream.write(f"  {coral_bg}{ink}  #  {name}{reset}\n")
            else:
                stream.write(f"  {dim}  .  {name}{reset}\n")
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
            stream.write(f"\n  {coral}#{reset}  selected  {labels.get(chosen, chosen)}\n")
            stream.flush()
            return commit(chosen)
        if key == b"\x1b":
            stream.write("\n  Cancelled.\n")
            stream.flush()
            return commit(None)


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
    """Entry point: loads config, runs the decision pipeline, installs item sets."""
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
        decision, silver, p0, p_avg, alpha = build_decision(cfg, items)
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
