"""TrendRadar CLI."""

import click
import traceback
import csv
import sys
import json as _json
from collections import Counter
from rich.console import Console
from rich.table import Table
from rich import print as rprint
from datetime import date

from sources import yc, producthunt, hackernews, vc_funding, newsapi, rss, fundbat
from sources import reddit, github_trending, hackernews_comments, producthunt_deep, google_trends
from sources import twitter_pain
from sources import exa_pain
from sources import rss_pain
from analyzer.digest import generate_daily_digest, generate_weekly_digest
from storage.trends import get_all_latest, get_history, save_snapshot as save_json_snapshot
from storage.s3 import S3Client
from storage.dynamo import DynamoClient, FundingClient
from storage.dlq import DLQClient

console = Console()

# Initialize storage clients
s3_client = S3Client()
dynamo_client = DynamoClient()
funding_client = FundingClient()
dlq_client = DLQClient()

# Funding sources that write to the separate funding table
FUNDING_SOURCES = {"fundbat", "vc_funding"}


def _process_source_data(source: str, event_type: str, data: list[dict], get_url_fn, get_title_fn, get_published_fn=None):
    """Process data from a source: save to S3, deduplicate, save to DynamoDB."""
    if not data:
        return

    # Save raw snapshot to S3
    try:
        s3_key = s3_client.save_snapshot(source, data) if s3_client.available else None
    except Exception as e:
        console.print(f"[yellow]⚠️ Failed to save {source} data to S3: {e}")
        dlq_client.add_failure(
            task_type="s3_write",
            payload={"source": source, "data": data},
            error=str(e),
            traceback=traceback.format_exc(),
        )
        s3_key = None

    # Choose the right client: funding sources go to the funding table
    is_funding = source in FUNDING_SOURCES
    save_fn = funding_client.save_funding_event if is_funding else dynamo_client.save_event

    # Save each event to DynamoDB
    saved_count = 0
    duplicate_count = 0

    for item in data:
        try:
            url = get_url_fn(item)
            title = get_title_fn(item)
            published_at = get_published_fn(item) if get_published_fn else None

            result = save_fn(
                source=source,
                event_type=event_type,
                title=title,
                url=url,
                data=item,
                raw_s3_key=s3_key,
                published_at=published_at,
            )

            if result.get("exists"):
                duplicate_count += 1
            else:
                saved_count += 1
        except Exception as e:
            console.print(f"[yellow]⚠️ Failed to save {source} event to DynamoDB: {e}")
            dlq_client.add_failure(
                task_type="dynamo_write",
                payload={"source": source, "item": item},
                error=str(e),
                traceback=traceback.format_exc(),
            )

    # Also save to local JSON for fallback
    try:
        save_json_snapshot(source, {"items": data})
    except Exception:
        pass

    console.print(f"[green]✅ {source}: saved {saved_count} new events, skipped {duplicate_count} duplicates")


@click.group()
def cli():
    """TrendRadar — Real-time VC trend radar for founders."""
    pass


@cli.group()
def trends():
    """Fetch trends from various sources."""
    pass


@trends.command()
@click.option("--source", default="all", help="Source: yc, producthunt, hackernews, vc, newsapi, rss, fundbat, reddit, github_trending, hn_comments, ph_deep, google_trends, twitter_pain, all")
def fetch(source):
    """Fetch trends from source(s)."""
    if source in ("all", "ycombinator", "yc"):
        with console.status("[bold green]Fetching YC companies..."):
            data = yc.fetch_latest_batch()
        _display_companies(data, "Y Combinator")
        # Process and save to storage
        _process_source_data(
            source="yc",
            event_type="company_founding",
            data=data,
            get_url_fn=lambda x: x.get("website", ""),
            get_title_fn=lambda x: x.get("name", "") + ": " + x.get("one_liner", ""),
        )
    
    if source in ("all", "producthunt", "ph"):
        with console.status("[bold green]Fetching Product Hunt..."):
            data = producthunt.fetch_today_trending()
        _display_products(data, "Product Hunt")
        # Process and save to storage
        _process_source_data(
            source="producthunt",
            event_type="product_launch",
            data=data,
            get_url_fn=lambda x: x.get("url", ""),
            get_title_fn=lambda x: x.get("name", "") + ": " + x.get("tagline", ""),
        )
    
    if source in ("all", "hackernews", "hn"):
        with console.status("[bold green]Fetching Hacker News..."):
            data = hackernews.fetch_top_stories()
        _display_stories(data, "Hacker News")
        # Process and save to storage
        _process_source_data(
            source="hackernews",
            event_type="tech_story",
            data=data,
            get_url_fn=lambda x: x.get("url", ""),
            get_title_fn=lambda x: x.get("title", ""),
        )
    
    if source in ("all", "vc", "vc_funding"):
        with console.status("[bold green]Fetching VC funding..."):
            data = vc_funding.fetch_recent_funding()
        _display_funding(data, "Recent VC Funding")
        # Process and save to storage
        _process_source_data(
            source="vc_funding",
            event_type="funding_round",
            data=data,
            get_url_fn=lambda x: x.get("url", ""),
            get_title_fn=lambda x: x.get("company", "") + f" raises {x.get('amount', '')} {x.get('round', '')}",
        )
    
    if source in ("all", "newsapi"):
        with console.status("[bold green]Fetching News API..."):
            data = newsapi.fetch_startup_news()
        _display_stories(data, "Startup News")
        # Process and save to storage
        _process_source_data(
            source="newsapi",
            event_type="news_article",
            data=data,
            get_url_fn=lambda x: x.get("url", ""),
            get_title_fn=lambda x: x.get("title", ""),
        )
    
    if source in ("all", "rss"):
        with console.status("[bold green]Fetching RSS feeds..."):
            data = rss.fetch_all_newsletters()
        _display_stories(data, "RSS Newsletters")
        # Process and save to storage
        _process_source_data(
            source="rss",
            event_type="news_article",
            data=data,
            get_url_fn=lambda x: x.get("url", ""),
            get_title_fn=lambda x: x.get("title", ""),
        )
    
    # FundBat deprecated - SEC Form D is now primary funding source
    # if source in ("all", "fundbat"):
    #     with console.status("[bold green]Fetching FundBat funding data..."):
    #         data = fundbat.fetch_all_companies()
    #     _display_companies(data, "FundBat Startup Funding")
    #     _process_source_data(
    #         source="fundbat",
    #         event_type="funding_round",
    #         data=data,
    #         get_url_fn=lambda x: x.get("url", ""),
    #         get_title_fn=lambda x: x.get("name", "") + f" ({x.get('funding_amount', '')} / {x.get('valuation', '')})",
    #     )

    if source in ("all", "reddit"):
        with console.status("[bold green]Fetching Reddit posts..."):
            data = reddit.fetch_latest()
        _display_stories(data, "Reddit Posts")
        _process_source_data(
            source="reddit",
            event_type="reddit_post",
            data=data,
            get_url_fn=lambda x: x.get("url", ""),
            get_title_fn=lambda x: x.get("title", ""),
            get_published_fn=lambda x: x.get("published_at"),
        )

    if source in ("all", "github_trending", "gh"):
        with console.status("[bold green]Fetching GitHub Trending repos..."):
            data = github_trending.fetch_latest()
        _display_stories(data, "GitHub Trending")
        _process_source_data(
            source="github_trending",
            event_type="github_trending",
            data=data,
            get_url_fn=lambda x: x.get("url", ""),
            get_title_fn=lambda x: x.get("title", ""),
            get_published_fn=lambda x: x.get("published_at"),
        )

    if source in ("all", "hn_comments"):
        with console.status("[bold green]Fetching HN comments..."):
            data = hackernews_comments.fetch_latest()
        _display_stories(data, "HN Comments")
        _process_source_data(
            source="hackernews_comments",
            event_type="hn_comment",
            data=data,
            get_url_fn=lambda x: x.get("url", ""),
            get_title_fn=lambda x: x.get("title", ""),
            get_published_fn=lambda x: x.get("published_at"),
        )

    if source in ("all", "ph_deep", "producthunt_deep"):
        with console.status("[bold green]Fetching ProductHunt deep data..."):
            data = producthunt_deep.fetch_latest()
        _display_products(data, "ProductHunt Deep")
        _process_source_data(
            source="producthunt_deep",
            event_type="product_launch",
            data=data,
            get_url_fn=lambda x: x.get("url", ""),
            get_title_fn=lambda x: x.get("title", ""),
            get_published_fn=lambda x: x.get("published_at"),
        )

    if source in ("all", "google_trends", "trends"):
        with console.status("[bold green]Fetching Google Trends..."):
            data = google_trends.fetch_latest()
        _display_stories(data, "Google Trends")
        _process_source_data(
            source="google_trends",
            event_type="trending_search",
            data=data,
            get_url_fn=lambda x: x.get("url", ""),
            get_title_fn=lambda x: x.get("title", ""),
            get_published_fn=lambda x: x.get("published_at"),
        )


    if source in ("all", "twitter_pain", "tp"):
        with console.status("[bold green]Fetching Twitter pain signals..."):
            data = twitter_pain.fetch_latest()
        _display_stories(data, "Twitter Pain Signals")

        # Pre-filter with gemma4:31b before writing to DynamoDB
        if data:
            with console.status("[bold cyan]🔍 Filtering pain signals with gemma4:31b..."):
                pain_filter = PainFilter()
                data = pain_filter.filter_batch(data)

        _process_source_data(
            source="twitter_pain",
            event_type="pain_signal",
            data=data,
            get_url_fn=lambda x: x.get("url", ""),
            get_title_fn=lambda x: x.get("title", ""),
            get_published_fn=lambda x: x.get("published_at"),
        )

    # Exa semantic pain search
    if source in ("all", "exa_pain", "exa"):
        with console.status("[bold green]🔍 Exa: semantic pain search..."):
            data = exa_pain.fetch_all_pain_signals(limit_per_query=2)
        _display_stories(data, "Exa Pain Signals (Semantic)")
        _process_source_data(
            source="exa_pain",
            event_type="pain_signal",
            data=data,
            get_url_fn=lambda x: x.get("url", ""),
            get_title_fn=lambda x: x.get("title", ""),
            get_published_fn=lambda x: x.get("published"),
        )

    # RSS newsletter pain extraction
    if source in ("all", "rss_pain", "rss"):
        with console.status("[bold green]📰 RSS: extracting pain signals..."):
            data = rss_pain.fetch_rss_pain_signals(limit_per_feed=5)
        _display_stories(data, "RSS Pain Signals (Newsletter)")
        _process_source_data(
            source="rss_pain",
            event_type="pain_signal",
            data=data,
            get_url_fn=lambda x: x.get("url", ""),
            get_title_fn=lambda x: x.get("pain", ""),
            get_published_fn=lambda x: x.get("extracted_at"),
        )


def _display_companies(companies, title):
    table = Table(title=title)
    table.add_column("Company", style="cyan")
    table.add_column("One-liner", style="dim")
    table.add_column("Industry", style="green")
    
    for c in companies[:15]:
        industries = c.get("industry", [])
        industry_str = ", ".join(industries) if isinstance(industries, list) else str(industries)
        table.add_row(
            c.get("name", ""),
            c.get("one_liner", "")[:50],
            industry_str
        )
    
    console.print(table)


def _display_products(products, title):
    table = Table(title=title)
    table.add_column("Product", style="cyan")
    table.add_column("Tagline", style="dim")
    table.add_column("Votes", style="green", justify="right")
    
    for p in products[:15]:
        table.add_row(
            p.get("name", ""),
            p.get("tagline", "")[:50],
            str(p.get("votes", 0))
        )
    
    console.print(table)


def _display_stories(stories, title):
    table = Table(title=title)
    table.add_column("Title", style="cyan")
    table.add_column("Score", style="green", justify="right")
    table.add_column("Comments", style="yellow", justify="right")
    
    for s in stories[:15]:
        table.add_row(
            s.get("title", "")[:60],
            str(s.get("score", 0)),
            str(s.get("comments", 0))
        )
    
    console.print(table)


def _display_funding(funding, title):
    table = Table(title=title)
    table.add_column("Company", style="cyan")
    table.add_column("Round", style="green")
    table.add_column("Amount", style="yellow")
    
    for f in funding[:15]:
        amount = f.get("amount", 0)
        if amount >= 1_000_000:
            amount_str = f"${amount/1e6:.1f}M"
        elif amount >= 1_000:
            amount_str = f"${amount/1e3:.1f}K"
        else:
            amount_str = str(amount)
        
        table.add_row(
            f.get("company", ""),
            f.get("round", ""),
            amount_str
        )
    
    console.print(table)


@cli.group()
def digest():
    """Generate trend digests."""
    pass


@digest.command()
@click.option("--slack", is_flag=True, help="Format for Slack")
def daily(slack):
    """Generate daily digest."""
    with console.status("[bold green]Generating daily digest..."):
        result = generate_daily_digest()
    
    if slack:
        from analyzer.digest import format_for_slack
        console.print(format_for_slack(result))
    else:
        console.print("\n[bold]🔥 Daily Trend Digest[/bold]")
        console.print(f"Date: {result['date']}")
        console.print(f"Sources: {result['sources_count']}")
        console.print("\n[bold]Hot Categories:[/bold]")
        for c in result.get("hot_categories", []):
            console.print(f"  • {c}")
        console.print("\n[bold]Recommendations:[/bold]")
        for r in result.get("recommendations", []):
            console.print(f"  • {r}")


@digest.command()
def weekly():
    """Generate weekly digest."""
    with console.status("[bold green]Generating weekly digest..."):
        result = generate_weekly_digest()
    
    console.print("\n[bold]📅 Weekly Trend Digest[/bold]")
    console.print(f"Period: {result.get('period', '')}")
    console.print(f"Sources: {result['sources_count']}")
    console.print("\n[bold]Hot Categories:[/bold]")
    for c in result.get("hot_categories", []):
        console.print(f"  • {c}")


@cli.command()
def analyze():
    """Run AI scoring on unanalyzed events."""
    from analyzer.scorer import run_scoring
    
    with console.status("[bold green]Running AI scoring..."):
        result = run_scoring()
    
    console.print("\n[bold]📊 Scoring Results[/bold]")
    console.print(f"  Total events: {result['total']}")
    console.print(f"  Scored: {result['scored']}")
    console.print(f"  Failed: {result['failed']}")
    console.print(f"  Actionable (score ≥ 70): {result['actionable']}")


from analyzer.pain_filter import PainFilter
from analyzer.obsidian_writer import ObsidianWriter
from storage.embedding import EmbeddingClient
from storage.chroma_client import ChromaClient
from analyzer.pain_verifier import PainVerifier
from analyzer.cluster_engine import ClusterEngine


@cli.command()
def analyze_v2():
    """Run v2.1 analysis: embedding + clustering + verification + Obsidian output."""
    import json as _json
    from datetime import datetime as _dt, timezone as _tz
    from dotenv import load_dotenv
    import os as _os
    # Global first, then project .env overrides (project takes priority)
    load_dotenv(_os.path.expanduser("~/.openclaw/.env"))
    load_dotenv(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), ".env"), override=True)

    # Fallback: read ARK_API_KEY and DEEPSEEK_API_KEY from openclaw.json if not in env
    openclaw_json = _os.path.expanduser("~/.openclaw/openclaw.json")
    if _os.path.exists(openclaw_json):
        try:
            with open(openclaw_json) as f:
                openclaw_cfg = _json.load(f)
            env_vals = openclaw_cfg.get("env", {})
            if "ARK_API_KEY" not in _os.environ and "ARK_API_KEY" in env_vals:
                _os.environ["ARK_API_KEY"] = env_vals["ARK_API_KEY"]
            if "DEEPSEEK_API_KEY" not in _os.environ and "DEEPSEEK_API_KEY" in env_vals:
                _os.environ["DEEPSEEK_API_KEY"] = env_vals["DEEPSEEK_API_KEY"]
        except Exception:
            pass

    with console.status("[bold green]Initializing v2.1 analysis pipeline..."):
        try:
            embedding_client = EmbeddingClient()
        except ValueError as e:
            console.print(f"[red]❌ Embedding client init failed: {e}")
            console.print("[yellow]Set ARK_API_KEY in .env")
            return

        try:
            chroma = ChromaClient()
            dynamo = DynamoClient()
            funding_client = FundingClient()
            verifier = PainVerifier(embedding_client, chroma, dynamo, funding_client)
            engine = ClusterEngine(embedding_client, chroma, dynamo, verifier)
            writer = ObsidianWriter()
        except Exception as e:
            console.print(f"[red]❌ Storage client init failed: {e}")
            return

    today = _dt.now(_tz.utc).strftime("%Y-%m-%d")
    console.print(f"[bold]📅 Processing signals for {today}[/bold]")

    # Step 1: Process signals
    with console.status("[bold green]Running clustering and verification..."):
        clusters = engine.process_daily_signals(date=today)

    if not clusters:
        console.print("[yellow]⚠️ No opportunity clusters generated")
        console.print("Try running 'trendradar trends fetch' first to collect data")
        return

    # Step 2: Compute stats
    high_conf = sum(1 for c in clusters if c.get("confidence", 0) >= 70)
    actionable = sum(1 for c in clusters if c.get("total_score", 0) >= 70)

    # Count events by layer
    events = dynamo.get_unanalyzed_events(limit=200)
    from analyzer.pain_verifier import PAIN_SOURCES
    layer1 = sum(1 for e in events if e.get("source") in PAIN_SOURCES)
    # fundbat/vc_funding are now in separate table, so they won't appear here
    layer3_sources = {"vc_funding", "newsapi", "rss", "yc", "google_trends"}
    layer3 = sum(1 for e in events if e.get("source") in layer3_sources)
    layer2 = len(events) - layer1 - layer3

    stats = {
        "total_events": len(events),
        "pain_signals": layer1,
        "high_confidence_pains": high_conf,
        "actionable_clusters": actionable,
        "layer1_count": layer1,
        "layer2_count": layer2,
        "layer3_count": layer3,
    }

    # Step 3: Write Obsidian report
    with console.status("[bold green]Writing Obsidian report..."):
        filepath = writer.write_daily_report(clusters, stats, date=today)

    # Display summary
    console.print(f"\n[bold]📊 v2.1 Analysis Results[/bold]")
    console.print(f"  Clusters generated: {len(clusters)}")
    console.print(f"  High confidence pains: {high_conf}")
    console.print(f"  Actionable (score ≥ 70): {actionable}")
    console.print(f"\n📝 Report written to: {filepath}")

    # Show top clusters
    if clusters:
        table = Table(title="Top Opportunity Clusters")
        table.add_column("#", style="dim", width=3)
        table.add_column("Title", style="cyan", max_width=50)
        table.add_column("Score", style="green", justify="right")
        table.add_column("Confidence", style="yellow", justify="right")
        table.add_column("Sources", style="dim", max_width=20)

        for i, c in enumerate(clusters[:10], 1):
            sources_str = ", ".join(c.get("sources", [])[:3])
            table.add_row(
                str(i),
                c.get("title", "?")[:50],
                str(c.get("total_score", 0)),
                str(c.get("confidence", 0)),
                sources_str,
            )
        console.print(table)


@cli.command()
@click.option("--table", required=True, type=click.Choice(["events", "funding"]), help="Table to export")
@click.option("--source", default=None, help="Filter by source")
@click.option("--output", default=None, help="Output file path (default: stdout)")
def export(table, source, output):
    """Export DynamoDB data to CSV."""
    from pathlib import Path

    if table == "events":
        dyn_table = dynamo_client.table
    else:
        dyn_table = funding_client.table

    # Scan with optional source filter
    scan_kwargs = {}
    if source:
        scan_kwargs["FilterExpression"] = "#s = :source"
        scan_kwargs["ExpressionAttributeNames"] = {"#s": "source"}
        scan_kwargs["ExpressionAttributeValues"] = {":source": source}

    items = []
    response = dyn_table.scan(**scan_kwargs)
    items.extend(response.get("Items", []))
    while "LastEvaluatedKey" in response:
        scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
        response = dyn_table.scan(**scan_kwargs)
        items.extend(response.get("Items", []))

    if not items:
        console.print("[yellow]⚠️ No items found")
        return

    # Determine output path
    if output:
        filepath = Path(output)
    else:
        today_str = date.today().isoformat()
        src_suffix = f"_{source}" if source else ""
        filepath = Path(f"output/{table}{src_suffix}_{today_str}.csv")

    filepath.parent.mkdir(parents=True, exist_ok=True)

    # Build CSV
    source_counts = Counter()

    if table == "events":
        fieldnames = ["source", "event_type", "title", "url", "is_analyzed", "first_seen_at", "data"]
    else:
        fieldnames = ["source", "title", "funding_amount", "valuation", "category", "investors", "url", "first_seen_at"]

    should_close = False
    if output:
        fh = open(filepath, "w", newline="", encoding="utf-8")
        should_close = True
    else:
        fh = sys.stdout
        filepath = None  # stdout mode

    try:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()

        for item in items:
            src = item.get("source", "")
            source_counts[src] += 1

            if table == "events":
                data_val = item.get("data", {})
                if isinstance(data_val, dict):
                    data_val = _json.dumps(data_val, ensure_ascii=False)
                row = {
                    "source": src,
                    "event_type": item.get("event_type", ""),
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "is_analyzed": item.get("is_analyzed", False),
                    "first_seen_at": item.get("first_seen_at", ""),
                    "data": data_val,
                }
            else:
                data = item.get("data", {})
                if isinstance(data, str):
                    try:
                        data = _json.loads(data)
                    except _json.JSONDecodeError:
                        data = {}
                row = {
                    "source": src,
                    "title": item.get("title", ""),
                    "funding_amount": data.get("funding_amount", data.get("amount", "")),
                    "valuation": data.get("valuation", ""),
                    "category": data.get("category", ""),
                    "investors": data.get("investors", ""),
                    "url": item.get("url", ""),
                    "first_seen_at": item.get("first_seen_at", ""),
                }
            writer.writerow(row)
    finally:
        if should_close:
            fh.close()

    # Print stats
    console.print(f"\n[bold]📊 Export Complete[/bold]")
    console.print(f"  Total items: {len(items)}")
    if filepath:
        console.print(f"  Output: {filepath}")
    else:
        console.print("  Output: stdout")
    console.print("\n  By source:")
    for src, count in source_counts.most_common():
        console.print(f"    {src}: {count}")


@cli.command()
def push():
    """Generate daily push summary."""
    from analyzer.push import generate_daily_push
    
    message = generate_daily_push()
    console.print(message)


@cli.command()
def history():
    """Show recent trend history."""
    all_latest = get_all_latest()
    
    for source, snapshot in all_latest.items():
        console.print(f"\n[bold cyan]{source.upper()}[/bold cyan] — {snapshot.get('timestamp', '')[:10]}")
        data = snapshot.get("data", [])
        if isinstance(data, list) and data:
            console.print(f"  {len(data)} items")


@cli.command()
def retry_failed():
    """Retry failed DLQ tasks."""
    retryable = dlq_client.get_retryable_tasks()
    if not retryable:
        console.print("[green]✅ No failed tasks to retry.")
        return
    
    console.print(f"[yellow]🔄 Retrying {len(retryable)} failed tasks...")
    
    success_count = 0
    fail_count = 0
    
    for entry in retryable:
        try:
            if entry["task_type"] == "s3_write":
                s3_client.save_snapshot(entry["payload"]["source"], entry["payload"]["data"])
            elif entry["task_type"] == "dynamo_write":
                # TODO: Implement proper retry logic for each task type
                pass
            
            dlq_client.mark_retried(entry["id"], success=True)
            success_count += 1
        except Exception as e:
            dlq_client.mark_retried(entry["id"], success=False, error=str(e))
            fail_count += 1
    
    console.print(f"[green]✅ Retried {success_count} tasks successfully, {fail_count} failed again.")


@cli.command()
@click.option("--dry-run", is_flag=True, help="Show what would be deleted without deleting")
@click.option("--threshold", default=0.95, help="Similarity threshold for deduplication (0.0-1.0)")
def dedup(dry_run, threshold):
    """Remove duplicate pain_signals and opportunity_clusters from ChromaDB.

    Keeps the earliest record and removes duplicates with similarity > threshold.
    """
    from storage.chroma_client import ChromaClient

    chroma = ChromaClient()
    deleted_pains = 0
    deleted_clusters = 0

    # ---- Deduplicate pain_signals ----
    console.print("[bold]Deduplicating pain_signals...[/bold]")

    # Fetch all pain signals
    all_pains = chroma.pains.get(include=["metadatas", "documents", "embeddings"])
    if all_pains["ids"]:
        id_list = all_pains["ids"]
        docs = all_pains["documents"]
        metas = all_pains["metadatas"]
        embs = all_pains["embeddings"]

        keep_ids = set()
        dup_ids = []

        for i, pain_id in enumerate(id_list):
            if pain_id in keep_ids or pain_id in dup_ids:
                continue

            emb_i = embs[i]
            if not emb_i:
                keep_ids.add(pain_id)
                continue

            # Compare with all later entries
            for j in range(i + 1, len(id_list)):
                if id_list[j] in dup_ids:
                    continue
                emb_j = embs[j]
                if not emb_j:
                    continue

                # Compute cosine similarity
                import math
                dot = sum(float(a) * float(b) for a, b in zip(emb_i, emb_j))
                mag_i = math.sqrt(sum(float(x) ** 2 for x in emb_i))
                mag_j = math.sqrt(sum(float(y) ** 2 for y in emb_j))
                if mag_i == 0 or mag_j == 0:
                    continue
                sim = dot / (mag_i * mag_j)

                if sim >= threshold:
                    dup_ids.append(id_list[j])

        console.print(f"  pain_signals: {len(id_list)} total, {len(dup_ids)} duplicates found")
        if dry_run:
            console.print(f"  [yellow]--dry-run: would delete {len(dup_ids)} duplicate pain_signals[/yellow]")
        else:
            if dup_ids:
                chroma.pains.delete(ids=dup_ids)
                deleted_pains = len(dup_ids)
                console.print(f"  [green]Deleted {deleted_pains} duplicate pain_signals[/green]")

    # ---- Deduplicate opportunity_clusters ----
    console.print("[bold]Deduplicating opportunity_clusters...[/bold]")

    all_clusters = chroma.clusters.get(include=["metadatas", "documents", "embeddings"])
    if all_clusters["ids"]:
        id_list = all_clusters["ids"]
        embs = all_clusters["embeddings"]

        dup_ids = []

        for i, cluster_id in enumerate(id_list):
            if cluster_id in dup_ids:
                continue

            emb_i = embs[i]
            if not emb_i:
                continue

            for j in range(i + 1, len(id_list)):
                if id_list[j] in dup_ids:
                    continue
                emb_j = embs[j]
                if not emb_j:
                    continue

                import math
                dot = sum(float(a) * float(b) for a, b in zip(emb_i, emb_j))
                mag_i = math.sqrt(sum(float(x) ** 2 for x in emb_i))
                mag_j = math.sqrt(sum(float(y) ** 2 for y in emb_j))
                if mag_i == 0 or mag_j == 0:
                    continue
                sim = dot / (mag_i * mag_j)

                if sim >= threshold:
                    dup_ids.append(id_list[j])

        console.print(f"  opportunity_clusters: {len(id_list)} total, {len(dup_ids)} duplicates found")
        if dry_run:
            console.print(f"  [yellow]--dry-run: would delete {len(dup_ids)} duplicate clusters[/yellow]")
        else:
            if dup_ids:
                chroma.clusters.delete(ids=dup_ids)
                deleted_clusters = len(dup_ids)
                console.print(f"  [green]Deleted {deleted_clusters} duplicate clusters[/green]")

    console.print(f"\n[bold]Done.[/bold] Removed {deleted_pains} pains, {deleted_clusters} clusters.")


if __name__ == "__main__":
    cli()
