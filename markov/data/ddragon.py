"""Riot Data Dragon API client and metadata manager."""

from __future__ import annotations

import json
import time
import urllib.request
from typing import Any

from markov.config import DDRAGON_TIMEOUT, LOL_TIMEOUT, UA
from markov.data.cache import read_cache, write_cache

_ITEMS_CACHE: dict[int, str] | None = None
_ITEM_DETAILS_CACHE: dict[str, dict] | None = None
_CHAMPIONS_CACHE: dict[int, str] | None = None


def http_bytes(url: str, timeout: int = LOL_TIMEOUT, referer: str | None = None) -> bytes:
    """Fetches raw bytes from a URL with retry logic."""
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


def http_json(url: str, timeout: int = LOL_TIMEOUT, referer: str | None = None) -> Any:
    """Fetches and parses JSON from a URL."""
    return json.loads(http_bytes(url, timeout=timeout, referer=referer).decode("utf-8", "ignore"))


def http_text(url: str, timeout: int = LOL_TIMEOUT, referer: str | None = None) -> str:
    """Fetches text from a URL."""
    return http_bytes(url, timeout=timeout, referer=referer).decode("utf-8", "ignore")


def ddragon_patch() -> str:
    """Returns the current live patch version from Data Dragon."""
    versions = http_json(
        "https://ddragon.leagueoflegends.com/api/versions.json",
        timeout=DDRAGON_TIMEOUT,
    )
    return ".".join(str(versions[0]).split(".")[:2])


def load_item_details() -> dict[str, dict]:
    """Loads detailed DDragon item database with stats, gold, and component trees."""
    global _ITEM_DETAILS_CACHE
    if _ITEM_DETAILS_CACHE is not None:
        return _ITEM_DETAILS_CACHE

    cached = read_cache("cache_item_details.json")
    if cached and isinstance(cached, dict):
        _ITEM_DETAILS_CACHE = cached
        return _ITEM_DETAILS_CACHE

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
                details = {}
                for k, v in data.items():
                    details[str(k)] = {
                        "name": v.get("name", str(k)),
                        "gold": v.get("gold", {}),
                        "stats": v.get("stats", {}),
                        "from": v.get("from", []),
                        "into": v.get("into", []),
                        "tags": v.get("tags", []),
                    }
                _ITEM_DETAILS_CACHE = details
                write_cache("cache_item_details.json", details)
                return _ITEM_DETAILS_CACHE
            except Exception:
                continue
    except Exception:
        pass
    return {}


def load_items() -> dict[int, str]:
    """Loads DDragon item ID-to-name mapping with disk cache."""
    global _ITEMS_CACHE
    if _ITEMS_CACHE is not None:
        return _ITEMS_CACHE

    cached = read_cache("cache_items.json")
    if cached and isinstance(cached, dict):
        _ITEMS_CACHE = {int(k): str(v) for k, v in cached.items()}
        return _ITEMS_CACHE

    details = load_item_details()
    if details:
        _ITEMS_CACHE = {int(k): v["name"] for k, v in details.items() if k.isdigit()}
        write_cache("cache_items.json", _ITEMS_CACHE)
        return _ITEMS_CACHE

    return {}


def load_champions() -> dict[int, str]:
    """Loads DDragon champion ID-to-name mapping with disk cache."""
    global _CHAMPIONS_CACHE
    if _CHAMPIONS_CACHE is not None:
        return _CHAMPIONS_CACHE

    cached = read_cache("cache_champions.json")
    if cached and isinstance(cached, dict):
        _CHAMPIONS_CACHE = {int(k): str(v) for k, v in cached.items()}
        return _CHAMPIONS_CACHE

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
                write_cache("cache_champions.json", _CHAMPIONS_CACHE)
                return _CHAMPIONS_CACHE
            except Exception:
                continue
    except Exception:
        pass
    return {145: "Kai'Sa", 18: "Tristana"}


def item_name(items: dict[int, str], item_id: str | int) -> str:
    """Resolves an item ID to its display name."""
    try:
        return items.get(int(item_id), str(item_id))
    except ValueError:
        return str(item_id)


def path_name(items: dict[int, str], path: str) -> str:
    """Converts an underscore-separated item path to display names."""
    return " -> ".join(item_name(items, p) for p in path.split("_"))


def is_boots(items: dict[int, str], item_id: str | int) -> bool:
    """Checks whether an item ID corresponds to boots."""
    name = item_name(items, item_id).lower()
    return any(key in name for key in ("boot", "greaves", "treads", "gluttonous", "shoes"))
