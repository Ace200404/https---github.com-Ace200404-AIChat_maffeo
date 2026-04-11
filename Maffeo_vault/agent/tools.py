"""
tools.py — The search tools the AI agent can call.

Each tool queries Supabase and returns formatted results with citations.
The agent decides which tools to use based on the user's question.

Tools:
  - semantic_search    → find segments by meaning (most used)
  - episode_lookup     → get full episode by number
  - speaker_search     → filter by speaker + topic
  - memory_recall      → search past conversations
"""

import os
import sys
from pathlib import Path
from typing import Optional

from langchain.tools import tool

sys.path.insert(0, str(Path(__file__).parent.parent))
from pipeline.config import get_supabase

# ── Embedding model (loaded once, reused across all tool calls) ───────────────
_model = None

def get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model


def _embed(text: str) -> list[float]:
    """Converts text to a vector using the local embedding model."""
    return get_model().encode(text, normalize_embeddings=True).tolist()


def _format_time(seconds) -> str:
    """Converts seconds to MM:SS format."""
    if seconds is None:
        return "00:00"
    try:
        m = int(float(seconds) // 60)
        s = int(float(seconds) % 60)
        return f"{m:02d}:{s:02d}"
    except (ValueError, TypeError):
        return "00:00"


def _format_segment(seg: dict) -> str:
    """Formats a segment into a citation string for the agent."""
    return (
        f"[Episode {seg.get('episode_number', '?')} | "
        f"{seg.get('speaker', 'Unknown')} | "
        f"{_format_time(seg.get('start_time'))}]\n"
        f"{seg.get('text', '')}"
    )


# ── Tool 1: Semantic Search ───────────────────────────────────────────────────

@tool
def semantic_search(query: str) -> str:
    """
    Search the podcast vault by meaning. Use this for most questions.
    Finds the most relevant segments across all episodes even if the
    exact words don't match. Returns segments with episode number,
    speaker name, and timestamp for citations.

    Args:
        query: The topic or question to search for.
    """
    try:
        db     = get_supabase()
        vector = _embed(query)

        result = db.rpc("match_segments", {
            "query_embedding": vector,
            "match_count":     8,
            "filter_speaker":  None,
        }).execute()

        if not result.data:
            return "No relevant segments found in the vault for this query."

        formatted = [_format_segment(seg) for seg in result.data]
        return "\n\n---\n\n".join(formatted)

    except Exception as e:
        return f"Search error: {str(e)}"


# ── Tool 2: Episode Lookup ────────────────────────────────────────────────────

@tool
def episode_lookup(episode_number: int) -> str:
    """
    Get the full transcript of a specific episode by its number.
    Use this when the user asks about a specific episode number,
    or when you need the full context of a particular episode.

    Args:
        episode_number: The episode number to retrieve.
    """
    try:
        db = get_supabase()

        # Get episode metadata
        ep_result = (
            db.table("episodes")
            .select("title, published_date, episode_number")
            .eq("episode_number", episode_number)
            .execute()
        )

        if not ep_result.data:
            return f"Episode {episode_number} not found in the vault."

        episode = ep_result.data[0]

        # Get all segments in order
        seg_result = (
            db.table("segments")
            .select("speaker, text, start_time")
            .eq("episode_number", episode_number)
            .order("start_time")
            .limit(50)   # first 50 segments to stay within context
            .execute()
        )

        if not seg_result.data:
            return f"Episode {episode_number} has no transcript segments."

        lines = [
            f"Episode {episode_number}: {episode['title']}",
            f"Published: {episode.get('published_date', 'Unknown')}",
            "",
        ]

        for seg in seg_result.data:
            lines.append(
                f"[{_format_time(seg['start_time'])}] "
                f"{seg['speaker']}: {seg['text']}"
            )

        return "\n".join(lines)

    except Exception as e:
        return f"Episode lookup error: {str(e)}"


# ── Tool 3: Speaker Search ────────────────────────────────────────────────────

@tool
def speaker_search(query: str) -> str:
    """
    Search for what a specific speaker said about a topic.
    The query should include the speaker name and the topic.
    Use this when the user asks specifically what Chris said,
    or what a particular guest said about something.

    Examples:
        "Chris Maffeo on distribution strategy"
        "what did guests say about brand building"

    Args:
        query: Speaker name and topic combined (e.g. "Chris Maffeo distribution")
    """
    try:
        db = get_supabase()

        # Extract speaker name — check for common patterns
        speaker = None
        search_query = query

        # Detect if a specific speaker is mentioned
        known_speakers_result = (
            db.table("speakers")
            .select("name")
            .order("total_segments", desc=True)
            .limit(20)
            .execute()
        )

        if known_speakers_result.data:
            for row in known_speakers_result.data:
                name = row["name"]
                if name.lower() in query.lower():
                    speaker = name
                    # Remove speaker name from search query
                    search_query = query.lower().replace(name.lower(), "").strip()
                    break

        # Fall back to "Chris Maffeo" if "chris" mentioned
        if not speaker and "chris" in query.lower():
            speaker = "Chris Maffeo"
            search_query = query.lower().replace("chris", "").strip()

        vector = _embed(search_query if search_query else query)

        result = db.rpc("match_segments", {
            "query_embedding": vector,
            "match_count":     8,
            "filter_speaker":  speaker,
        }).execute()

        if not result.data:
            msg = f"No results found"
            if speaker:
                msg += f" for speaker '{speaker}'"
            return msg + f" on topic: {query}"

        header = f"Results for: {query}"
        if speaker:
            header += f"\nFiltered to speaker: {speaker}"

        formatted = [_format_segment(seg) for seg in result.data]
        return header + "\n\n---\n\n" + "\n\n---\n\n".join(formatted)

    except Exception as e:
        return f"Speaker search error: {str(e)}"


# ── Tool 4: Memory Recall ─────────────────────────────────────────────────────

@tool
def memory_recall(query: str) -> str:
    """
    Search past conversations with Chris to find what was discussed before.
    Use this when the user references a previous conversation, asks if
    something was discussed before, or when context from past sessions
    would improve the answer.

    Args:
        query: Topic or question to search for in past conversations.
    """
    try:
        db     = get_supabase()
        vector = _embed(query)

        # Search conversations table using vector similarity
        result = db.rpc("match_conversations", {
            "query_embedding": vector,
            "match_count":     5,
        }).execute()

        if not result.data:
            return "No relevant past conversations found on this topic."

        lines = ["Relevant past conversations:\n"]
        for conv in result.data:
            date = str(conv.get("created_at", ""))[:10]
            role = conv.get("role", "unknown")
            content = conv.get("content", "")[:300]
            lines.append(f"[{date} | {role}]: {content}")

        return "\n\n".join(lines)

    except Exception as e:
        return f"Memory recall error: {str(e)}"
