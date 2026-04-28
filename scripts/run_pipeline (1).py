"""
run_pipeline.py — Full end-to-end pipeline for new episodes.

Fetches new episodes from Transistor API, imports them into Supabase,
and generates embeddings. Run manually or via GitHub Actions.

Usage:
    python scripts/run_pipeline.py              # process new episodes only
    python scripts/run_pipeline.py --dry-run    # check what's new without importing
"""

import sys
import time
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.transistor_api import fetch_new_episodes, fetch_transcript_json
from pipeline.parser import parse_episode, parse_segments
from pipeline.importer import (
    episode_exists,
    insert_episode,
    insert_segments,
    upsert_speakers,
    log_pipeline_run,
)

console = Console()


@click.command()
@click.option("--dry-run", is_flag=True, default=False,
              help="Check for new episodes without importing.")
def main(dry_run: bool):
    """Fetch and import new episodes from Transistor.fm into the vault."""

    console.print(Panel.fit(
        "[bold cyan]Maffeo Vault — Weekly Pipeline[/]\n"
        "Checking Transistor.fm for new episodes..."
        + (" [dim](dry run)[/]" if dry_run else ""),
        border_style="cyan"
    ))

    # ── Step 1: Check for new episodes ───────────────────────────────────────
    console.print("\n[bold]Step 1:[/] Fetching episode list from Transistor API...")
    try:
        new_episodes = fetch_new_episodes()
    except Exception as e:
        console.print(f"[red]Failed to fetch from Transistor API:[/] {e}")
        sys.exit(1)

    if not new_episodes:
        console.print(Panel.fit(
            "[green]✓ Vault is up to date![/]\n"
            "No new episodes found.",
            border_style="green"
        ))
        return

    console.print(f"  [green]✓[/] Found [bold]{len(new_episodes)}[/] new episode(s):\n")
    for ep in new_episodes:
        console.print(
            f"  Ep {ep.get('episode_number', '?')} — "
            f"{ep.get('title', 'Untitled')[:60]}"
        )

    if dry_run:
        console.print("\n[yellow]Dry run — nothing imported.[/]")
        return

    # ── Step 2: Import each new episode ──────────────────────────────────────
    console.print(f"\n[bold]Step 2:[/] Importing {len(new_episodes)} episode(s)...")

    results  = {"success": 0, "failed": 0, "no_transcript": 0}
    imported_ids = []
    total    = len(new_episodes)

    for idx, ep in enumerate(new_episodes, start=1):
        ep_num        = ep.get("episode_number", "?")
        transistor_id = ep["transistor_id"]
        title         = ep.get("title", "Untitled")[:55]
        start         = time.time()

        console.print(f"\n[dim]({idx}/{total})[/] Ep {ep_num} — {title}")

        # Fetch the transcript JSON
        transcript_url = ep.get("transcript_json_url")
        if not transcript_url:
            console.print(f"  [yellow]⟳ Skipped[/] — no transcript available yet")
            results["no_transcript"] += 1
            continue

        console.print(f"  Fetching transcript...")
        raw_transcript = fetch_transcript_json(transcript_url)

        if not raw_transcript:
            console.print(f"  [yellow]⟳ Skipped[/] — transcript download failed")
            results["no_transcript"] += 1
            continue

        # Build the episode dict the parser expects
        # Transistor API transcript JSON may differ from bulk export format
        # We normalise it here
        raw = _normalise_transcript(ep, raw_transcript)

        try:
            # Parse
            episode_data = parse_episode(raw)
            segments     = parse_segments(raw, episode_number=ep_num)

            # Insert episode
            episode_id = insert_episode(episode_data)

            # Insert segments
            inserted = insert_segments(segments, episode_id, show_progress=False)

            # Update speakers
            upsert_speakers(segments, episode_id)

            duration = round(time.time() - start, 2)
            log_pipeline_run(transistor_id, ep_num, "success",
                             segment_count=inserted, duration_seconds=duration)

            console.print(f"  [green]✓[/] {inserted} segments — {duration}s")
            results["success"] += 1
            imported_ids.append(episode_id)

        except Exception as e:
            duration = round(time.time() - start, 2)
            log_pipeline_run(transistor_id, ep_num, "failed",
                             error_message=str(e), duration_seconds=duration)
            results["failed"] += 1
            console.print(f"  [red]✗ Failed:[/] {e}")

    # ── Step 3: Generate embeddings for new segments ──────────────────────────
    if imported_ids and results["success"] > 0:
        console.print(f"\n[bold]Step 3:[/] Generating embeddings for new segments...")
        try:
            from sentence_transformers import SentenceTransformer
            from pipeline.config import get_supabase

            db    = get_supabase()
            model = SentenceTransformer("all-MiniLM-L6-v2")

            # Fetch segments without embeddings for newly imported episodes
            result = (
                db.table("segments")
                .select("id, text")
                .in_("episode_id", imported_ids)
                .is_("embedding", "null")
                .execute()
            )

            segments_to_embed = result.data
            console.print(f"  Embedding {len(segments_to_embed)} new segments...")

            for seg in segments_to_embed:
                vector = model.encode(
                    seg["text"],
                    normalize_embeddings=True
                ).tolist()
                db.table("segments").update({
                    "embedding": vector
                }).eq("id", seg["id"]).execute()

            console.print(f"  [green]✓[/] Embeddings generated")

        except Exception as e:
            console.print(f"  [yellow]Warning:[/] Embedding failed: {e}")
            console.print("  Run: python scripts/generate_embeddings.py")

    # ── Summary ───────────────────────────────────────────────────────────────
    console.print(Panel.fit(
        f"[bold green]Pipeline complete![/]\n\n"
        f"[green]✓ Imported:[/]       {results['success']}\n"
        f"[yellow]⟳ No transcript:[/] {results['no_transcript']}\n"
        f"[red]✗ Failed:[/]         {results['failed']}",
        border_style="green" if results["failed"] == 0 else "yellow"
    ))


def _normalise_transcript(ep: dict, raw_transcript) -> dict:
    """
    Normalises the Transistor API transcript format to match
    what our parser expects.

    The API transcript JSON format may differ from the bulk export.
    This function bridges the two.
    """
    # If raw_transcript is already a list (bulk export format), wrap it
    if isinstance(raw_transcript, list):
        # Find the matching episode dict if present
        for item in raw_transcript:
            if str(item.get("episode_number")) == str(ep.get("episode_number")):
                return item
        return raw_transcript[0] if raw_transcript else {}

    # If it's a dict, check if it has segments directly or nested
    if isinstance(raw_transcript, dict):
        # Already has transcript key — return as-is with episode metadata added
        if "transcript" in raw_transcript or "segments" in raw_transcript:
            raw_transcript["episode_number"] = ep.get("episode_number")
            raw_transcript["title"]          = ep.get("title")
            raw_transcript["id"]             = ep.get("transistor_id")
            return raw_transcript

    # Fallback: wrap in expected structure
    return {
        "episode_number": ep.get("episode_number"),
        "title":          ep.get("title"),
        "id":             ep.get("transistor_id"),
        "transcript":     raw_transcript,
    }


if __name__ == "__main__":
    main()
