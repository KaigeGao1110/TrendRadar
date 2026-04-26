"""Obsidian Markdown output for TrendRadar v2.1 daily reports.

Generates daily report files and reads user ratings back.
Output path: {vault_path}/TrendRadar/YYYY-MM-DD.md
"""

import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_VAULT_PATH = "/home/kaige/.openclaw/workspace"


class ObsidianWriter:
    """Write daily TrendRadar reports as Obsidian-compatible Markdown."""

    def __init__(self, vault_path: Optional[str] = None):
        self.vault_path = vault_path or os.environ.get(
            "TREND_RADAR_VAULT_PATH", DEFAULT_VAULT_PATH
        )
        self.output_dir = Path(self.vault_path) / "TrendRadar"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Daily report
    # ------------------------------------------------------------------

    def write_daily_report(
        self,
        clusters: list[dict],
        stats: dict,
        date: Optional[str] = None,
    ) -> str:
        """Generate and write the daily report Markdown file.

        Args:
            clusters: List of scored opportunity cluster dicts.
            stats: Dict with summary stats (total_events, pain_signals, etc).
            date: YYYY-MM-DD string (default: today UTC).

        Returns:
            Path to the written file.
        """
        if date is None:
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        lines = self._build_report(clusters, stats, date)
        content = "\n".join(lines)

        filepath = self.output_dir / f"{date}.md"
        filepath.write_text(content, encoding="utf-8")
        logger.info("Written daily report to %s", filepath)
        return str(filepath)

    def _build_report(self, clusters: list[dict], stats: dict, date: str) -> list[str]:
        """Build the Markdown lines for the report."""
        lines = []

        # Header
        lines.append(f"# 🎯 TrendRadar 每日信号 — {date}")
        lines.append("")

        # Overview
        lines.append("## 📊 今日概览")
        lines.append(f"- 新增事件: {stats.get('total_events', 0)} 条")
        lines.append(f"- 痛点信号: {stats.get('pain_signals', 0)} 条 "
                      f"({stats.get('high_confidence_pains', 0)} 条高置信)")
        lines.append(f"- 可行机会: {stats.get('actionable_clusters', 0)} 条 (score ≥ 70)")
        lines.append("")
        lines.append("---")
        lines.append("")

        # High-value opportunities (score >= 70)
        high_value = [c for c in clusters if c.get("total_score", 0) >= 70]
        pending = [c for c in clusters if 50 <= c.get("total_score", 0) < 70]

        if high_value:
            lines.append("## 🔥 高价值机会 (score ≥ 70)")
            lines.append("")
            for i, cluster in enumerate(high_value, 1):
                lines.extend(self._format_cluster(i, cluster))
                lines.append("")

        # Pending verification
        if pending:
            lines.append("## 🟡 待验证 (confidence 50-69)")
            lines.append("")
            offset = len(high_value) + 1
            for i, cluster in enumerate(pending, offset):
                lines.extend(self._format_cluster(i, cluster, brief=True))
                lines.append("")

        if not high_value and not pending:
            lines.append("## 📭 今日无高价值机会")
            lines.append("")
            lines.append("继续监控市场动态...")
            lines.append("")

        # Stats table
        lines.append("---")
        lines.append("")
        lines.append("## 📈 今日统计")
        lines.append("")
        lines.append("| 指标 | 值 |")
        lines.append("|------|-----|")
        lines.append(f"| 总事件 | {stats.get('total_events', 0)} |")
        lines.append(f"| 痛点信号 | {stats.get('pain_signals', 0)} |")
        lines.append(f"| 高置信痛点 | {stats.get('high_confidence_pains', 0)} |")
        lines.append(f"| 可行机会 | {stats.get('actionable_clusters', 0)} |")
        lines.append(f"| Layer 1 数据量 | {stats.get('layer1_count', 0)} |")
        lines.append(f"| Layer 2 数据量 | {stats.get('layer2_count', 0)} |")
        lines.append(f"| Layer 3 数据量 | {stats.get('layer3_count', 0)} |")
        lines.append("")

        return lines

    def _format_cluster(self, index: int, cluster: dict, brief: bool = False) -> list[str]:
        """Format a single cluster as Markdown."""
        lines = []
        total = cluster.get("total_score", 0)
        title = cluster.get("title", "Untitled")
        confidence = cluster.get("confidence", 0)
        sources = cluster.get("sources", [])

        # Title line
        lines.append(f"### {index}. [{total}分] {title}")

        # Confidence and sources
        source_str = ", ".join(sources[:5]) if sources else "unknown"
        # Count mentions per source
        source_counts = {}
        for ev in cluster.get("layer1", []) + cluster.get("layer2", []) + cluster.get("layer3", []):
            src = ev.get("source", "unknown")
            source_counts[src] = source_counts.get(src, 0) + 1
        source_detail = " + ".join(f"{s}({c})" for s, c in sorted(source_counts.items()))
        lines.append(f"**置信度:** {confidence}/100")
        lines.append(f"**来源:** {source_detail}")
        lines.append("")

        if brief:
            lines.append(f"**你的评分:** __/10")
            lines.append("")
            return lines

        # Score table
        pain = cluster.get("pain_score", 0)
        tech = cluster.get("tech_score", 0)
        timing = cluster.get("timing_score", 0)
        verification = cluster.get("verification", {})
        mention_count = verification.get("mention_count", 1)

        lines.append("| 维度 | 分数 | 说明 |")
        lines.append("|------|------|------|")
        pain_desc = f"{mention_count}人提到类似痛点"
        tech_desc = self._build_tech_desc(cluster)
        timing_desc = self._build_timing_desc(cluster)
        lines.append(f"| 痛点 | {pain} | {pain_desc} |")
        lines.append(f"| 技术 | {tech} | {tech_desc} |")
        lines.append(f"| 时机 | {timing} | {timing_desc} |")
        lines.append("")

        # AI Reasoning
        reasoning = cluster.get("reasoning", "")
        if reasoning:
            lines.append(f"**AI Reasoning:** {reasoning}")
            lines.append("")

        # Related signals
        all_events = cluster.get("layer1", []) + cluster.get("layer2", []) + cluster.get("layer3", [])
        if all_events:
            lines.append("**相关信号:**")
            for ev in all_events[:8]:
                src = ev.get("source", "")
                ev_title = ev.get("title", "")
                url = ev.get("url", "")
                icon = self._source_icon(src)
                if url:
                    lines.append(f"- {icon} [{ev_title}]({url})")
                else:
                    lines.append(f"- {icon} {ev_title}")
            lines.append("")

        # User rating
        lines.append("**你的评分:** __/10")
        lines.append("**备注:** _________")
        lines.append("")

        return lines

    def _source_icon(self, source: str) -> str:
        """Get emoji icon for a source."""
        icons = {
            "twitter_pain": "🐦",
            "reddit": "💬",
            "hackernews": "🔗",
            "hackernews_comments": "💬",
            "producthunt": "🚀",
            "producthunt_deep": "🚀",
            "github_trending": "💻",
            "fundbat": "💰",
            "vc_funding": "💰",
            "yc": "🎓",
            "newsapi": "📰",
            "rss": "📰",
            "google_trends": "📈",
        }
        return icons.get(source, "📌")

    def _build_tech_desc(self, cluster: dict) -> str:
        """Build tech feasibility description from Layer 2 events."""
        layer2 = cluster.get("layer2", [])
        if not layer2:
            return "无直接技术信号"
        parts = []
        for ev in layer2[:3]:
            src = ev.get("source", "")
            title = ev.get("title", "")
            if src == "github_trending":
                parts.append(f"GitHub: {title}")
            elif "hackernews" in src:
                parts.append(f"HN: {title}")
        return "; ".join(parts) if parts else f"{len(layer2)}条技术信号"

    def _build_timing_desc(self, cluster: dict) -> str:
        """Build timing description from Layer 3 events."""
        layer3 = cluster.get("layer3", [])
        if not layer3:
            return "无直接市场验证"
        parts = []
        for ev in layer3[:3]:
            src = ev.get("source", "")
            title = ev.get("title", "")
            if src in ("fundbat", "vc_funding"):
                parts.append(f"融资: {title}")
            elif src == "yc":
                parts.append(f"YC: {title}")
        return "; ".join(parts) if parts else f"{len(layer3)}条市场信号"

    # ------------------------------------------------------------------
    # Rating reader
    # ------------------------------------------------------------------

    def read_user_ratings(self, date: str) -> list[dict]:
        """Read user ratings from an Obsidian daily report.

        Parses lines matching: **你的评分:** X/10

        Args:
            date: YYYY-MM-DD string.

        Returns:
            List of dicts with cluster_title, rating, date.
        """
        filepath = self.output_dir / f"{date}.md"
        if not filepath.exists():
            logger.info("No report file for %s", date)
            return []

        content = filepath.read_text(encoding="utf-8")
        ratings = []

        lines = content.split("\n")
        current_title = ""

        for line in lines:
            # Detect cluster title lines: "### N. [score] title"
            title_match = re.match(r"###\s+\d+\.\s+\[\d+分\]\s+(.+)", line)
            if title_match:
                current_title = title_match.group(1).strip()
                continue

            # Detect rating lines: "**你的评分:** 7/10" or "**你的评分:** __/10"
            rating_match = re.search(
                r"\*\*你的评分:\*\*\s*(\d{1,2})/10", line
            )
            if rating_match:
                rating_val = int(rating_match.group(1))
                if 1 <= rating_val <= 10:
                    ratings.append({
                        "cluster_title": current_title,
                        "rating": rating_val,
                        "date": date,
                    })

        logger.info("Read %d user ratings from %s", len(ratings), filepath)
        return ratings
