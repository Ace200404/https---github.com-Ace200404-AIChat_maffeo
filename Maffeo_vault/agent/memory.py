"""
memory.py — Permanent conversation memory stored in Supabase.

Every message Chris sends and every response the agent gives is
stored in the conversations table. This means memory is permanent —
conversations from months ago are still searchable.

Three layers:
  1. Session buffer   → last N messages passed in prompt (immediate context)
  2. Load on start    → last 3 exchanges loaded when session begins
  3. Vector search    → memory_recall tool searches all past conversations
"""

import sys
import uuid
from pathlib import Path
from datetime import datetime
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from pipeline.config import get_supabase


class VaultMemory:
    """
    Manages conversation memory for the Maffeo Vault agent.
    One instance per chat session.
    """

    def __init__(self, session_id: Optional[str] = None):
        """
        Creates a new memory instance.
        If session_id is provided, continues an existing session.
        If not, creates a new session with a fresh UUID.
        """
        self.session_id  = session_id or str(uuid.uuid4())
        self.db          = get_supabase()
        self.turn_number = 0
        self.buffer      = []   # in-memory list of recent messages

        # Load recent history from Supabase on startup
        self._load_recent_history()

    def _load_recent_history(self) -> None:
        """
        Loads the last 6 messages from this session on startup.
        Gives the agent immediate context without needing a tool call.
        """
        try:
            result = (
                self.db.table("conversations")
                .select("role, content, turn_number")
                .eq("session_id", self.session_id)
                .order("turn_number", desc=True)
                .limit(6)
                .execute()
            )

            if result.data:
                # Reverse so oldest is first
                self.buffer = list(reversed(result.data))
                self.turn_number = result.data[0]["turn_number"] + 1

        except Exception:
            pass   # Fresh session if load fails

    def add_message(self, role: str, content: str, segments_used: list = None) -> None:
        """
        Saves a message to both the in-memory buffer and Supabase.

        Args:
            role:          "user" or "assistant"
            content:       The message text
            segments_used: List of segment IDs cited in this response
        """
        self.turn_number += 1

        message = {
            "role":    role,
            "content": content,
        }

        # Add to in-memory buffer (keep last 6)
        self.buffer.append(message)
        if len(self.buffer) > 6:
            self.buffer.pop(0)

        # Save to Supabase
        try:
            record = {
                "session_id":    self.session_id,
                "turn_number":   self.turn_number,
                "role":          role,
                "content":       content,
                "segments_used": segments_used or [],
            }

            self.db.table("conversations").insert(record).execute()

            # Generate and store embedding asynchronously
            self._store_embedding(content, self.turn_number)

        except Exception as e:
            pass   # Memory failure should never crash the chat

    def _store_embedding(self, text: str, turn_number: int) -> None:
        """
        Generates and stores an embedding for this message.
        Enables semantic search over past conversations.
        """
        try:
            from sentence_transformers import SentenceTransformer
            model  = SentenceTransformer("all-MiniLM-L6-v2")
            vector = model.encode(text, normalize_embeddings=True).tolist()

            self.db.table("conversations").update({
                "embedding": vector
            }).eq("session_id", self.session_id).eq(
                "turn_number", turn_number
            ).execute()

        except Exception:
            pass   # Embedding failure is non-fatal

    def get_history_as_messages(self) -> list[dict]:
        """
        Returns the conversation buffer formatted for the LangChain agent.
        Used to provide immediate context in the prompt.
        """
        return [
            {"role": msg["role"], "content": msg["content"]}
            for msg in self.buffer
        ]

    def get_session_id(self) -> str:
        return self.session_id
