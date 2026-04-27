"""
transistor_api.py — Fetches new episodes from the Transistor.fm API.

Handles:
  - Listing all published episodes with pagination
  - Downloading transcript JSON for each episode
  - Checking which episodes are already in the database

API docs: https://developers.transistor.fm
"""

import os
import sys
import time
from pathlib import Path
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from rich.console import Console

sys.path.insert(0, str(Path(__file__).parent.parent))
from pipeline.config import get_supabase

console = Console()

TRANSISTOR_API_BASE = "https://api.transistor.fm/v1"
PAGE_SIZE           = 10    # episodes per API page
PAGE_DELAY          = 1.5   # seconds between pages — stays under rate limit
MAX_RETRIES         = 3     # retries on 429/5xx


def get_api_key() -> str:
    """Returns the Transistor API key from environment."""
    key = os.getenv("TRANSISTOR_API_KEY")
    if not key:
        raise EnvironmentError(
            "TRANSISTOR_API_KEY not found in .env file.\n"
            "Add it: TRANSISTOR_API_KEY=your-key-here"
        )
    return key.strip()


def get_session() -> requests.Session:
    """Returns a requests Session with automatic retry on 5xx errors."""
    session = requests.Session()
    retry = Retry(
        total=MAX_RETRIES,
        backoff_factor=2,          # wait 2s, 4s, 8s between retries
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def get_headers() -> dict:
    return {"x-api-key": get_api_key()}


def fetch_all_published_episodes() -> list[dict]:
    """
    Fetches all published episodes from Transistor API.
    Paginates through all pages with rate-limit-safe delays.

    Returns a list of episode attribute dicts.
    """
    all_episodes = []
    page         = 1
    session      = get_session()

    while True:
        # Respect rate limits — Transistor allows ~10 req/min on free plans
        if page > 1:
            time.sleep(PAGE_DELAY)

        for attempt in range(MAX_RETRIES + 1):
            response = session.get(
                f"{TRANSISTOR_API_BASE}/episodes",
                headers=get_headers(),
                params={
                    "pagination[page]": page,
                    "pagination[per]":  PAGE_SIZE,
                },
                timeout=30,
            )

            if response.status_code == 429:
                wait = 10 * (attempt + 1)   # 10s, 20s, 30s
                console.print(f"  [yellow]Rate limited — waiting {wait}s...[/]")
                time.sleep(wait)
                continue

            response.raise_for_status()
            break
        else:
            raise RuntimeError(f"Page {page} failed after {MAX_RETRIES} retries (429)")

        data = response.json()

        episodes = data.get("data", [])
        if not episodes:
            break

        # Only include published episodes (skip drafts)
        for ep in episodes:
            attrs = ep.get("attributes", {})
            if attrs.get("status") == "published":
                all_episodes.append({
                    "transistor_id":       ep["id"],
                    "episode_number":      attrs.get("number"),
                    "title":               attrs.get("title"),
                    "published_at":        attrs.get("published_at"),
                    "duration":            attrs.get("duration"),
                    "transcript_json_url": _get_transcript_url(attrs),
                })

        meta        = data.get("meta", {})
        total_pages = meta.get("totalPages", 1)

        if page >= total_pages:
            break

        page += 1

    return all_episodes


def fetch_new_episodes() -> list[dict]:
    """
    Returns only episodes that are NOT already in the database.
    Deduplicates by episode_number (reliable across bulk imports and API imports).
    """
    db = get_supabase()

    # Get all episode numbers already in the database
    result = db.table("episodes").select("episode_number").execute()
    existing_numbers = {row["episode_number"] for row in result.data}

    # Fetch all published episodes from API
    all_episodes = fetch_all_published_episodes()

    # Filter to only new ones
    new_episodes = [
        ep for ep in all_episodes
        if ep.get("episode_number") not in existing_numbers
    ]

    return new_episodes


def fetch_transcript_json(transcript_url: str) -> Optional[dict]:
    """
    Downloads the transcript JSON from Transistor's CDN.
    Returns the parsed JSON or None if unavailable.
    """
    if not transcript_url:
        return None

    try:
        response = requests.get(transcript_url, timeout=30)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        console.print(f"  [yellow]Warning:[/] Could not fetch transcript: {e}")
        return None


def _get_transcript_url(attrs: dict) -> Optional[str]:
    """Extracts the JSON transcript URL from episode attributes."""
    transcripts = attrs.get("transcripts", [])
    for t in transcripts:
        if t.get("format") == "json":
            return t.get("url")
    return None
