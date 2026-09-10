"""Daily holdout validation, blacklist with TTL, and snapshot persistence."""

from __future__ import annotations

import json
from datetime import date, timedelta

from markov.config import BLACKLIST_PATH, HISTORY_DIR, HISTORY_PATH
from markov.engine.aggregation import actually_built
from markov.engine.math_utils import compact_score, score_path


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
    """Finds the most recent history entry before today, filtered by tier and champion."""
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
