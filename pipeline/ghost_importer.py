"""
ghost_importer.py — Parses Ghost articles into chunks and stores them in Supabase.

Each article is split into ~250-word paragraph chunks. Chunks are stored in
the shared segments table with source='article', so semantic_search finds
both podcast segments and article chunks in one query.
"""

import re
from rich.console import Console

from pipeline.config import get_supabase, BATCH_SIZE

console = Console()

CHUNK_MAX_WORDS = 250  # target words per chunk


def article_exists(ghost_id: str) -> bool:
    db = get_supabase()
    result = db.table("articles").select("id").eq("ghost_id", ghost_id).execute()
    return len(result.data) > 0


def insert_article(post: dict) -> int:
    """Inserts an article row and returns its new database ID."""
    db = get_supabase()
    result = db.table("articles").insert({
        "ghost_id":     post["ghost_id"],
        "title":        post["title"],
        "slug":         post["slug"],
        "published_at": post["published_at"],
        "author":       post["author"],
        "tags":         post["tags"],
        "url":          post["url"],
    }).execute()
    if not result.data:
        raise RuntimeError(f"Article insert returned no data: {post['ghost_id']}")
    return result.data[0]["id"]


def chunk_article(post: dict, article_id: int) -> list[dict]:
    """
    Splits article plaintext into embeddable chunks.
    Groups paragraphs up to CHUNK_MAX_WORDS, then starts a new chunk.
    start_time is reused as a chunk index for ordering.
    """
    text = (post.get("plaintext") or "").strip()
    if not text:
        return []

    paragraphs = [p.strip() for p in re.split(r"\n\n+", text) if p.strip()]

    chunks        = []
    current_paras = []
    current_words = 0
    chunk_index   = 0

    for para in paragraphs:
        word_count = len(para.split())

        if current_words + word_count > CHUNK_MAX_WORDS and current_paras:
            chunks.append(_make_segment(post, article_id, current_paras, chunk_index))
            chunk_index  += 1
            current_paras = [para]
            current_words = word_count
        else:
            current_paras.append(para)
            current_words += word_count

    if current_paras:
        chunks.append(_make_segment(post, article_id, current_paras, chunk_index))

    return chunks


def insert_article_segments(segments: list[dict]) -> int:
    """Inserts article chunks into the shared segments table in batches."""
    db = get_supabase()
    batches = [segments[i:i + BATCH_SIZE] for i in range(0, len(segments), BATCH_SIZE)]
    total = 0
    for batch in batches:
        result = db.table("segments").insert(batch).execute()
        total += len(result.data)
    return total


def _make_segment(post: dict, article_id: int, paras: list[str], index: int) -> dict:
    return {
        "article_id":    article_id,
        "article_title": post["title"],
        "article_url":   post["url"],
        "episode_id":    None,
        "episode_number": None,
        "speaker":       post["author"],
        "text":          "\n\n".join(paras),
        "start_time":    float(index),
        "source":        "article",
    }
