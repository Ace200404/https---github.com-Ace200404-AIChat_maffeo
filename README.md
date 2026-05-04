# Maffeo Vault

A conversational AI assistant that lets users search and query the full history of the **Maffeo Drinks podcast** and **Ghost blog articles**. It uses semantic (meaning-based) search, permanent memory across sessions, and an automated weekly pipeline to stay up to date.

---

## Table of Contents

1. [How It Works — Overview](#1-how-it-works--overview)
2. [Project Structure](#2-project-structure)
3. [Data Flow](#3-data-flow)
4. [Supabase Tables](#4-supabase-tables)
5. [Component Reference](#5-component-reference)
6. [Local Setup](#6-local-setup)
7. [Running the App](#7-running-the-app)
8. [Weekly Pipeline](#8-weekly-pipeline)
9. [Environment Variables](#9-environment-variables)
10. [Adding New Features](#10-adding-new-features)
11. [Common Issues](#11-common-issues)

---

## 1. How It Works — Overview

```
EXTERNAL DATA SOURCES
┌────────────────────┐    ┌────────────────────┐
│  Transistor.fm API │    │  Ghost Admin API   │
│  (podcast episodes)│    │  (blog articles)   │
└────────┬───────────┘    └─────────┬──────────┘
         │                          │
         ▼ weekly (GitHub Actions)  ▼
┌─────────────────────────────────────────────┐
│              run_pipeline.py                │
│  fetch → parse → chunk → embed → store      │
└────────────────────┬────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────┐
│                  Supabase                   │
│  episodes | segments | articles | speakers  │
│           | conversations                   │
└────────────────────┬────────────────────────┘
                     │ vector search (pgvector)
                     ▼
┌─────────────────────────────────────────────┐
│        LangGraph ReAct Agent (Claude)        │
│  tools: semantic_search, episode_lookup,    │
│         speaker_search, memory_recall       │
└────────────────────┬────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────┐
│          Streamlit Chat UI (ui/app.py)       │
└─────────────────────────────────────────────┘
```

**Key ideas:**
- All podcast transcript segments and article chunks live in a single `segments` table, enabling one unified search across both sources.
- Embeddings (384-dimensional vectors) are generated locally using `sentence-transformers` — no third-party embedding API costs.
- The agent is a LangGraph ReAct loop: Claude reasons about which tool to call, reads the result, and decides whether to call another tool or answer.
- Conversation history is stored permanently in Supabase and is searchable via `memory_recall`.

---

## 2. Project Structure

```
AIChat/
│
├── .github/
│   └── workflows/
│       └── weekly_pipeline.yml   # GitHub Actions — runs every Monday 9am UTC
│
├── agent/                        # AI agent (Claude + tools + memory)
│   ├── agent.py                  # LangGraph ReAct agent setup + entry point
│   ├── memory.py                 # Permanent conversation memory (Supabase)
│   ├── prompts.py                # System prompt for Claude
│   └── tools.py                  # 4 search tools available to the agent
│
├── pipeline/                     # Data ingestion modules
│   ├── config.py                 # Supabase client factory + shared constants
│   ├── transistor_api.py         # Fetches episodes from Transistor.fm API
│   ├── parser.py                 # Parses Transistor JSON transcripts
│   ├── importer.py               # Writes episode data to Supabase
│   ├── ghost_api.py              # Fetches articles from Ghost Admin API
│   └── ghost_importer.py         # Chunks articles and writes to Supabase
│
├── scripts/                      # CLI tools for setup, import, and debugging
│   ├── run_pipeline.py           # Main pipeline entry point (used by GitHub Actions)
│   ├── import_all.py             # Bulk import all episodes from a JSON file
│   ├── import_episode.py         # Import or inspect a single episode
│   ├── generate_embeddings.py    # Generate embeddings for all un-embedded segments
│   ├── verify_episode.py         # Check data quality of an imported episode
│   ├── test_connection.py        # Verify Supabase connection + schema
│   └── debug_ghost.py            # Print raw Ghost API response (debug only)
│
├── sql/
│   └── schema.sql                # Supabase table definitions — run once on setup
│
├── ui/
│   └── app.py                    # Streamlit chat interface
│
├── .env.example                  # Template — copy to .env and fill in keys
├── .gitignore
└── requirements.txt
```

---

## 3. Data Flow

### 3a. Ingestion (Weekly Pipeline)

```
Transistor.fm API
        │
        │  transistor_api.fetch_new_episodes()
        │  → checks DB for already-imported episode numbers
        │  → returns only NEW episodes
        │
        ▼
transistor_api.fetch_transcript_json(url)
        │
        │  Downloads transcript JSON from Transistor CDN
        │
        ▼
run_pipeline._normalise_transcript()
        │
        │  Bridges API format → parser's expected format
        │  (Transistor API format differs from bulk export format)
        │
        ▼
parser.parse_episode()  →  episode dict
parser.parse_segments() →  list of segment dicts
        │
        │  Each segment: { speaker, text, start_time, end_time, word_count }
        │
        ▼
importer.insert_episode()   → episodes table
importer.insert_segments()  → segments table (source = 'podcast')
importer.upsert_speakers()  → speakers table


Ghost Admin API
        │
        │  ghost_api.fetch_new_posts()
        │  → checks articles table for already-imported ghost_ids
        │  → returns only NEW articles
        │
        ▼
ghost_importer.chunk_article()
        │
        │  Splits article plaintext into ~250-word chunks (by paragraph)
        │
        ▼
ghost_importer.insert_article()           → articles table
ghost_importer.insert_article_segments()  → segments table (source = 'article')


After all imports:
        │
        ▼
SentenceTransformer("all-MiniLM-L6-v2")
        │
        │  Fetches all segments WHERE embedding IS NULL
        │  Encodes text → 384-dimensional normalized vector
        │  Updates segments.embedding
        │
        ▼
Supabase segments table fully populated + searchable
```

### 3b. Chat Query (Real-Time)

```
User types message in Streamlit
        │
        ▼
ui/app.py → agent.get_agent_response(user_message, memory)
        │
        ▼
agent.py builds message list:
  [ SystemMessage(SYSTEM_PROMPT) ]
  + [ last 6 messages from VaultMemory buffer ]
  + [ HumanMessage(user_message) ]
        │
        ▼
LangGraph ReAct agent (Claude-Sonnet-4-5)
  ┌─────────────────────────────────────┐
  │  Reason: which tool should I call?  │
  │  Act: call tool                     │
  │  Observe: read result               │
  │  Repeat if needed (max 10 loops)    │
  └─────────────────────────────────────┘
        │
        │  One or more tool calls:
        │
        ├── semantic_search(query)
        │       embed query → match_segments RPC → top 8 results
        │       returns both podcast + article matches
        │
        ├── episode_lookup(episode_number)
        │       fetches episode metadata + first 50 segments (ordered by time)
        │
        ├── speaker_search(query)
        │       detects speaker name → embed query → match_segments with filter
        │
        └── memory_recall(query)
                embed query → match_conversations RPC → top 5 past messages
        │
        ▼
Claude synthesises answer with citations
        │
        ▼
agent.py saves user + assistant messages to VaultMemory
  → VaultMemory.add_message() stores to conversations table + generates embedding
        │
        ▼
ui/app.py displays response in chat
```

---

## 4. Supabase Tables

### `episodes`
Stores podcast episode metadata.

| Column | Type | Description |
|--------|------|-------------|
| `id` | uuid | Primary key |
| `transistor_id` | text | Unique ID from Transistor.fm (deduplication key) |
| `episode_number` | int | Episode number (can be null for trailers/specials) |
| `title` | text | Episode title |
| `published_date` | date | Publication date |
| `duration_seconds` | int | Total duration |
| `raw_json` | jsonb | Full original transcript JSON (for reference/reprocessing) |
| `created_at` | timestamptz | When imported |

### `segments`
Core search table. Stores both podcast transcript segments AND article chunks in one place. This unified design lets `semantic_search` find both with a single query.

| Column | Type | Description |
|--------|------|-------------|
| `id` | uuid | Primary key |
| `episode_id` | uuid | FK → episodes (null for article chunks) |
| `episode_number` | int | Denormalized for fast filtering |
| `speaker` | text | Speaker name (e.g. "Chris Maffeo") |
| `text` | text | The actual spoken/written content |
| `start_time` | float | Seconds from start (podcast only) |
| `end_time` | float | Seconds from end (podcast only) |
| `word_count` | int | Word count of this segment |
| `embedding` | vector(384) | Semantic embedding for vector search |
| `source` | text | `'podcast'` or `'article'` |
| `article_id` | uuid | FK → articles (null for podcast segments) |
| `article_title` | text | Article title (denormalized for display) |
| `article_url` | text | Article URL (denormalized for citations) |

### `speakers`
Aggregated speaker data built up as episodes are imported.

| Column | Type | Description |
|--------|------|-------------|
| `id` | uuid | Primary key |
| `name` | text | Speaker name (unique) |
| `is_host` | bool | Whether this speaker is the podcast host |
| `total_segments` | int | Count of segments across all episodes |
| `first_episode_id` | uuid | FK → episodes |
| `notes` | text | Optional notes |

### `articles`
Ghost blog articles (metadata only — content is in `segments`).

| Column | Type | Description |
|--------|------|-------------|
| `id` | uuid | Primary key |
| `ghost_id` | text | Ghost's internal post ID (deduplication key) |
| `title` | text | Article title |
| `slug` | text | URL slug |
| `published_at` | timestamptz | Publication date |
| `author` | text | Author name |
| `tags` | text[] | Array of tag names |
| `url` | text | Full public URL |

### `pipeline_logs`
Audit trail of every pipeline run.

| Column | Type | Description |
|--------|------|-------------|
| `id` | uuid | Primary key |
| `transistor_id` | text | Episode's Transistor ID |
| `episode_number` | int | Episode number |
| `status` | text | `'success'`, `'failed'`, or `'skipped'` |
| `segment_count` | int | How many segments were inserted |
| `error_message` | text | Error details (if failed) |
| `duration_seconds` | float | How long the import took |
| `ran_at` | timestamptz | When this log entry was created |

### `conversations`
Permanent chat history, searchable by meaning.

| Column | Type | Description |
|--------|------|-------------|
| `id` | uuid | Primary key |
| `session_id` | uuid | Groups messages from one chat session |
| `turn_number` | int | Order within the session |
| `role` | text | `'user'` or `'assistant'` |
| `content` | text | The message text |
| `embedding` | vector(384) | Semantic embedding (for `memory_recall` tool) |
| `segments_used` | text[] | Which segment IDs were cited in this response |
| `created_at` | timestamptz | Timestamp |

### Supabase RPC Functions
Two PostgreSQL functions handle vector search (called from `agent/tools.py`):

- **`match_segments(query_embedding, match_count, filter_speaker)`**
  Semantic similarity search over `segments.embedding`. Optional speaker filter.

- **`match_conversations(query_embedding, match_count)`**
  Semantic similarity search over `conversations.embedding`.

These must exist in Supabase — they are defined in `sql/schema.sql`.

---

## 5. Component Reference

### `pipeline/config.py`
Single place for shared config. Import `get_supabase()` from here in any module that needs the database.

```python
from pipeline.config import get_supabase
db = get_supabase()
```

Constants:
- `HOST_NAME = "Chris"` — used by the parser to identify the host speaker
- `BATCH_SIZE = 100` — segment insert batch size

---

### `pipeline/transistor_api.py`
Handles all Transistor.fm communication.

Key functions:
- `fetch_new_episodes()` — compares Transistor episode list against DB, returns only new ones
- `fetch_transcript_json(url)` — downloads the transcript JSON from Transistor's CDN

Rate limiting: Transistor free plan allows 10 req/min. The code adds a 1.5s delay between pages and uses exponential backoff on 429 errors.

---

### `pipeline/parser.py`
Converts raw Transistor JSON into structured dicts the importer can write.

**Critical constants** (update these if the JSON field names ever change):
```python
FIELD_NUMBER   = "episode_number"
FIELD_SEGMENTS = "segments"
FIELD_SPEAKER  = "speaker"
FIELD_TEXT     = "body"       # Note: NOT "text"
FIELD_START    = "startTime"  # camelCase
FIELD_END      = "endTime"
```

Key functions:
- `parse_episode(raw)` → episode metadata dict
- `parse_segments(raw, episode_number)` → list of segment dicts
- `inspect_json(file_path)` → prints structure (debug tool, no DB writes)

---

### `pipeline/importer.py`
Writes structured data to Supabase.

Key functions:
- `insert_episode(episode_data)` → returns new episode `id`
- `insert_segments(segments, episode_id)` → inserts in batches of 100
- `upsert_speakers(segments, episode_id)` → creates or updates speaker rows
- `log_pipeline_run(...)` → writes to `pipeline_logs` table
- `delete_episode(transistor_id)` → deletes episode + cascades to segments

---

### `pipeline/ghost_api.py`
Fetches articles from Ghost using the **Admin API** (not Content API).

The Admin API is required because the Content API strips body content from members-only posts. Auth uses a short-lived JWT (5-minute expiry) derived from `GHOST_ADMIN_KEY`.

Key functions:
- `fetch_all_published_posts()` → returns all published posts with `plaintext` format
- `fetch_new_posts()` → deduplicates against `articles` table, returns only new posts
- `_make_jwt(admin_key)` → generates the JWT for each request

---

### `pipeline/ghost_importer.py`
Splits article content into searchable chunks.

Articles are broken into ~250-word chunks along paragraph boundaries. Each chunk is stored as a row in `segments` with `source='article'`, linking back to its `article_id`.

Key functions:
- `insert_article(post)` → writes to `articles` table, returns `id`
- `chunk_article(post, article_id)` → returns list of segment dicts
- `insert_article_segments(segments)` → batch inserts into `segments`

---

### `agent/tools.py`
Defines the 4 tools Claude can call. All tools query Supabase and return formatted strings.

| Tool | When Claude uses it | What it does |
|------|---------------------|--------------|
| `semantic_search(query)` | General topic questions | Embeds query → vector search → top 8 matches (podcast + articles) |
| `episode_lookup(episode_number)` | "What happened in episode 45?" | Fetches metadata + first 50 segments ordered by time |
| `speaker_search(query)` | "What did Chris say about X?" | Detects speaker name → filtered vector search |
| `memory_recall(query)` | Follow-up to past conversations | Vector search over `conversations` table |

The embedding model (`all-MiniLM-L6-v2`) is loaded once into `_model` (module-level cache) and reused across all tool calls.

Citation format returned by tools:
```
[Episode 45 | Chris Maffeo | 12:34]
The text of what was said...

[Article: Title (https://...) | Chris Maffeo]
The article text chunk...
```

---

### `agent/agent.py`
Wires everything together.

- `build_agent()` — creates a LangGraph `create_react_agent` with Claude and the 4 tools
- `get_agent_response(user_message, memory)` — the main entry point called by the UI:
  1. Builds message list from memory buffer
  2. Runs agent (max 10 tool-call iterations via `recursion_limit`)
  3. Extracts final answer
  4. Saves both messages to memory

Model: `claude-sonnet-4-5` (change here to upgrade to a newer model).

---

### `agent/memory.py`
3-layer memory system:

| Layer | Where stored | How used |
|-------|-------------|----------|
| In-memory buffer | Python list (last 6 messages) | Immediate context for every message |
| DB load on start | `conversations` table | Restores last 6 messages when session resumes |
| Vector search | `conversations.embedding` | `memory_recall` tool finds relevant past messages |

Each message is saved to Supabase AND its embedding is generated immediately after (synchronous).

---

### `agent/prompts.py`
The system prompt sent to Claude at the start of every conversation.

Edit this file to:
- Change the assistant's persona or name
- Add/remove instruction rules
- Add a new data source (e.g. "you also have access to YouTube transcripts")
- Change citation format

---

### `ui/app.py`
Streamlit chat UI. Key details:

- `_preload_embedding_model()` is decorated with `@st.cache_resource` so the 200MB model loads once at startup, not on every message
- `st.session_state.memory` holds the `VaultMemory` instance for the session
- `st.session_state.messages` holds the visible chat history for rendering

To run locally:
```bash
streamlit run ui/app.py
```

---

## 6. Local Setup

### Prerequisites
- Python 3.11+
- A Supabase project with `pgvector` enabled
- API keys for Transistor, Ghost, and Anthropic

### Steps

```bash
# 1. Clone and enter the project
git clone <repo-url> AIChat
cd AIChat

# 2. Create and activate virtual environment
python -m venv venv
venv\Scripts\Activate.ps1     # Windows PowerShell
# source venv/bin/activate    # Mac/Linux

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set up credentials
cp .env.example .env
# Fill in .env with your API keys (see Environment Variables section)

# 5. Create Supabase schema
# Go to supabase.com → your project → SQL Editor
# Paste and run the contents of sql/schema.sql

# 6. Test the connection
python scripts/test_connection.py
# Expected: ✓ All tests passed!
```

---

## 7. Running the App

```bash
# Activate venv first (if not already active)
venv\Scripts\Activate.ps1

# Run the chat UI
streamlit run ui/app.py
```

The app opens at `http://localhost:8501`.

**First run**: The embedding model (~90MB) downloads and caches to `~/.cache/huggingface`. Subsequent starts are fast.

---

## 8. Weekly Pipeline

### What it does
Every Monday at 9am UTC, GitHub Actions runs `scripts/run_pipeline.py` which:

1. Fetches new podcast episodes from Transistor.fm (since last import)
2. Downloads and parses their transcripts
3. Inserts episodes + segments into Supabase
4. Fetches new Ghost articles (since last import)
5. Chunks and inserts article content into segments
6. Generates embeddings for all new segments

### Running manually

```bash
# Dry run — see what's new without writing anything
python scripts/run_pipeline.py --dry-run

# Full run
python scripts/run_pipeline.py
```

### Triggering manually on GitHub
Go to your repo → **Actions → Weekly Pipeline → Run workflow → Run workflow**.

### GitHub Secrets required
These must be set at: `repo → Settings → Secrets and variables → Actions → Repository secrets`

```
SUPABASE_URL
SUPABASE_ANON_KEY
ANTHROPIC_API_KEY
TRANSISTOR_API_KEY
GHOST_URL
GHOST_ADMIN_KEY
```

Each is a separate secret entry — name on the left, value on the right, no `=` signs.

---

## 9. Environment Variables

| Variable | Where to get it |
|----------|----------------|
| `SUPABASE_URL` | supabase.com → your project → Settings → API → Project URL |
| `SUPABASE_ANON_KEY` | supabase.com → your project → Settings → API → anon public key |
| `ANTHROPIC_API_KEY` | console.anthropic.com → API Keys |
| `TRANSISTOR_API_KEY` | Transistor dashboard → Account → API Key |
| `GHOST_URL` | Your Ghost site URL e.g. `https://yoursite.ghost.io` |
| `GHOST_ADMIN_KEY` | Ghost dashboard → Settings → Integrations → create integration → Admin API Key |

Never commit `.env` to git — it is listed in `.gitignore`.

---

## 10. Adding New Features

### Add a new data source (e.g. YouTube transcripts)

1. **Create `pipeline/youtube_api.py`** — fetch transcripts from YouTube API
2. **Create `pipeline/youtube_importer.py`** — chunk and insert into `segments` with `source='youtube'`
3. **Update `agent/tools.py`** — `_format_segment` already has an if/else on `source`; add a new branch for `'youtube'`
4. **Update `agent/prompts.py`** — mention YouTube as a third source
5. **Update `scripts/run_pipeline.py`** — add a Step 4 block for YouTube, following the Ghost pattern

### Add a new search tool

1. **Write the tool function in `agent/tools.py`**:
```python
@tool
def my_new_tool(query: str) -> str:
    """Describe when the agent should use this tool."""
    db = get_supabase()
    # ... query Supabase ...
    return formatted_result
```

2. **Add it to the tools list in `agent/agent.py`**:
```python
from agent.tools import semantic_search, episode_lookup, speaker_search, memory_recall, my_new_tool

tools = [semantic_search, episode_lookup, speaker_search, memory_recall, my_new_tool]
```

3. **Update `agent/prompts.py`** to tell Claude when to use the new tool.

### Change the AI model

In `agent/agent.py`, find:
```python
llm = ChatAnthropic(model="claude-sonnet-4-5", max_tokens=4096)
```
Replace with the new model ID (e.g. `claude-opus-4-7`). See [Anthropic docs](https://docs.anthropic.com/en/docs/about-claude/models) for available models.

### Change the embedding model

In `agent/tools.py`:
```python
MODEL_NAME = "all-MiniLM-L6-v2"  # 384-dim vectors
```

If you change this, you must:
1. Update `MODEL_NAME` in `tools.py`
2. Re-generate all embeddings: `python scripts/generate_embeddings.py --reset`
3. The new model's output dimension must match the `vector(384)` column in Supabase — update the schema if different

### Add a new Supabase table

1. Write the `CREATE TABLE` statement and run it in Supabase SQL Editor
2. If you need vector search on the new table, also create a `match_*` RPC function (follow the pattern in `sql/schema.sql`)
3. Add insert/query functions in a new `pipeline/` module

### Modify the chunk size for articles

In `pipeline/ghost_importer.py`:
```python
CHUNK_MAX_WORDS = 250  # increase for longer chunks, decrease for more granular search
```

After changing, delete and re-import existing articles for the change to take effect.

---

## 11. Common Issues

**`Error: Missing Supabase credentials`**
→ Check your `.env` file exists, is in the project root, and has `SUPABASE_URL` and `SUPABASE_ANON_KEY` filled in.

**`relation "episodes" does not exist`**
→ Run `sql/schema.sql` in the Supabase SQL Editor to create all tables.

**`Parse error: JSON has no 'transcript' field`**
→ Run `python scripts/import_episode.py your_file.json --inspect` to see the actual field names. Update the constants at the top of `pipeline/parser.py` to match.

**`Skipped — no transcript available yet`**
→ The episode exists on Transistor but doesn't have a JSON transcript yet. The pipeline will pick it up next run once the transcript is ready.

**Chat loads indefinitely**
→ The `recursion_limit=10` in `agent/agent.py` prevents infinite loops. If it still hangs, check that `ANTHROPIC_API_KEY` is set correctly.

**GitHub Actions — secrets all False**
→ Secrets must be added as individual **Repository secrets** (not Environment secrets, not as one combined secret). Go to `repo → Settings → Secrets and variables → Actions` and add each key separately.

**`0 chunks per article`**
→ Check that the Ghost Admin API is being used (not Content API). Members-only posts return empty `plaintext` with the Content API. Verify `GHOST_ADMIN_KEY` is set and formatted as `key-id:secret-hex`.

**Embedding model slow to load**
→ First run downloads the model (~90MB). It caches to `~/.cache/huggingface` — subsequent starts are instant. In the UI, `@st.cache_resource` keeps it in memory across chat messages.
