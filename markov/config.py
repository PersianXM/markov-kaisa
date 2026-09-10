"""Configuration and League environment resolution."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
OUTPUT_DIR = ROOT / "output"
HISTORY_DIR = ROOT / "history"
HISTORY_PATH = HISTORY_DIR / "daily.jsonl"
BLACKLIST_PATH = HISTORY_DIR / "blacklist.json"

DDRAGON_TIMEOUT = 10
LOL_TIMEOUT = 12
UA = {
    "User-Agent": "MarkovLeague/2.0",
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
        "evolution_type": "kaisa",
    },
    "tristana": {
        "slug": "tristana",
        "name": "Tristana",
        "id": 18,
        "folder": "Tristana",
        "title": "Markov Tristana",
        "lane": "bottom",
        "evolution_type": None,
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


def detect_league_root(configured_path: Optional[str] = None) -> Path:
    """Auto-detects the League of Legends install root directory on Windows."""
    # 1. Check if configured path is valid
    if configured_path:
        p = Path(configured_path)
        if p.exists() and (p / "Config").exists():
            return p
        if p.exists() and (p / "LeagueClient.exe").exists():
            return p

    # 2. Check Windows Registry
    try:
        import winreg

        subkeys = (
            r"SOFTWARE\Riot Games, Inc\League of Legends",
            r"SOFTWARE\WOW6432Node\Riot Games, Inc\League of Legends",
            r"SOFTWARE\Riot Games\League of Legends",
            r"SOFTWARE\WOW6432Node\Riot Games\League of Legends",
        )
        for hkey in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            for subkey in subkeys:
                try:
                    with winreg.OpenKey(hkey, subkey) as key:
                        val, _ = winreg.QueryValueEx(key, "Location")
                        if val:
                            cand = Path(val)
                            if cand.exists() and (cand / "Config").exists():
                                return cand
                except OSError:
                    continue
    except Exception:
        pass

    # 3. Check common drive roots
    for drive in "CGDEFHIJKLMNOPQRSTUVWXYZ":
        cand = Path(f"{drive}:/Riot Games/League of Legends")
        if cand.exists() and (cand / "LeagueClient.exe").exists():
            return cand
        cand_alt = Path(f"{drive}:/Program Files/Riot Games/League of Legends")
        if cand_alt.exists() and (cand_alt / "LeagueClient.exe").exists():
            return cand_alt

    # Fallback to configured or typical default
    return Path(configured_path or r"C:\Riot Games\League of Legends")


def apply_champion(cfg: dict, champ_input: str | None = None) -> dict:
    """Applies champion metadata to the configuration dictionary."""
    slug = normalize_champion(champ_input or cfg.get("champion") or "kaisa")
    meta = SUPPORTED_CHAMPIONS.get(slug, SUPPORTED_CHAMPIONS["kaisa"])
    cfg["champion"] = meta["slug"]
    cfg["champion_name"] = meta["name"]
    cfg["champion_id"] = meta["id"]
    cfg["build_title"] = meta["title"]
    cfg["evolution_type"] = meta.get("evolution_type")
    if "lane" not in cfg or not cfg["lane"]:
        cfg["lane"] = meta["lane"]

    league_root = detect_league_root(cfg.get("league_root"))
    cfg["league_root"] = str(league_root)
    cfg["itemset_dir"] = str(league_root / "Config" / "Champions" / meta["folder"] / "Recommended")
    cfg["itemsets_index"] = str(league_root / "Config" / "ItemSets.json")
    return cfg


def load_config() -> dict:
    """Loads config.json from disk and applies auto-detection."""
    if CONFIG_PATH.exists():
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    else:
        cfg = {}
    return apply_champion(cfg)
