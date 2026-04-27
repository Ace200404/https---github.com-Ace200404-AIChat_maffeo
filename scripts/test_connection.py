"""
test_connection.py — Verify your Supabase connection and schema.

Run this FIRST before anything else.

Usage:
    python scripts/test_connection.py
"""

import sys
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

sys.path.insert(0, str(Path(__file__).parent.parent))
from pipeline.config import get_supabase

console = Console()
REQUIRED_TABLES = ["episodes", "segments", "speakers", "pipeline_logs"]

def main():
    console.print(Panel.fit("[bold cyan]Maffeo Vault — Connection Test[/]", border_style="cyan"))

    console.print("\n[bold]Test 1:[/] Loading credentials from .env...")
    try:
        db = get_supabase()
        console.print("  [green]✓[/] Credentials loaded.")
    except EnvironmentError as e:
        console.print(f"  [red]✗[/] {e}")
        sys.exit(1)

    console.print("\n[bold]Test 2:[/] Connecting to Supabase...")
    try:
        db.table("episodes").select("id").limit(1).execute()
        console.print("  [green]✓[/] Connection successful.")
    except Exception as e:
        if "does not exist" in str(e):
            console.print("  [yellow]⚠[/]  Connected but tables missing — run sql/schema.sql first.")
        else:
            console.print(f"  [red]✗[/] {e}")
        sys.exit(1)

    console.print("\n[bold]Test 3:[/] Checking required tables...")
    all_ok = True
    for t in REQUIRED_TABLES:
        try:
            db.table(t).select("id").limit(1).execute()
            console.print(f"  [green]✓[/] {t}")
        except Exception:
            console.print(f"  [red]✗[/] {t} — missing")
            all_ok = False
    if not all_ok:
        console.print("\n  Fix: Supabase → SQL Editor → paste sql/schema.sql → Run")
        sys.exit(1)

    console.print("\n[bold]Test 4:[/] Current row counts...")
    tbl = Table(show_header=True, header_style="bold cyan", box=None, padding=(0,3))
    tbl.add_column("Table")
    tbl.add_column("Rows", justify="right")
    for t in ["episodes", "segments", "speakers"]:
        try:
            r = db.table(t).select("*", count="exact").execute()
            tbl.add_row(t, str(r.count if r.count is not None else len(r.data)))
        except Exception:
            tbl.add_row(t, "[red]error[/]")
    console.print(tbl)

    console.print(Panel.fit(
        "[bold green]✓ All tests passed![/]\n\nNext step:\npython scripts/import_episode.py your_episode.json --inspect",
        border_style="green"
    ))

if __name__ == "__main__":
    main()
