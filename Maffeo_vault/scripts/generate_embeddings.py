"""
generate_embeddings.py — Generate vector embeddings for all segments.

Runs a local AI model (no API cost) that converts each segment's text
into a 384-dimension vector. Paginates through ALL segments in Supabase
(fixes the 1000-row default limit).

Usage:
    python scripts/generate_embeddings.py             # embed all missing
    python scripts/generate_embeddings.py --reset     # re-embed everything
    python scripts/generate_embeddings.py --test      # test search only
"""

import sys
import time
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, BarColumn, TaskProgressColumn, TimeRemainingColumn

sys.path.insert(0, str(Path(__file__).parent.parent))
from pipeline.config import get_supabase

console = Console()

EMBED_BATCH_SIZE  = 64   # segments encoded at once (memory vs speed)
UPLOAD_BATCH_SIZE = 50   # vectors uploaded to Supabase at once
PAGE_SIZE         = 1000 # rows fetched per Supabase page


def fetch_all_segments_without_embeddings(db) -> list:
    """
    Fetches ALL segments missing embeddings using pagination.
    Supabase returns max 1000 rows per request — this loops until done.
    """
    all_segments = []
    offset = 0

    while True:
        result = (
            db.table("segments")
            .select("id, text, episode_number, speaker")
            .is_("embedding", "null")
            .range(offset, offset + PAGE_SIZE - 1)
            .execute()
        )

        batch = result.data
        if not batch:
            break

        all_segments.extend(batch)
        console.print(f"  Fetched {len(all_segments)} so far...", end="\r")

        if len(batch) < PAGE_SIZE:
            break  # last page

        offset += PAGE_SIZE

    return all_segments


@click.command()
@click.option("--reset", is_flag=True, default=False,
              help="Clear all existing embeddings and re-generate from scratch.")
@click.option("--test", is_flag=True, default=False,
              help="Run a test search after embedding to verify everything works.")
def main(reset: bool, test: bool):
    """Generate embeddings for all segments that don't have one yet."""

    console.print(Panel.fit(
        "[bold cyan]Maffeo Vault — Embedding Generator[/]\n"
        "Model: all-MiniLM-L6-v2 (runs locally, no API cost)",
        border_style="cyan"
    ))

    db = get_supabase()

    # ── Optional reset ────────────────────────────────────────────────────────
    if reset:
        console.print("\n[yellow]--reset: clearing all existing embeddings...[/]")
        # Paginate deletes too — Supabase update also has a row limit
        offset = 0
        cleared = 0
        while True:
            result = (
                db.table("segments")
                .select("id")
                .not_.is_("embedding", "null")
                .range(offset, offset + PAGE_SIZE - 1)
                .execute()
            )
            if not result.data:
                break
            ids = [r["id"] for r in result.data]
            db.table("segments").update({"embedding": None}).in_("id", ids).execute()
            cleared += len(ids)
            console.print(f"  Cleared {cleared}...", end="\r")
            if len(result.data) < PAGE_SIZE:
                break
            offset += PAGE_SIZE
        console.print(f"  [green]✓[/] Cleared {cleared} embeddings")

    # ── Fetch segments that need embeddings ───────────────────────────────────
    console.print("\n[bold]Fetching all segments without embeddings...[/]")
    segments = fetch_all_segments_without_embeddings(db)
    console.print(f"\n  [green]✓[/] {len(segments)} segments need embedding\n")

    if not segments:
        console.print("  [green]✓[/] All segments already have embeddings!")
        if test:
            _run_test_search(db)
        return

    # ── Load the embedding model ──────────────────────────────────────────────
    console.print("[bold]Loading embedding model...[/]")
    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("all-MiniLM-L6-v2")
        console.print("  [green]✓[/] Model loaded\n")
    except ImportError:
        console.print("[red]sentence-transformers not installed.[/]")
        console.print("Run: pip install sentence-transformers torch")
        sys.exit(1)

    # ── Generate and upload embeddings ────────────────────────────────────────
    total      = len(segments)
    done       = 0
    failed     = 0
    start_time = time.time()
    batches    = _chunk(segments, EMBED_BATCH_SIZE)

    with Progress(
        SpinnerColumn(),
        "[progress.description]{task.description}",
        BarColumn(),
        TaskProgressColumn(),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Embedding segments...", total=total)

        for batch in batches:
            texts = [seg["text"] for seg in batch]

            try:
                vectors = model.encode(
                    texts,
                    batch_size=EMBED_BATCH_SIZE,
                    show_progress_bar=False,
                    normalize_embeddings=True,
                )
            except Exception as e:
                console.print(f"\n[red]Embedding failed for batch:[/] {e}")
                failed += len(batch)
                progress.advance(task, len(batch))
                continue

            # Upload each vector individually (most reliable)
            for seg, vector in zip(batch, vectors):
                try:
                    db.table("segments").update({
                        "embedding": vector.tolist()
                    }).eq("id", seg["id"]).execute()
                    done += 1
                except Exception as e:
                    console.print(f"\n[red]Upload failed for segment {seg['id']}:[/] {e}")
                    failed += 1

            progress.advance(task, len(batch))

    # ── Summary ───────────────────────────────────────────────────────────────
    elapsed = round(time.time() - start_time)
    mins    = elapsed // 60
    secs    = elapsed % 60

    console.print(Panel.fit(
        f"[bold green]Embedding complete![/]\n\n"
        f"[green]✓ Embedded:[/]  {done}\n"
        f"[red]✗ Failed:[/]   {failed}\n"
        f"[dim]Time taken:[/]  {mins}m {secs}s",
        border_style="green" if failed == 0 else "yellow"
    ))

    if test or done > 0:
        _run_test_search(db)


def _run_test_search(db) -> None:
    """Tests semantic search by running real queries against the vault."""
    console.print("\n[bold]Testing semantic search...[/]")

    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("all-MiniLM-L6-v2")
    except ImportError:
        console.print("[yellow]Cannot test — sentence-transformers not installed[/]")
        return

    test_queries = [
        "building a drinks brand from scratch",
        "distribution strategy for small brands",
        "what makes a great bar ambassador",
    ]

    for query in test_queries:
        console.print(f"\n  Query: [cyan]\"{query}\"[/]")
        vector = model.encode(query, normalize_embeddings=True).tolist()

        try:
            result = db.rpc("match_segments", {
                "query_embedding": vector,
                "match_count":     3,
                "filter_speaker":  None,
            }).execute()

            if not result.data:
                console.print("  [yellow]No results — embeddings may still be processing[/]")
                continue

            for r in result.data:
                similarity = round(r["similarity"] * 100, 1)
                preview    = r["text"][:80].replace("\n", " ")
                console.print(
                    f"  [green]{similarity}%[/] · "
                    f"Ep {r['episode_number']} · "
                    f"[cyan]{r['speaker']}[/] · "
                    f"{preview}..."
                )
        except Exception as e:
            console.print(f"  [red]Search failed:[/] {e}")

    console.print("\n[dim]Semantic search working. Ready for Phase 3: AI Agent.[/]")


def _chunk(lst: list, size: int) -> list:
    return [lst[i : i + size] for i in range(0, len(lst), size)]


if __name__ == "__main__":
    main()
