"""Interactive terminal menus for champion and tier selection."""

from __future__ import annotations

import sys
from pathlib import Path

from markov.config import normalize_champion

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
