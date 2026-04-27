"""
parser.py — Reads a Transistor.fm JSON transcript file and returns
clean, validated Python dictionaries ready to insert into Supabase.

Your actual format: all_transcripts.json is a list of all episodes:
[
  { "episode_number": 119, "title": "...", "transcript": { "segments": [...] } },
  { "episode_number": 118, "title": "...", "transcript": { "segments": [...] } },
  ...
]
"""

import json
from pathlib import Path
from typing import Optional


# ── Field names — matches YOUR actual Transistor JSON ────────────────────────
FIELD_TITLE      = "title"
FIELD_NUMBER     = "episode_number"
FIELD_SHOW       = "show"
FIELD_TRANSCRIPT = "transcript"
FIELD_SEGMENTS   = "segments"
FIELD_SPEAKER    = "speaker"
FIELD_TEXT       = "body"        # Transistor uses "body" not "text"
FIELD_START      = "startTime"   # camelCase strings e.g. "47.016"
FIELD_END        = "endTime"


def load_all_episodes(file_path: str) -> list[dict]:
    """
    Loads all_transcripts.json and returns a list of raw episode dicts.
    Handles both a top-level list [...] and a single episode dict {...}.
    """
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    with open(path, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in {file_path}: {e}")

    if isinstance(data, list):
        return data           # all episodes — the normal case
    elif isinstance(data, dict):
        return [data]         # single episode wrapped in a list
    else:
        raise ValueError(f"Unexpected top-level JSON type: {type(data)}")


def load_json(file_path: str) -> dict:
    """
    Loads a file and returns the FIRST episode only.
    Used by import_episode.py for single-episode imports.
    """
    episodes = load_all_episodes(file_path)
    return episodes[0]


def parse_episode(raw: dict) -> dict:
    """
    Extracts episode metadata from one raw episode dict.
    Returns a clean dict matching the `episodes` table columns.
    """
    episode_number = raw.get(FIELD_NUMBER)
    if episode_number is None:
        raise ValueError(f"Episode missing 'episode_number'. Keys found: {list(raw.keys())}")

    return {
        "transistor_id":    str(episode_number),   # episode_number used as unique ID
        "episode_number":   int(episode_number),
        "title":            raw.get(FIELD_TITLE, "Untitled Episode"),
        "published_date":   None,
        "duration_seconds": None,
        "raw_json":         raw,
    }


def parse_segments(raw: dict, episode_number: Optional[int] = None) -> list[dict]:
    """
    Extracts all speaker segments from one raw episode dict.
    Returns a list of dicts matching the `segments` table columns.
    """
    transcript = raw.get(FIELD_TRANSCRIPT)

    if transcript is None:
        raise ValueError(
            f"Episode {episode_number} has no 'transcript' field.\n"
            f"Available keys: {list(raw.keys())}"
        )

    if isinstance(transcript, dict):
        raw_segments = transcript.get(FIELD_SEGMENTS, [])
    elif isinstance(transcript, list):
        raw_segments = transcript
    else:
        raise ValueError(f"Unexpected transcript format: {type(transcript)}")

    if not raw_segments:
        raise ValueError(f"Episode {episode_number} has zero segments.")

    segments = []
    for seg in raw_segments:
        speaker = seg.get(FIELD_SPEAKER, "").strip()
        text    = seg.get(FIELD_TEXT, "").strip()

        if not speaker or not text:
            continue

        segments.append({
            "episode_number": episode_number,
            "speaker":        speaker,
            "text":           text,
            "start_time":     _to_float(seg.get(FIELD_START)),
            "end_time":       _to_float(seg.get(FIELD_END)),
            "word_count":     len(text.split()),
        })

    if not segments:
        raise ValueError(f"Episode {episode_number}: all segments were empty after filtering.")

    return segments


def inspect_json(file_path: str) -> None:
    """
    Prints a summary of the JSON file structure.
    Run this first with --inspect before importing.
    """
    episodes = load_all_episodes(file_path)

    print("\n── JSON Structure Inspector ──────────────────────────")
    print(f"Total episodes found: {len(episodes)}")

    if not episodes:
        print("[WARNING] File is empty!")
        return

    first = episodes[0]
    last  = episodes[-1]

    print(f"\nFirst episode:")
    print(f"  Number: {first.get(FIELD_NUMBER, '[NOT FOUND]')}")
    print(f"  Title:  {first.get(FIELD_TITLE,  '[NOT FOUND]')}")
    print(f"  Show:   {first.get(FIELD_SHOW,   '[NOT FOUND]')}")

    print(f"\nLast episode:")
    print(f"  Number: {last.get(FIELD_NUMBER, '[NOT FOUND]')}")
    print(f"  Title:  {last.get(FIELD_TITLE,  '[NOT FOUND]')}")

    transcript = first.get(FIELD_TRANSCRIPT, {})
    segs = transcript.get(FIELD_SEGMENTS, []) if isinstance(transcript, dict) else transcript
    print(f"\nFirst episode segment count: {len(segs)}")

    if segs:
        s = segs[0]
        print(f"\nFirst segment keys:  {list(s.keys())}")
        print(f"  Speaker:    {s.get(FIELD_SPEAKER, '[NOT FOUND]')}")
        print(f"  Start time: {s.get(FIELD_START,   '[NOT FOUND]')}")
        print(f"  Body:       {str(s.get(FIELD_TEXT, '[NOT FOUND]'))[:100]}...")

    # List all episode numbers
    numbers = sorted([e.get(FIELD_NUMBER) for e in episodes if e.get(FIELD_NUMBER)])
    print(f"\nAll episode numbers: {numbers}")
    print("──────────────────────────────────────────────────────\n")


# ── Internal helpers ──────────────────────────────────────────────────────────

def _to_float(value) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None
