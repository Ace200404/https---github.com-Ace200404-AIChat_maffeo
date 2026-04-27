"""
config.py — Central configuration and Supabase client.

Every other module imports from here. If your keys ever change,
you only change them in one place (.env file).
"""

import os
from dotenv import load_dotenv
from supabase import create_client, Client

# Load .env file from the project root
load_dotenv()


def get_supabase() -> Client:
    """
    Returns a connected Supabase client.
    Call this once at the top of any script that needs the database.

    Example:
        from pipeline.config import get_supabase
        db = get_supabase()
        result = db.table("episodes").select("*").execute()
    """
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_ANON_KEY")

    if not url or not key:
        raise EnvironmentError(
            "\n\n[ERROR] Missing Supabase credentials.\n"
            "Steps to fix:\n"
            "  1. Copy .env.example to .env\n"
            "  2. Fill in your SUPABASE_URL and SUPABASE_ANON_KEY\n"
            "  3. Find these at: supabase.com → your project → Settings → API\n"
        )

    return create_client(url, key)


# ── Shared constants ─────────────────────────────────────────────────────────
# The host's name exactly as it appears in your Transistor JSON files.
# Check one of your JSON files and update this if needed.
HOST_NAME = "Chris"

# Segments inserted per database call — keeps memory usage low on big episodes.
BATCH_SIZE = 100
