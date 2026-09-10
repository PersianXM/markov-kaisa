"""Disk caching helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from markov.config import OUTPUT_DIR


def read_cache(filename: str) -> Any | None:
    """Reads JSON from cache file if it exists."""
    path = OUTPUT_DIR / filename
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def write_cache(filename: str, data: Any) -> None:
    """Writes data to cache file."""
    path = OUTPUT_DIR / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
