"""
agent.py — Wires together the LangChain agent, tools, and memory.

Uses LangGraph's prebuilt ReAct agent which is compatible with
the current version of LangChain/LangGraph installed.
"""

import os
import sys
from pathlib import Path

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langgraph.prebuilt import create_react_agent

sys.path.insert(0, str(Path(__file__).parent.parent))
from agent.tools import semantic_search, episode_lookup, speaker_search, memory_recall
from agent.prompts import SYSTEM_PROMPT
from agent.memory import VaultMemory


# ── Tools available to the agent ─────────────────────────────────────────────
TOOLS = [
    semantic_search,
    episode_lookup,
    speaker_search,
    memory_recall,
]


def build_agent():
    """
    Builds and returns the LangGraph ReAct agent.
    Called once per message.
    """
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    if not anthropic_key:
        raise EnvironmentError(
            "ANTHROPIC_API_KEY not found in .env file.\n"
            "Add it: ANTHROPIC_API_KEY=sk-ant-your-key-here"
        )

    llm = ChatAnthropic(
        model="claude-sonnet-4-5",
        anthropic_api_key=anthropic_key,
        max_tokens=4096,
    )

    return create_react_agent(llm, TOOLS)


def get_agent_response(user_message: str, memory: VaultMemory) -> str:
    """
    Main entry point. Takes a user message and returns the agent's response.

    Args:
        user_message: What Chris typed in the chat
        memory:       The VaultMemory instance for this session

    Returns:
        The agent's response string with citations
    """
    agent = build_agent()

    # Build message history: system prompt + past messages + new message
    messages = [SystemMessage(content=SYSTEM_PROMPT)]

    for msg in memory.get_history_as_messages():
        if msg["role"] == "user":
            messages.append(HumanMessage(content=msg["content"]))
        else:
            messages.append(AIMessage(content=msg["content"]))

    messages.append(HumanMessage(content=user_message))

    # Run the agent (recursion_limit prevents infinite tool-call loops)
    result = agent.invoke({"messages": messages}, {"recursion_limit": 10})

    # Extract the final response text
    response = ""
    for msg in reversed(result["messages"]):
        if isinstance(msg, AIMessage) and msg.content:
            if isinstance(msg.content, str):
                response = msg.content
                break
            elif isinstance(msg.content, list):
                # Handle list content blocks
                for block in msg.content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        response = block["text"]
                        break
                if response:
                    break

    if not response:
        response = "I couldn't generate a response. Please try again."

    # Save both messages to permanent memory
    memory.add_message("user",      user_message)
    memory.add_message("assistant", response)

    return response
