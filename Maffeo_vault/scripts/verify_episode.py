"""
verify_episode.py — Check an imported episode's data quality.

Run this after import_episode.py to confirm everything looks right
before moving on to the next episode.

Usage:
    python scripts/verify_episode.py --episode-number 45
    python scripts/verify_episode.py --transistor-id abc123
    python scripts/verify_episode.py        (checks the most recent import)
"""

import sys
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

sys.path.insert(0, str(Path(__file__).parent.parent))
from pipeline.config import get_supabase

console = Console()


@click.command()
@click.option("--episode-number", "-n", type=int, default=None, help="Episode number to verify")
@click.option("--transistor-id",  "-t", type=str, default=None, help="Transistor ID to verify")
def main(episode_number, transistor_id):
    """Verify an imported episode's data quality."""

    db = get_supabase()

    # ── Find the episode ──────────────────────────────────────────────────────
    if episode_number:
        result = db.table("episodes").select("*").eq("episode_number", episode_number).execute()
    elif transistor_id:
        result = db.table("episodes").select("*").eq("transistor_id", transistor_id).execute()
    else:
        # Default: most recently imported episode
        result = db.table("episodes").select("*").order("created_at", desc=True).limit(1).execute()

    if not result.data:
        console.print("[red]Episode not found.[/] Have you imported it yet?")
        sys.exit(1)

    episode = result.data[0]
    ep_id   = episode["id"]

    console.print(Panel.fit(
        f"[bold cyan]Verifying:[/] {episode['title']}\n"
        f"Episode #{episode.get('episode_number', '?')} · ID: {ep_id}",
        border_style="cyan"
    ))

    # ── Check 1: Segment count ────────────────────────────────────────────────
    segs_result = db.table("segments").select("*", count="exact").eq("episode_id", ep_id).execute()
    seg_count = segs_result.count or len(segs_result.data)
    console.print(f"\n[bold]Segments total:[/] {seg_count}")
    if seg_count == 0:
        console.print("[red]✗ No segments found — import may have failed.[/]")
        sys.exit(1)
    console.print(f"  [green]✓[/] {seg_count} segments present")

    # ── Check 2: Speaker breakdown ────────────────────────────────────────────
    segs = segs_result.data
    speaker_counts: dict = {}
    for s in segs:
        speaker_counts[s["speaker"]] = speaker_counts.get(s["speaker"], 0) + 1

    console.print("\n[bold]Speaker breakdown:[/]")
    sp_table = Table(show_header=True, header_style="bold", box=None, padding=(0, 3))
    sp_table.add_column("Speaker")
    sp_table.add_column("Segments", justify="right")
    sp_table.add_column("Words",    justify="right")

    for speaker, count in sorted(speaker_counts.items(), key=lambda x: -x[1]):
        words = sum(s.get("word_count", 0) or 0 for s in segs if s["speaker"] == speaker)
        sp_table.add_row(speaker, str(count), str(words))
    console.print(sp_table)

    # ── Check 3: Empty text ───────────────────────────────────────────────────
    empty = [s for s in segs if not s.get("text", "").strip()]
    if empty:
        console.print(f"\n[yellow]⚠  {len(empty)} segments have empty text[/]")
    else:
        console.print("\n  [green]✓[/] No empty segments")

    # ── Check 4: Missing timestamps ───────────────────────────────────────────
    missing_times = [s for s in segs if s.get("start_time") is None]
    if missing_times:
        console.print(f"  [yellow]⚠  {len(missing_times)} segments missing timestamps[/]")
    else:
        console.print("  [green]✓[/] All segments have timestamps")

    # ── Preview: First 5 segments ─────────────────────────────────────────────
    console.print("\n[bold]First 5 segments (preview):[/]")
    ordered = sorted(segs, key=lambda s: s.get("start_time") or 0)
    preview_table = Table(show_header=True, header_style="dim", box=None, padding=(0, 2))
    preview_table.add_column("Time",    style="dim",    width=8)
    preview_table.add_column("Speaker", style="cyan",   width=16)
    preview_table.add_column("Text",    style="white",  width=60)

    for seg in ordered[:5]:
        t = seg.get("start_time")
        time_str = _format_time(t) if t is not None else "—"
        text_preview = (seg["text"][:80] + "...") if len(seg["text"]) > 80 else seg["text"]
        preview_table.add_row(time_str, seg["speaker"], text_preview)
    console.print(preview_table)

    console.print(Panel.fit(
        "[bold green]✓ Verification complete[/]\n\n"
        "If everything looks correct, import the next episode or\n"
        "proceed to the batch import script.",
        border_style="green"
    ))


def _format_time(seconds: float) -> str:
    """Converts seconds to MM:SS format."""
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m:02d}:{s:02d}"


if __name__ == "__main__":
    main()
