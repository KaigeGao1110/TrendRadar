"""Slash command handlers for TrendRadar Slack bot."""

from analyzer.digest import generate_daily_digest, generate_weekly_digest, format_for_slack
from analyzer.trends import analyze_daily_trends
from sources import yc, producthunt, hackernews, vc_funding
from storage.trends import get_latest, save_snapshot


def register_commands(app):
    """Register all slash commands with the Slack app."""

    @app.command("/trendradar-today")
    def daily_digest(ack, respond, command):
        """Send daily digest to channel."""
        ack()

        try:
            result = generate_daily_digest()
            formatted = format_for_slack(result)
            respond(formatted)
        except Exception as e:
            respond(f"Error generating digest: {str(e)}")

    @app.command("/trendradar-weekly")
    def weekly_digest(ack, respond, command):
        """Send weekly digest to channel."""
        ack()

        try:
            result = generate_weekly_digest()
            formatted = format_for_slack(result)
            respond(formatted)
        except Exception as e:
            respond(f"Error generating weekly digest: {str(e)}")

    @app.command("/trendradar-yc")
    def yc_trends(ack, respond, command):
        """Fetch latest YC batch trends."""
        ack()

        try:
            data = yc.fetch_latest_batch()
            save_snapshot("yc", data)

            if not data:
                respond("No YC companies found.")
                return

            lines = ["*Latest YC Batch Companies:*\n"]
            for i, company in enumerate(data[:10], 1):
                name = company.get("name", "Unknown")
                batch = company.get("batch", "")
                url = company.get("url", "")
                lines.append(f"{i}. <{url}|{name}> ({batch})")

            respond("\n".join(lines))
        except Exception as e:
            respond(f"Error fetching YC data: {str(e)}")

    @app.command("/trendradar-ph")
    def ph_trends(ack, respond, command):
        """Fetch today's Product Hunt trends."""
        ack()

        try:
            data = producthunt.fetch_today_trending()
            save_snapshot("producthunt", data)

            if not data:
                respond("No Product Hunt products found.")
                return

            lines = ["*Today's Product Hunt Trending:*\n"]
            for i, product in enumerate(data[:10], 1):
                name = product.get("name", "Unknown")
                tagline = product.get("tagline", "")
                votes = product.get("votes", 0)
                url = product.get("url", "")
                lines.append(f"{i}. <{url}|{name}> - {tagline} ({votes} votes)")

            respond("\n".join(lines))
        except Exception as e:
            respond(f"Error fetching Product Hunt data: {str(e)}")

    @app.command("/trendradar-hn")
    def hn_trends(ack, respond, command):
        """Fetch Hacker News trends."""
        ack()

        try:
            data = hackernews.fetch_top_stories()
            save_snapshot("hackernews", data)

            if not data:
                respond("No Hacker News stories found.")
                return

            lines = ["*Top Hacker News Stories:*\n"]
            for i, story in enumerate(data[:10], 1):
                title = story.get("title", "Unknown")
                score = story.get("score", 0)
                url = story.get("url", f"https://news.ycombinator.com/item?id={story.get('id')}")
                lines.append(f"{i}. <{url}|{title}> ({score} pts)")

            respond("\n".join(lines))
        except Exception as e:
            respond(f"Error fetching Hacker News data: {str(e)}")

    @app.command("/trendradar-funding")
    def funding_trends(ack, respond, command):
        """Fetch recent VC funding rounds."""
        ack()

        try:
            data = vc_funding.fetch_recent_funding()
            save_snapshot("vc_funding", data)

            if not data:
                respond("No funding rounds found.")
                return

            lines = ["*Recent VC Funding Rounds:*\n"]
            for i, round_data in enumerate(data[:10], 1):
                company = round_data.get("company", "Unknown")
                amount = round_data.get("amount", "Unknown")
                round_type = round_data.get("round", "")
                url = round_data.get("source_url", "")
                lines.append(f"{i}. <{url}|{company}> - {amount} ({round_type})")

            respond("\n".join(lines))
        except Exception as e:
            respond(f"Error fetching funding data: {str(e)}")

    @app.command("/trendradar-help")
    def help_command(ack, respond, command):
        """Show help for TrendRadar commands."""
        ack()

        help_text = """
*TrendRadar Commands:*

• `/trendradar-today` - Get daily trend digest
• `/trendradar-weekly` - Get weekly trend digest
• `/trendradar-yc` - Latest Y Combinator batch
• `/trendradar-ph` - Today's Product Hunt trending
• `/trendradar-hn` - Top Hacker News stories
• `/trendradar-funding` - Recent VC funding rounds
• `/trendradar-help` - Show this help

_TrendRadar - Know what's hot before everyone else._
"""
        respond(help_text)
