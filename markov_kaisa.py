#!/usr/bin/env python3
"""Generate the Markov Kai'Sa item set from Lolalytics and install it."""

from __future__ import annotations

import json
import math
import re
import sys
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
OUTPUT_DIR = ROOT / "output"
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


def actually_built(itemsets: dict, t: int, boot: bool = False) -> dict[str, tuple[float, float]]:
    prefix = "itemBootSet" if boot else "itemSet"
    max_i = 6 if boot else 5
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
        "U": None if games < n_min else delta - 0.55 * risk,
        "n": games,
        "reject": games < n_min,
    }


def rank_paths(agg: dict, p0: float, p_avg: float, alpha: float, n_min: float) -> list[tuple[str, dict]]:
    rows: list[tuple[str, dict]] = []
    for path, (games, wins) in agg.items():
        s = score(wins, games, p0, p_avg, alpha, n_min)
        if s and not s["reject"] and s["U"] is not None:
            rows.append((path, s))
    rows.sort(key=lambda row: row[1]["U"], reverse=True)
    return rows


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


def choose_start_items() -> list[str]:
    # Highest-win Kaisa ADC start on current patch family.
    return ["1086", "2003"]


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


def choose_late_items(
    silver_sets: dict,
    prior_sets: dict,
    core: str,
    p0: float,
    alpha: float,
    n_min: float,
) -> tuple[str | None, str | None]:
    silver4 = actually_built(silver_sets, 4)
    prior4 = actually_built(prior_sets, 4)
    silver5 = actually_built(silver_sets, 5)
    prior5 = actually_built(prior_sets, 5)

    item4 = None
    best4 = -1.0
    for path, (games, wins) in silver4.items():
        if not path.startswith(core + "_") or games < n_min:
            continue
        tilde = hierarchical_tilde((games, wins), lookup(prior4, path), p0, alpha)
        if tilde is not None and tilde > best4:
            best4 = tilde
            item4 = path.split("_")[-1]

    item5 = None
    best5 = -1.0
    prefix = core + (f"_{item4}" if item4 else "")
    source = silver5 if item4 else silver5
    prior_src = prior5
    for path, (games, wins) in source.items():
        if not path.startswith(prefix + "_") or games < max(80, n_min // 2):
            continue
        tilde = hierarchical_tilde((games, wins), lookup(prior_src, path), p0, alpha)
        last = path.split("_")[-1]
        if last == item4:
            continue
        if tilde is not None and tilde > best5:
            best5 = tilde
            item5 = last
    return item4, item5


def build_decision(cfg: dict, items: dict[int, str]) -> dict:
    cfg["patch"] = resolve_live_patch(cfg)
    print(f"Fetching Silver {cfg['region'].upper()} item sets...")
    silver = fetch_itemsets(cfg, cfg["tier"], cfg["region"])
    print(f"Fetching {cfg['prior_tier'].title()} {cfg['prior_region'].upper()} prior...")
    try:
        prior = fetch_itemsets(cfg, cfg["prior_tier"], cfg["prior_region"])
    except Exception as exc:
        print(f"Primary prior failed ({exc}); using Global Emerald.")
        prior = fetch_itemsets(cfg, cfg["prior_tier"], cfg["fallback_prior_region"])

    print("Fetching champion baseline...")
    p0, p_avg = fetch_baseline(cfg)
    alpha = float(cfg["alpha_rank"])
    print(f"Baseline p0={p0:.4f}  p_avg={p_avg:.4f}")

    item1_rows = rank_paths(
        actually_built(silver, 1), p0, p_avg, alpha, cfg["n_min_item1"]
    )
    if not item1_rows:
        raise RuntimeError("No reliable Item 1 candidates.")
    item1 = item1_rows[0][0]

    item2_all = rank_paths(
        actually_built(silver, 2), p0, p_avg, alpha, cfg["n_min_item2"]
    )
    item2_rows = [row for row in item2_all if row[0].startswith(item1 + "_")]
    if not item2_rows:
        raise RuntimeError("No reliable Item 2 candidates.")
    pair = item2_rows[0][0]

    core_all = rank_paths(
        actually_built(silver, 3), p0, p_avg, alpha, cfg["n_min_core"]
    )
    greedy = [row for row in core_all if row[0].startswith(pair + "_")]
    if not greedy:
        raise RuntimeError("No reliable core candidates.")
    greedy_core = greedy[0][0]
    global_core = core_all[0][0]
    selected_core = global_core
    core_score = core_all[0][1]

    boots = choose_boots(items, silver, pair, p0, p_avg, alpha)
    item4, item5 = choose_late_items(
        silver, prior, selected_core, p0, alpha, cfg["n_min_late"]
    )
    if not item4:
        item4 = "3157"
    if not item5:
        item5 = "3089"

    start = choose_start_items()
    core_ids = selected_core.split("_")
    buy_order = [core_ids[0], boots, core_ids[1], core_ids[2], item4, item5]
    situational = []
    for extra in ("3157", "2510", "3006", "3008", "4645", "3302", "3026", "3036"):
        if extra not in buy_order and extra not in situational:
            situational.append(extra)

    decision = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "context": {
            "tier": cfg["tier"],
            "region": cfg["region"],
            "patch": cfg["patch"],
            "p0": p0,
            "p_avg": p_avg,
        },
        "item1": {"id": item1, "name": item_name(items, item1), **item1_rows[0][1]},
        "item2": {"id": pair.split("_")[1], "path": pair, "name": path_name(items, pair), **item2_rows[0][1]},
        "core": {
            "path": selected_core,
            "name": path_name(items, selected_core),
            "greedy": path_name(items, greedy_core),
            **{k: core_score[k] for k in ("wr", "tilde", "delta", "U", "n")},
        },
        "boots": {"id": boots, "name": item_name(items, boots)},
        "item4": {"id": item4, "name": item_name(items, item4)},
        "item5": {"id": item5, "name": item_name(items, item5)},
        "start": [{"id": i, "name": item_name(items, i)} for i in start],
        "buy_order": [{"id": i, "name": item_name(items, i)} for i in buy_order],
        "situational": [{"id": i, "name": item_name(items, i)} for i in situational],
    }
    return decision


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
            block("Markov Core + Boots", buy_ids),
            block("Situational", situ_ids),
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
    print("=" * 64)
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
    print(f"\nChampion file:\n  {dest}")
    print(f"Client index:\n  {index_path}")
    if league_client_running():
        print("\nLeague is open. Close the client completely, then reopen it.")
        print("Otherwise the client may overwrite ItemSets.json on exit.")
    else:
        print("\nOpen League and select Kai'Sa. The set appears under Item Sets.")


def main() -> int:
    cfg = load_config()
    try:
        items = load_items()
        decision = build_decision(cfg, items)
        itemset = make_itemset(cfg, decision)
        OUTPUT_DIR.mkdir(exist_ok=True)
        write_json(OUTPUT_DIR / "decision.json", decision)
        write_json(OUTPUT_DIR / cfg["itemset_filename"], itemset)
        dest, index_path = install_itemset(cfg, itemset)
        print_summary(cfg, decision, dest, index_path)
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
