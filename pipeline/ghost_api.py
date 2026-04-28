"""
ghost_api.py — Fetches articles from the Ghost Admin API.

Uses the Admin API (not Content API) so members-only post bodies are accessible.
API docs: https://ghost.org/docs/admin-api/
"""

import os
import sys
import time
import datetime
from pathlib import Path

import jwt
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from rich.console import Console

sys.path.insert(0, str(Path(__file__).parent.parent))
from pipeline.config import get_supabase

console = Console()

MAX_RETRIES = 3


def get_credentials() -> tuple[str, str, str]:
    """Returns (ghost_url, content_api_key, admin_api_key)."""
    url       = os.getenv("GHOST_URL", "").rstrip("/")
    admin_key = os.getenv("GHOST_ADMIN_KEY", "").strip()
    if not url or not admin_key:
        raise EnvironmentError(
            "GHOST_URL and GHOST_ADMIN_KEY not found in .env file.\n"
            "Get the Admin API key from: Ghost dashboard → Settings → Integrations\n"
            "  GHOST_URL=https://yourdomain.ghost.io\n"
            "  GHOST_ADMIN_KEY=your-id:your-secret"
        )
    return url, admin_key


def _make_jwt(admin_key: str) -> str:
    """Generates a short-lived JWT for Ghost Admin API authentication."""
    key_id, secret = admin_key.split(":")
    iat = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
    payload = {
        "iat": iat,
        "exp": iat + 300,   # valid for 5 minutes
        "aud": "/admin/",
    }
    token = jwt.encode(
        payload,
        bytes.fromhex(secret),
        algorithm="HS256",
        headers={"kid": key_id},
    )
    return token


def get_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=MAX_RETRIES,
        backoff_factor=2,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def fetch_all_published_posts() -> list[dict]:
    """
    Fetches all published posts from Ghost Admin API.
    Admin API bypasses members-only restrictions so body content is always returned.
    """
    ghost_url, admin_key = get_credentials()
    token   = _make_jwt(admin_key)
    session = get_session()

    response = session.get(
        f"{ghost_url}/ghost/api/admin/posts/",
        headers={"Authorization": f"Ghost {token}"},
        params={
            "include": "tags,authors",
            "formats": "plaintext",
            "limit":   "all",
            "order":   "published_at asc",
            "filter":  "status:published",
        },
        timeout=60,
    )
    response.raise_for_status()
    data = response.json()

    posts = []
    for post in data.get("posts", []):
        posts.append({
            "ghost_id":     post["id"],
            "title":        post.get("title", "Untitled"),
            "slug":         post.get("slug", ""),
            "published_at": post.get("published_at"),
            "author":       _extract_author(post),
            "tags":         _extract_tags(post),
            "url":          post.get("url", ""),
            "plaintext":    post.get("plaintext", "") or "",
        })

    return posts


def fetch_new_posts() -> list[dict]:
    """Returns posts not already in the articles table."""
    db = get_supabase()
    result = db.table("articles").select("ghost_id").execute()
    existing_ids = {row["ghost_id"] for row in result.data}

    all_posts = fetch_all_published_posts()
    return [p for p in all_posts if p["ghost_id"] not in existing_ids]


def _extract_author(post: dict) -> str:
    authors = post.get("authors", [])
    if authors:
        return authors[0].get("name", "Chris Maffeo")
    return "Chris Maffeo"


def _extract_tags(post: dict) -> list[str]:
    return [t["name"] for t in post.get("tags", []) if t.get("name")]
