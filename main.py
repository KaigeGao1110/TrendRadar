"""TrendRadar CLI."""

import click
import traceback
from rich.console import Console
from rich.table import Table
from rich import print as rprint
from datetime import date

from sources import yc, producthunt, hackernews, vc_funding, newsapi, rss, fundbat
from analyzer.digest import generate_daily_digest, generate_weekly_digest
from storage.trends import get_all_latest, get_history, save_snapshot as save_json_snapshot
from storage.s3 import S3Client
from storage.dynamo import DynamoClient
from storage.dlq import DLQClient

console = Console()

# Initialize storage clients
s3_client = S3Client()
dynamo_client = DynamoClient()
dlq_client = DLQClient()


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
    
    # Save each event to DynamoDB
    saved_count = 0
    duplicate_count = 0
    
    for item in data:
        try:
            url = get_url_fn(item)
            title = get_title_fn(item)
            published_at = get_published_fn(item) if get_published_fn else None
            
            result = dynamo_client.save_event(
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
@click.option("--source", default="all", help="Source: yc, producthunt, hackernews, vc, newsapi, rss, fundbat, all")
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
    
    if source in ("all", "fundbat"):
        with console.status("[bold green]Fetching FundBat funding data..."):
            data = fundbat.fetch_all_companies()
        _display_companies(data, "FundBat Startup Funding")
        # Process and save to storage
        _process_source_data(
            source="fundbat",
            event_type="funding_round",
            data=data,
            get_url_fn=lambda x: x.get("url", ""),
            get_title_fn=lambda x: x.get("name", "") + f" ({x.get('funding_amount', '')} / {x.get('valuation', '')})",
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


if __name__ == "__main__":
    cli()
