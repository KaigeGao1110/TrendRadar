"""TrendRadar REST API (FastAPI)."""

from datetime import date
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from sources import yc, producthunt, hackernews, vc_funding
from analyzer.digest import generate_daily_digest, generate_weekly_digest, format_for_slack
from storage.trends import get_all_latest, get_latest, get_history, get_latest_digest, save_digest

app = FastAPI(
    title="TrendRadar API",
    description="Real-time VC trend radar for founders",
    version="1.0.0",
)


class DigestRequest(BaseModel):
    format: Optional[str] = "json"  # json, slack, email


@app.get("/health")
def health():
    """Health check."""
    return {"status": "ok", "service": "trendradar"}


@app.get("/trends")
def get_trends():
    """Get latest trends from all sources."""
    all_latest = get_all_latest()
    return {
        "date": str(date.today()),
        "sources": len(all_latest),
        "data": all_latest,
    }


@app.get("/trends/{source}")
def get_source_trends(source: str):
    """Get latest trends from a specific source."""
    valid_sources = ["ycombinator", "producthunt", "hackernews", "vc_funding"]
    if source not in valid_sources:
        raise HTTPException(status_code=400, detail=f"Invalid source. Valid: {valid_sources}")
    
    snapshot = get_latest(source)
    if not snapshot:
        raise HTTPException(status_code=404, detail=f"No data for source: {source}")
    
    return snapshot


@app.get("/trends/{source}/history")
def get_source_history(source: str, limit: int = 7):
    """Get historical data for a source."""
    valid_sources = ["ycombinator", "producthunt", "hackernews", "vc_funding"]
    if source not in valid_sources:
        raise HTTPException(status_code=400, detail=f"Invalid source. Valid: {valid_sources}")
    
    history = get_history(source, limit=limit)
    return {"source": source, "count": len(history), "history": history}


@app.post("/digest/daily")
def create_daily_digest(req: Optional[DigestRequest] = None):
    """Generate daily digest."""
    digest = generate_daily_digest()
    
    if req and req.format == "slack":
        return format_for_slack(digest)
    
    return digest


@app.post("/digest/weekly")
def create_weekly_digest(req: Optional[DigestRequest] = None):
    """Generate weekly digest."""
    digest = generate_weekly_digest()
    
    if req and req.format == "slack":
        return format_for_slack(digest)
    
    return digest


@app.get("/digest/latest")
def get_latest_digest_endpoint():
    """Get latest digest, auto-generate if none cached."""
    digest = get_latest_digest()
    if not digest:
        # Auto-generate rather than returning 404
        digest = generate_daily_digest()
    return digest


@app.get("/sources/ycombinator")
def fetch_yc():
    """Fetch latest YC companies."""
    return {"data": yc.fetch_latest_batch()}


@app.get("/sources/producthunt")
def fetch_ph():
    """Fetch Product Hunt trending."""
    return {"data": producthunt.fetch_today_trending()}


@app.get("/sources/hackernews")
def fetch_hn():
    """Fetch Hacker News top stories."""
    return {"data": hackernews.fetch_top_stories()}


@app.get("/sources/vc_funding")
def fetch_vc():
    """Fetch recent VC funding."""
    return {"data": vc_funding.fetch_recent_funding()}


if __name__ == "__main__":
    import os
    import uvicorn
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)
