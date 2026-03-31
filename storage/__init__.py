"""Trend data storage."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

DATA_DIR = Path(__file__).parent.parent / "data"
TRENDS_FILE = DATA_DIR / "trends.json"


def _ensure_data_dir():
    """Ensure data directory exists."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _load() -> dict:
    """Load all trend data from file."""
    _ensure_data_dir()
    if not TRENDS_FILE.exists():
        return {"sources": {}, "digests": []}
    try:
        with open(TRENDS_FILE, "r") as f:
            data = json.load(f)
            if "digests" not in data:
                data["digests"] = []
            return data
    except (json.JSONDecodeError, IOError):
        return {"sources": {}, "digests": []}


def _save(data: dict) -> None:
    """Save trend data to file."""
    _ensure_data_dir()
    with open(TRENDS_FILE, "w") as f:
        json.dump(data, f, indent=2, default=str)


def save_snapshot(source: str, data: dict) -> dict:
    """Save a snapshot of data from a source.
    
    Args:
        source: Source name (e.g., "hackernews", "producthunt")
        data: Data to save
    
    Returns:
        The saved snapshot with timestamp
    """
    all_data = _load()
    if "digests" not in all_data:
        all_data["digests"] = []
    
    snapshot = {
        "source": source,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": data,
    }
    
    if source not in all_data["sources"]:
        all_data["sources"][source] = []
    
    all_data["sources"][source].append(snapshot)
    
    # Keep only last 100 snapshots per source
    all_data["sources"][source] = all_data["sources"][source][-100:]
    
    _save(all_data)
    return snapshot


def get_latest(source: str) -> Optional[dict]:
    """Get latest data snapshot from a source."""
    all_data = _load()
    snapshots = all_data.get("sources", {}).get(source, [])
    if not snapshots:
        return None
    return snapshots[-1]


def get_history(source: str, limit: int = 7) -> list[dict]:
    """Get historical data for a source.
    
    Args:
        source: Source name
        limit: Number of snapshots to return
    
    Returns:
        List of snapshots, most recent first
    """
    all_data = _load()
    snapshots = all_data.get("sources", {}).get(source, [])
    return list(reversed(snapshots[-limit:]))


def get_all_latest() -> dict:
    """Get latest snapshot from all sources."""
    all_data = _load()
    result = {}
    for source, snapshots in all_data.get("sources", {}).items():
        if snapshots:
            result[source] = snapshots[-1]
    return result


def save_digest(digest: dict) -> None:
    """Save a generated digest."""
    all_data = _load()
    if "digests" not in all_data:
        all_data["digests"] = []
    all_data["digests"].append({
        **digest,
        "saved_at": datetime.now(timezone.utc).isoformat(),
    })
    # Keep only last 50 digests
    all_data["digests"] = all_data["digests"][-50:]
    _save(all_data)


def get_latest_digest() -> Optional[dict]:
    """Get the most recent digest."""
    all_data = _load()
    digests = all_data.get("digests", [])
    if not digests:
        return None
    return digests[-1]
