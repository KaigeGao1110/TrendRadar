"""TrendRadar CLI."""

import click
from rich.console import Console
from rich.table import Table
from rich import print as rprint
from datetime import date

from sources import yc, producthunt, hackernews, vc_funding
from analyzer.digest import generate_daily_digest, generate_weekly_digest
from storage.trends import get_all_latest, get_history

console = Console()


@click.group()
def cli():
    """TrendRadar — Real-time VC trend radar for founders."""
    pass


@cli.group()
def trends():
    """Fetch trends from various sources."""
    pass


@trends.command()
@click.option("--source", default="all", help="Source: yc, producthunt, hackernews, vc, all")
def fetch(source):
    """Fetch trends from source(s)."""
    if source in ("all", "ycombinator", "yc"):
        with console.status("[bold green]Fetching YC companies..."):
            data = yc.fetch_latest_batch()
        _display_companies(data, "Y Combinator")
    
    if source in ("all", "producthunt", "ph"):
        with console.status("[bold green]Fetching Product Hunt..."):
            data = producthunt.fetch_today_trending()
        _display_products(data, "Product Hunt")
    
    if source in ("all", "hackernews", "hn"):
        with console.status("[bold green]Fetching Hacker News..."):
            data = hackernews.fetch_top_stories()
        _display_stories(data, "Hacker News")
    
    if source in ("all", "vc", "vc_funding"):
        with console.status("[bold green]Fetching VC funding..."):
            data = vc_funding.fetch_recent_funding()
        _display_funding(data, "Recent VC Funding")


def _display_companies(companies, title):
    table = Table(title=title)
    table.add_column("Company", style="cyan")
    table.add_column("One-liner", style="dim")
    table.add_column("Industry", style="green")
    
    for c in companies[:15]:
        table.add_row(
            c.get("name", ""),
            c.get("one_liner", "")[:50],
            c.get("industry", "")
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
def history():
    """Show recent trend history."""
    all_latest = get_all_latest()
    
    for source, snapshot in all_latest.items():
        console.print(f"\n[bold cyan]{source.upper()}[/bold cyan] — {snapshot.get('timestamp', '')[:10]}")
        data = snapshot.get("data", [])
        if isinstance(data, list) and data:
            console.print(f"  {len(data)} items")


if __name__ == "__main__":
    cli()
