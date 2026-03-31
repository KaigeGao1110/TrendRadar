"""Trend data storage."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

TRENDS_FILE = Path(__file__).parent.parent / "data" / "trends.json"


def _ensure_data_dir() -> None:
    """Ensure the data directory exists."""
    TRENDS_FILE.parent.mkdir(parents=True, exist_ok=True)


def _load() -> dict:
    """Load all trend data from file.

    Returns:
        Dictionary of trend data.
    """
    _ensure_data_dir()
    if not TRENDS_FILE.exists():
        return {"sources": {}, "history": []}

    try:
        with open(TRENDS_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"sources": {}, "history": []}


def _save(data: dict) -> None:
    """Save trend data to file.

    Args:
        data: Trend data dictionary.
    """
    _ensure_data_dir()
    with open(TRENDS_FILE, "w") as f:
        json.dump(data, f, indent=2, default=str)


def save_snapshot(source: str, data: dict) -> dict:
    """Save a snapshot of trend data from a source.

    Args:
        source: Source name (e.g., 'hackernews', 'producthunt').
        data: Trend data to save.

    Returns:
        The saved data with metadata.
    """
    trend_data = _load()

    snapshot = {
        "source": source,
        "data": data,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

    if source not in trend_data["sources"]:
        trend_data["sources"][source] = []

    trend_data["sources"][source].insert(0, snapshot)

    # Keep only last 100 snapshots per source
    trend_data["sources"][source] = trend_data["sources"][source][:100]

    # Add to history
    trend_data["history"].insert(0, snapshot)
    trend_data["history"] = trend_data["history"][:1000]

    _save(trend_data)
    return snapshot


def get_latest(source: str) -> Optional[dict]:
    """Get the latest snapshot for a source.

    Args:
        source: Source name.

    Returns:
        Latest snapshot dict or None.
    """
    trend_data = _load()
    if source not in trend_data["sources"] or not trend_data["sources"][source]:
        return None
    return trend_data["sources"][source][0]


def get_history(source: str, limit: int = 7) -> list[dict]:
    """Get historical snapshots for a source.

    Args:
        source: Source name.
        limit: Maximum number of snapshots to return.

    Returns:
        List of historical snapshots.
    """
    trend_data = _load()
    if source not in trend_data["sources"]:
        return []
    return trend_data["sources"][source][:limit]


def get_all_latest() -> dict:
    """Get the latest snapshot from all sources.

    Returns:
        Dictionary of {source: latest_snapshot}.
    """
    trend_data = _load()
    result = {}
    for source, snapshots in trend_data.get("sources", {}).items():
        if snapshots:
            result[source] = snapshots[0]
    return result
