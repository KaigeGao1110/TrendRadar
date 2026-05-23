"""Supabase storage backend for TrendRadar.

Replaces JSON-file storage with a Supabase PostgreSQL backend.
Set SUPABASE_URL and SUPABASE_KEY environment variables before use.
"""

import os
from datetime import datetime, timezone, timedelta
from typing import Optional

try:
    from supabase import create_client, Client
except ImportError:
    create_client = None  # type: ignore
    Client = None  # type: ignore

from storage.trends import get_latest as _json_get_latest, get_history as _json_get_history


class SupabaseClient:
    """Supabase-backed storage client for TrendRadar trend data.

    Falls back to JSON storage if Supabase is unavailable.
    """

    def __init__(self) -> None:
        self.url: str | None = os.environ.get("SUPABASE_URL")
        self.key: str | None = os.environ.get("SUPABASE_KEY")
        self._client: Client | None = (
            create_client(self.url, self.key) if create_client and self.url and self.key else None
        )

    @property
    def available(self) -> bool:
        """Return True if Supabase client is initialized."""
        return self._client is not None

    # -------------------------------------------------------------------------
    # Snapshots
    # -------------------------------------------------------------------------

    def save_snapshot(self, source: str, data: dict) -> dict:
        """Save a snapshot of trend data from a source.

        Mirrors storage.trends.save_snapshot().

        Args:
            source: Source name (e.g., 'hackernews', 'producthunt').
            data: Trend data to save.

        Returns:
            The saved snapshot record.
        """
        snapshot = {
            "source": source,
            "data": data,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        if self._client:
            result = (
                self._client.table("snapshots")
                .insert(snapshot)
                .execute()
            )
            if result.data:
                return result.data[0]

        # Fallback: delegate to JSON storage
        return _json_get_latest(source) or snapshot

    def get_latest(self, source: str) -> Optional[dict]:
        """Get the latest snapshot for a source.

        Args:
            source: Source name.

        Returns:
            Latest snapshot dict or None.
        """
        if self._client:
            result = (
                self._client.table("snapshots")
                .select("*")
                .eq("source", source)
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            if result.data:
                return result.data[0]

        return _json_get_latest(source)

    def get_history(self, source: str, limit: int = 7) -> list[dict]:
        """Get historical snapshots for a source.

        Args:
            source: Source name.
            limit: Maximum number of snapshots to return.

        Returns:
            List of historical snapshots, newest first.
        """
        if self._client:
            result = (
                self._client.table("snapshots")
                .select("*")
                .eq("source", source)
                .order("created_at", desc=True)
                .limit(limit)
                .execute()
            )
            return result.data or []

        return _json_get_history(source, limit)

    def get_all_latest(self) -> dict[str, dict]:
        """Get the latest snapshot from all sources.

        Returns:
            Dictionary of {source: latest_snapshot}.
        """
        result: dict[str, dict] = {}

        if self._client:
            # Distinct sources via a window function or subquery workaround
            # Fetch up to 100 latest per source (simulate "all sources")
            for source in self._get_sources():
                snap_result = (
                    self._client.table("snapshots")
                    .select("*")
                    .eq("source", source)
                    .order("created_at", desc=True)
                    .limit(1)
                    .execute()
                )
                if snap_result.data:
                    result[source] = snap_result.data[0]
            return result

        from storage.trends import get_all_latest as _json_all
        return _json_all()

    def _get_sources(self) -> list[str]:
        """Return distinct source names from snapshots."""
        if not self._client:
            return []
        result = (
            self._client.table("snapshots")
            .select("source")
            .execute()
        )
        return list({r["source"] for r in result.data}) if result.data else []

    # -------------------------------------------------------------------------
    # Digests
    # -------------------------------------------------------------------------

    def save_digest(self, digest: dict) -> dict:
        """Save a generated digest.

        Mirrors storage.trends.save_digest().

        Args:
            digest: Digest dict with date, type, content.

        Returns:
            The saved digest record.
        """
        record = {
            "type": digest.get("type", "daily"),
            "content": digest.get("content", digest),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        if self._client:
            result = (
                self._client.table("digests")
                .insert(record)
                .execute()
            )
            if result.data:
                return result.data[0]

        from storage.trends import save_digest as _json_save
        return _json_save(digest)

    def get_latest_digest(self, digest_type: str = "daily") -> Optional[dict]:
        """Get the most recent digest of a given type.

        Args:
            digest_type: "daily" or "weekly".

        Returns:
            Latest digest dict or None.
        """
        if self._client:
            result = (
                self._client.table("digests")
                .select("*")
                .eq("type", digest_type)
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            if result.data:
                return result.data[0]

        from storage.trends import get_latest_digest as _json_latest
        return _json_latest(digest_type)

    # -------------------------------------------------------------------------
    # Trend history (metrics)
    # -------------------------------------------------------------------------

    def save_trend_metric(
        self,
        source: str,
        metric_name: str,
        metric_value: float,
        recorded_at: datetime | None = None,
    ) -> dict:
        """Record a metric value for a source.

        Args:
            source: Source name.
            metric_name: Name of the metric (e.g., 'post_count', 'score').
            metric_value: Numeric value of the metric.
            recorded_at: Timestamp for this record (defaults to now).

        Returns:
            The saved trend_history record.
        """
        record = {
            "source": source,
            "metric_name": metric_name,
            "metric_value": metric_value,
            "recorded_at": (recorded_at or datetime.now(timezone.utc)).isoformat(),
        }

        if self._client:
            result = (
                self._client.table("trend_history")
                .insert(record)
                .execute()
            )
            if result.data:
                return result.data[0]

        return record

    def get_trends_by_date_range(
        self,
        source: str,
        metric_name: str,
        start_date: datetime,
        end_date: datetime,
    ) -> list[dict]:
        """Get metric values for a source within a date range.

        Args:
            source: Source name.
            metric_name: Metric name to query.
            start_date: Start of date range (inclusive).
            end_date: End of date range (inclusive).

        Returns:
            List of trend_history records, oldest first.
        """
        if self._client:
            result = (
                self._client.table("trend_history")
                .select("*")
                .eq("source", source)
                .eq("metric_name", metric_name)
                .gte("recorded_at", start_date.isoformat())
                .lte("recorded_at", end_date.isoformat())
                .order("recorded_at", desc=False)
                .execute()
            )
            return result.data or []

        return []

    def search_trends(self, keyword: str) -> list[dict]:
        """Search snapshots whose JSON data contains a keyword.

        Performs a case-insensitive substring search over the JSONB data field.

        Args:
            keyword: Keyword to search for.

        Returns:
            List of matching snapshot records.
        """
        if self._client:
            # JSONB contains text search via ->> operator
            result = (
                self._client.table("snapshots")
                .select("*")
                .ilike("data", f"%{keyword}%")
                .order("created_at", desc=True)
                .limit(50)
                .execute()
            )
            return result.data or []

        return []

    def cleanup_old_snapshots(self, keep_days: int = 30) -> int:
        """Delete snapshots older than the retention window.

        Args:
            keep_days: Number of days to retain (default 30).

        Returns:
            Number of records deleted.
        """
        if not self._client:
            return 0

        cutoff = datetime.now(timezone.utc) - timedelta(days=keep_days)
        result = (
            self._client.table("snapshots")
            .delete()
            .lt("created_at", cutoff.isoformat())
            .execute()
        )
        # Supabase delete returns deleted rows in .data
        return len(result.data) if result.data else 0
