"""
importer.py — Inserts a parsed episode into Supabase.

Separated from parser.py so each module has one job:
  - parser.py   → read & validate JSON
  - importer.py → write to database
"""

import time
from typing import Optional
from rich.console import Console

from pipeline.config import get_supabase, BATCH_SIZE

console = Console()


def episode_exists(transistor_id: str) -> bool:
    """Returns True if this episode is already in the database."""
    db = get_supabase()
    result = (
        db.table("episodes")
        .select("id")
        .eq("transistor_id", transistor_id)
        .execute()
    )
    return len(result.data) > 0


def insert_episode(episode_data: dict) -> int:
    """Inserts a single episode record and returns its new database ID."""
    db = get_supabase()
    result = db.table("episodes").insert(episode_data).execute()

    if not result.data:
        raise RuntimeError(
            f"Episode insert returned no data. "
            f"Transistor ID: {episode_data.get('transistor_id')}"
        )
    return result.data[0]["id"]


def insert_segments(segments: list[dict], episode_id: int, show_progress: bool = True) -> int:
    """
    Inserts all segments for an episode in batches.
    show_progress=False disables the per-batch print (used during bulk import
    so the outer progress bar isn't cluttered).
    """
    db = get_supabase()

    for seg in segments:
        seg["episode_id"] = episode_id

    batches = _chunk(segments, BATCH_SIZE)
    total_inserted = 0

    for i, batch in enumerate(batches):
        result = db.table("segments").insert(batch).execute()
        total_inserted += len(result.data)
        if show_progress:
            console.print(f"  Batch {i+1}/{len(batches)}: {len(result.data)} segments inserted")

    return total_inserted


def upsert_speakers(segments: list[dict], episode_id: int) -> None:
    """Ensures every speaker in this episode has a row in the speakers table."""
    db = get_supabase()
    unique_speakers = list({seg["speaker"] for seg in segments})

    for name in unique_speakers:
        count = sum(1 for s in segments if s["speaker"] == name)
        existing = (
            db.table("speakers")
            .select("id, total_segments")
            .eq("name", name)
            .execute()
        )

        if existing.data:
            current_total = existing.data[0]["total_segments"] or 0
            db.table("speakers").update({
                "total_segments": current_total + count
            }).eq("name", name).execute()
        else:
            db.table("speakers").insert({
                "name":             name,
                "total_segments":   count,
                "first_episode_id": episode_id,
                "is_host":          False,
            }).execute()


def log_pipeline_run(
    transistor_id: str,
    episode_number: Optional[int],
    status: str,
    segment_count: int = 0,
    error_message: Optional[str] = None,
    duration_seconds: Optional[float] = None,
) -> None:
    """Records the result of a pipeline run in pipeline_logs."""
    try:
        db = get_supabase()
        db.table("pipeline_logs").insert({
            "transistor_id":    transistor_id,
            "episode_number":   episode_number,
            "status":           status,
            "segment_count":    segment_count,
            "error_message":    error_message,
            "duration_seconds": duration_seconds,
        }).execute()
    except Exception:
        pass  # logging failure should never crash the pipeline


def delete_episode(transistor_id: str) -> bool:
    """
    Removes an episode and all its segments (via CASCADE).
    Returns True if the episode was found and deleted.
    """
    db = get_supabase()
    result = (
        db.table("episodes")
        .delete()
        .eq("transistor_id", transistor_id)
        .execute()
    )
    return len(result.data) > 0


def delete_all_episodes() -> int:
    """
    Deletes ALL episodes and segments. Used to clean up a bad bulk import.
    Returns the number of episodes deleted.
    """
    db = get_supabase()
    result = db.table("episodes").delete().neq("id", 0).execute()
    return len(result.data)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _chunk(lst: list, size: int) -> list[list]:
    return [lst[i : i + size] for i in range(0, len(lst), size)]
