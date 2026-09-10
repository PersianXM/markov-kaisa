"""League of Legends item set installer and index synchronizer."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def league_client_running() -> bool:
    """Checks if the League client process (LeagueClient.exe) is currently running."""
    try:
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
    index_path.parent.mkdir(parents=True, exist_ok=True)
    if index_path.exists():
        try:
            backup = index_path.with_suffix(".json.bak")
            backup.write_bytes(index_path.read_bytes())
            data = json.loads(index_path.read_text(encoding="utf-8"))
        except Exception:
            data = {"accountId": 0, "itemSets": [], "timestamp": 0}
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
    """Writes a dictionary as formatted JSON to a file path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def prune_stale_recommended(cfg: dict, itemset: dict, keep_name: str | None = None) -> list[Path]:
    """Removes old item set files matching the current set's UID or title in the champion directory."""
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
    """Writes an item set file to champion recommended folder and upserts client index."""
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
    """Removes item sets by UID from both the index and champion recommended folder."""
    if not uids:
        return
    index_path = Path(cfg["itemsets_index"])
    if index_path.exists():
        try:
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
        except Exception:
            pass

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
