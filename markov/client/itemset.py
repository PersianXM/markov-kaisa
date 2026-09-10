"""Riot League Client ItemSet JSON format builder."""

from __future__ import annotations

import uuid
from typing import Any


def make_itemset(
    cfg: dict,
    decision: dict,
    title: str | None = None,
    uid_key: str | None = None,
    sortrank: int = 0,
) -> dict:
    """Constructs a standard League client item set JSON payload with early components and evolution blocks."""

    def block(block_title: str, ids: list[str]) -> dict:
        return {
            "type": block_title,
            "hideIfSummonerSpell": "",
            "showIfSummonerSpell": "",
            "items": [{"id": str(item_id), "count": 1} for item_id in ids],
        }

    champ_slug = cfg.get("champion", "kaisa")
    actual_uid_key = uid_key or f"markov-{champ_slug}-itemset"
    buy_ids = [row["id"] for row in decision.get("buy_order") or []]
    start_ids = [row["id"] for row in decision.get("start") or []]
    situ_ids = [row["id"] for row in decision.get("situational") or []]
    branches = decision.get("policy_branches") or []
    components = decision.get("early_components") or []

    blocks = [
        block("Starting", start_ids),
    ]

    # Add Early Components block if present
    if components:
        blocks.append(block("Early Spikes & Components (First Back)", components))

    # Add Kai'Sa Q Evolution block if identified
    ev_info = decision.get("evolution") or {}
    q_rush_items = ev_info.get("q_rush_items") or []
    if q_rush_items:
        blocks.append(block("Q Evolution Rush Components", q_rush_items))

    blocks.append(block("Buy order (default)", buy_ids))
    blocks.append(block("Late swaps (replace item 4-6)", situ_ids))

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
        "associatedMaps": cfg.get("associated_maps", [11, 12]),
        "preferredItemSlots": [],
        "blocks": blocks,
    }
