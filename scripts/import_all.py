"""
import_all.py — Import ALL episodes from all_transcripts.json into Supabase.

Safe to re-run — skips episodes already imported.

Usage:
    python scripts/import_all.py data/raw/all_transcripts.json
    python scripts/import_all.py data/raw/all_transcripts.json --dry-run
    python scripts/import_all.py data/raw/all_transcripts.json --clean
"""

import sys
import time
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.parser import load_all_episodes, parse_episode, parse_segments
from pipeline.importer import (
    episode_exists,
    insert_episode,
    insert_segments,
    upsert_speakers,
    log_pipeline_run,
    delete_all_episodes,
)

console = Console()


@click.command()
@click.argument("json_file", type=click.Path(exists=True))
@click.option("--dry-run", is_flag=True, default=False,
              help="Validate all episodes without writing to the database.")
@click.option("--clean", is_flag=True, default=False,
              help="Delete all existing data before importing. Use after a failed run.")
def main(json_file: str, dry_run: bool, clean: bool):
    """Import all episodes from a Transistor JSON file into Supabase."""

    console.print(Panel.fit(
        f"[bold cyan]Maffeo Vault — Bulk Importer[/]\n"
        f"File: [yellow]{json_file}[/]"
        + (" [dim](dry run)[/]" if dry_run else ""),
        border_style="cyan"
    ))

    # ── Optional clean wipe ───────────────────────────────────────────────────
    if clean and not dry_run:
        console.print("\n[bold yellow]--clean flag set: deleting all existing episodes...[/]")
        deleted = delete_all_episodes()
        console.print(f"  [green]✓[/] Deleted {deleted} episodes (segments removed via cascade)")

    # ── Load all episodes ─────────────────────────────────────────────────────
    console.print("\n[bold]Loading JSON...[/]")
    try:
        all_episodes = load_all_episodes(json_file)
    except Exception as e:
        console.print(f"[red]Failed to load file:[/] {e}")
        sys.exit(1)

    console.print(f"  [green]✓[/] Found [bold]{len(all_episodes)}[/] episodes\n")

    if dry_run:
        _dry_run_report(all_episodes)
        return

    # ── Process each episode (no nested progress bars) ────────────────────────
    results  = {"success": 0, "skipped": 0, "failed": 0}
    failures = []
    total    = len(all_episodes)

    for idx, raw in enumerate(all_episodes, start=1):
        ep_num = raw.get("episode_number")
        title  = raw.get("title", "Untitled")[:55]
        start  = time.time()

        console.print(f"[dim]({idx}/{total})[/] Ep {ep_num or 'N/A'} — {title}")

        # Skip episodes with no episode_number
        if ep_num is None:
            console.print(f"  [yellow]⟳ Skipped[/] — no episode_number in JSON")
            results["skipped"] += 1
            continue

        try:
            episode_data  = parse_episode(raw)
            transistor_id = episode_data["transistor_id"]

            if episode_exists(transistor_id):
                console.print(f"  [yellow]⟳ Skipped[/] — already in database")
                log_pipeline_run(transistor_id, ep_num, "skipped")
                results["skipped"] += 1
                continue

            # Insert episode record
            episode_id = insert_episode(episode_data)

            # Insert segments (no inner progress bar)
            segments = parse_segments(raw, episode_number=int(ep_num))
            inserted = insert_segments(segments, episode_id, show_progress=False)

            # Update speakers table
            upsert_speakers(segments, episode_id)

            duration = round(time.time() - start, 2)
            log_pipeline_run(transistor_id, ep_num, "success",
                             segment_count=inserted, duration_seconds=duration)

            console.print(f"  [green]✓[/] {inserted} segments — {duration}s")
            results["success"] += 1

        except Exception as e:
            duration = round(time.time() - start, 2)
            log_pipeline_run(str(ep_num), ep_num, "failed",
                             error_message=str(e), duration_seconds=duration)
            results["failed"] += 1
            failures.append({"episode": ep_num, "error": str(e)})
            console.print(f"  [red]✗ Failed:[/] {e}")

    # ── Final report ──────────────────────────────────────────────────────────
    border = "green" if results["failed"] == 0 else "yellow"
    console.print(Panel.fit(
        f"[bold green]Import complete![/]\n\n"
        f"[green]✓ Imported:[/]  {results['success']}\n"
        f"[yellow]⟳ Skipped:[/]  {results['skipped']} (already existed or no episode number)\n"
        f"[red]✗ Failed:[/]   {results['failed']}",
        border_style=border
    ))

    if failures:
        console.print("\n[bold red]Failed episodes:[/]")
        for f in failures:
            console.print(f"  Episode {f['episode']}: {f['error']}")

    console.print(
        "\n[dim]Next: python scripts/verify_episode.py --episode-number 1[/]"
    )


def _dry_run_report(all_episodes: list) -> None:
    table = Table(show_header=True, header_style="bold cyan", box=None, padding=(0, 3))
    table.add_column("Episode #", justify="right")
    table.add_column("Title")
    table.add_column("Segments", justify="right")

    total_segments = 0
    skipped_no_num = 0

    for raw in all_episodes:
        ep_num    = raw.get("episode_number")
        title     = raw.get("title", "Untitled")[:60]
        transcript = raw.get("transcript", {})
        segs      = transcript.get("segments", []) if isinstance(transcript, dict) else []
        seg_count = len([s for s in segs if s.get("body", "").strip()])
        total_segments += seg_count

        if ep_num is None:
            skipped_no_num += 1
            table.add_row("[yellow]None[/]", f"[yellow]{title}[/]", str(seg_count))
        else:
            table.add_row(str(ep_num), title, str(seg_count))

    console.print(table)
    console.print(f"\n[bold]Total episodes:[/]  {len(all_episodes)}")
    if skipped_no_num:
        console.print(f"[yellow]No episode_number:[/] {skipped_no_num} (will be skipped on import)")
    console.print(f"[bold]Total segments:[/]   {total_segments}")
    console.print("\n[yellow]Dry run — nothing written to database.[/]")
    console.print("Remove --dry-run to do the real import.")


if __name__ == "__main__":
    main()
