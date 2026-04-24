"""Dead Letter Queue for failed pipeline tasks.

Stores failed tasks for later retries, triggers alerts after 3 failures.
"""

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, list, dict

DLQ_DIR = Path(__file__).parent.parent / "data" / "dlq"
MAX_RETRIES = 3
ALERT_THRESHOLD = 3  # Alert after 3 failures


class DLQClient:
    """Dead Letter Queue client for storing and retrying failed tasks."""

    def __init__(self) -> None:
        DLQ_DIR.mkdir(parents=True, exist_ok=True)

    def add_failure(
        self,
        task_type: str,
        payload: dict,
        error: str,
        traceback: Optional[str] = None,
    ) -> dict:
        """Add a failed task to the DLQ.
        
        Args:
            task_type: Type of task (e.g., "crawl", "s3_write", "dynamo_write")
            payload: Task payload
            error: Error message
            traceback: Optional error traceback
        
        Returns:
            Saved DLQ entry
        """
        now = datetime.now(timezone.utc)
        entry_id = f"{now.strftime('%Y%m%d%H%M%S')}_{task_type}_{len(list(DLQ_DIR.glob(f'*.json')))}"
        
        entry = {
            "id": entry_id,
            "task_type": task_type,
            "payload": payload,
            "error": error,
            "traceback": traceback,
            "failed_at": now.isoformat(),
            "retry_count": 0,
            "last_retried_at": None,
        }
        
        with open(DLQ_DIR / f"{entry_id}.json", "w") as f:
            json.dump(entry, f, indent=2)
        
        # Check if we need to alert
        if self._should_alert(entry_id):
            self._send_alert(entry)
        
        return entry

    def _should_alert(self, entry_id: str) -> bool:
        """Check if we need to send an alert for this failure."""
        # Count failures for this task type in the last hour
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        count = 0
        
        for f in DLQ_DIR.glob("*.json"):
            with open(f, "r") as fp:
                entry = json.load(fp)
                if entry["task_type"] == entry_id.split("_")[1] and entry["failed_at"] >= cutoff:
                    count += 1
        
        return count >= ALERT_THRESHOLD

    def _send_alert(self, entry: dict) -> None:
        """Send an alert for repeated failures.
        
        TODO: Integrate with Telegram/Slack alerts.
        """
        # For now, just log to console
        print(f"[ALERT] {entry['task_type']} failed {ALERT_THRESHOLD} times in the last hour!")
        print(f"Latest error: {entry['error']}")

    def get_retryable_tasks(self, max_age_hours: int = 2) -> list[dict]:
        """Get all tasks that are eligible for retry.
        
        Args:
            max_age_hours: Only retry tasks younger than this (default 2 hours)
        
        Returns:
            List of retryable DLQ entries
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=max_age_hours)).isoformat()
        retryable = []
        
        for f in DLQ_DIR.glob("*.json"):
            with open(f, "r") as fp:
                entry = json.load(fp)
                if entry["retry_count"] < MAX_RETRIES and entry["failed_at"] >= cutoff:
                    retryable.append(entry)
        
        # Sort by failed_at (oldest first)
        return sorted(retryable, key=lambda x: x["failed_at"])

    def mark_retried(self, entry_id: str, success: bool, error: Optional[str] = None) -> None:
        """Mark a task as retried.
        
        Args:
            entry_id: DLQ entry ID
            success: Whether the retry succeeded
            error: Optional error message if retry failed
        """
        file_path = DLQ_DIR / f"{entry_id}.json"
        if not file_path.exists():
            return
        
        with open(file_path, "r") as f:
            entry = json.load(f)
        
        entry["retry_count"] += 1
        entry["last_retried_at"] = datetime.now(timezone.utc).isoformat()
        
        if success:
            # Delete successfully retried tasks
            file_path.unlink()
        else:
            # Update error message if retry failed
            entry["error"] = error or entry["error"]
            with open(file_path, "w") as f:
                json.dump(entry, f, indent=2)
            
            # Alert if max retries reached
            if entry["retry_count"] >= MAX_RETRIES:
                self._send_alert(entry)
                # Move to failed directory
                failed_dir = DLQ_DIR / "failed"
                failed_dir.mkdir(exist_ok=True)
                file_path.rename(failed_dir / f"{entry_id}.json")
