"""
app.py — Streamlit chat interface for the Maffeo Vault.

Run with:
    streamlit run ui/app.py

Then open: http://localhost:8501
"""

import sys
import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent.parent))
from agent.agent import get_agent_response
from agent.memory import VaultMemory

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Maffeo Vault",
    page_icon="🎙️",
    layout="centered",
)

st.title("🎙️ Maffeo Vault")
st.caption("Ask anything from 113+ episodes of the MAFFEO DRINKS podcast.")

# ── Session state ─────────────────────────────────────────────────────────────
# Persists memory and chat history across reruns within the same session
if "memory" not in st.session_state:
    st.session_state.memory = VaultMemory()

if "messages" not in st.session_state:
    st.session_state.messages = [
        {
            "role": "assistant",
            "content": (
                "Welcome to the Maffeo Vault.\n\n"
                "Ask me anything from the podcast archive — "
                "I'll search across all episodes and cite my sources.\n\n"
                "Try asking:\n"
                "- What have I said about distribution strategy?\n"
                "- What did guests say about brand building in the US?\n"
                "- What happened in episode 45?"
            ),
        }
    ]

# ── Render chat history ───────────────────────────────────────────────────────
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# ── Chat input ────────────────────────────────────────────────────────────────
if prompt := st.chat_input("Ask the vault..."):

    # Show user message immediately
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Generate response
    with st.chat_message("assistant"):
        with st.spinner("Searching vault..."):
            try:
                response = get_agent_response(
                    user_message=prompt,
                    memory=st.session_state.memory,
                )
            except Exception as e:
                response = (
                    f"Something went wrong: {str(e)}\n\n"
                    "Check your ANTHROPIC_API_KEY in the .env file."
                )

        st.markdown(response)

    # Save to display history
    st.session_state.messages.append({"role": "assistant", "content": response})
