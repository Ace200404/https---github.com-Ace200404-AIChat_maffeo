"""
import_episode.py — Import a single episode JSON file into Supabase.

This is the script you run manually during Phase 1.
In Phase 2, the pipeline will call these same functions automatically.

Usage:
    python scripts/import_episode.py data/raw/episode_45.json
    python scripts/import_episode.py data/raw/episode_45.json --dry-run
    python scripts/import_episode.py data/raw/episode_45.json --inspect
"""

import sys
import time
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# Add project root to path so we can import our modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.parser import load_json, parse_episode, parse_segments, inspect_json
from pipeline.importer import (
    episode_exists,
    insert_episode,
    insert_segments,
    upsert_speakers,
    log_pipeline_run,
)

console = Console()


@click.command()
@click.argument("json_file", type=click.Path(exists=True))
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Parse and validate the JSON without writing to the database.",
)
@click.option(
    "--inspect",
    is_flag=True,
    default=False,
    help="Print the JSON structure and exit — use this with a new file format.",
)
def main(json_file: str, dry_run: bool, inspect: bool):
    """
    Import a Transistor.fm episode JSON file into Supabase.

    JSON_FILE: path to the .json transcript file
    """

    # ── Inspect mode ─────────────────────────────────────────────────────────
    if inspect:
        inspect_json(json_file)
        return

    console.print(Panel.fit(
        f"[bold cyan]Maffeo Vault — Episode Importer[/]\n"
        f"File: [yellow]{json_file}[/]"
        + (" [dim](dry run)[/]" if dry_run else ""),
        border_style="cyan"
    ))

    start_time = time.time()

    # ── Step 1: Load and parse JSON ───────────────────────────────────────────
    console.print("\n[bold]Step 1:[/] Loading JSON...")
    try:
        raw = load_json(json_file)
        episode_data = parse_episode(raw)
        segments     = parse_segments(raw, episode_number=episode_data.get("episode_number"))
    except (FileNotFoundError, ValueError) as e:
        console.print(f"\n[bold red]Parse error:[/] {e}")
        sys.exit(1)

    # Show what we found
    _print_episode_summary(episode_data, segments)

    if dry_run:
        console.print("\n[bold yellow]Dry run complete — nothing written to database.[/]")
        return

    # ── Step 2: Check for duplicate ──────────────────────────────────────────
    console.print("\n[bold]Step 2:[/] Checking for duplicates...")
    transistor_id = episode_data["transistor_id"]

    try:
        if episode_exists(transistor_id):
            console.print(
                f"[yellow]Skipped:[/] Episode '{transistor_id}' is already in the database.\n"
                "To re-import, first delete it with: python scripts/delete_episode.py {transistor_id}"
            )
            log_pipeline_run(
                transistor_id=transistor_id,
                episode_number=episode_data.get("episode_number"),
                status="skipped",
            )
            return
        console.print("  [green]✓[/] No duplicate found — safe to import.")
    except Exception as e:
        console.print(f"\n[bold red]Database error checking for duplicate:[/] {e}")
        console.print("Is your .env file configured? Run: python scripts/test_connection.py")
        sys.exit(1)

    # ── Step 3: Insert episode ────────────────────────────────────────────────
    console.print("\n[bold]Step 3:[/] Inserting episode record...")
    try:
        episode_id = insert_episode(episode_data)
        console.print(f"  [green]✓[/] Episode inserted — database ID: {episode_id}")
    except Exception as e:
        console.print(f"\n[bold red]Failed to insert episode:[/] {e}")
        log_pipeline_run(
            transistor_id=transistor_id,
            episode_number=episode_data.get("episode_number"),
            status="failed",
            error_message=str(e),
        )
        sys.exit(1)

    # ── Step 4: Insert segments ───────────────────────────────────────────────
    console.print(f"\n[bold]Step 4:[/] Inserting {len(segments)} segments...")
    try:
        inserted_count = insert_segments(segments, episode_id)
        console.print(f"  [green]✓[/] {inserted_count} segments inserted.")
    except Exception as e:
        console.print(f"\n[bold red]Failed to insert segments:[/] {e}")
        console.print("[yellow]Rolling back episode record...[/]")
        from pipeline.importer import delete_episode
        delete_episode(transistor_id)
        log_pipeline_run(
            transistor_id=transistor_id,
            episode_number=episode_data.get("episode_number"),
            status="failed",
            error_message=str(e),
        )
        sys.exit(1)

    # ── Step 5: Upsert speakers ───────────────────────────────────────────────
    console.print("\n[bold]Step 5:[/] Updating speakers table...")
    try:
        upsert_speakers(segments, episode_id)
        unique_speakers = list({s["speaker"] for s in segments})
        console.print(f"  [green]✓[/] Speakers updated: {', '.join(unique_speakers)}")
    except Exception as e:
        # Non-fatal — speakers table is supplementary
        console.print(f"  [yellow]Warning:[/] Speakers table update failed: {e}")

    # ── Done ──────────────────────────────────────────────────────────────────
    duration = round(time.time() - start_time, 2)
    log_pipeline_run(
        transistor_id=transistor_id,
        episode_number=episode_data.get("episode_number"),
        status="success",
        segment_count=inserted_count,
        duration_seconds=duration,
    )

    console.print(Panel.fit(
        f"[bold green]✓ Import complete![/]\n\n"
        f"Episode:  {episode_data['title']}\n"
        f"Segments: {inserted_count}\n"
        f"Duration: {duration}s",
        border_style="green"
    ))

    console.print(
        "\n[dim]Next step — run these verification queries in Supabase SQL Editor:[/]\n"
        "  SELECT speaker, COUNT(*) FROM segments "
        f"WHERE episode_id = {episode_id} GROUP BY speaker;\n"
        f"  SELECT * FROM segments WHERE episode_id = {episode_id} "
        "ORDER BY start_time LIMIT 10;"
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _print_episode_summary(episode_data: dict, segments: list) -> None:
    """Prints a formatted summary of what was parsed."""

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Key",   style="dim")
    table.add_column("Value", style="cyan")

    table.add_row("Title",          episode_data.get("title", "—"))
    table.add_row("Episode number", str(episode_data.get("episode_number", "—")))
    table.add_row("Transistor ID",  episode_data.get("transistor_id", "—"))
    table.add_row("Published",      episode_data.get("published_date", "—"))
    table.add_row("Segments found", str(len(segments)))

    # Show unique speakers
    speakers = list({s["speaker"] for s in segments})
    table.add_row("Speakers",       ", ".join(speakers))

    console.print("\n  Parsed successfully:")
    console.print(table)


if __name__ == "__main__":
    main()
