# Maffeo Drinks Digital CEO — System Architecture Document
**Version:** 1.0  
**Date:** March 2026  
**Author:** Architecture Design Session  

---

## Table of Contents
1. [System Overview](#1-system-overview)
2. [Architecture Decision: AI Agent vs MCP](#2-architecture-decision)
3. [High-Level Architecture Diagram](#3-high-level-architecture)
4. [Layer-by-Layer Breakdown](#4-layer-by-layer-breakdown)
5. [Database Schema (Supabase)](#5-database-schema)
6. [AI Agent Design](#6-ai-agent-design)
7. [Data Pipeline Design](#7-data-pipeline-design)
8. [Conversation Memory System](#8-conversation-memory-system)
9. [Citation System](#9-citation-system)
10. [Tech Stack Summary](#10-tech-stack-summary)
11. [Implementation Phases](#11-implementation-phases)
12. [Open Questions & Future Decisions](#12-open-questions)

---

## 1. System Overview

The Maffeo Vault is a conversational AI system that allows Chris to query the entire history of his podcast as if talking to a digital version of himself. The system ingests weekly podcast transcripts from Transistor.fm, stores them with full speaker attribution, builds a semantic knowledge network, and surfaces answers via a chat interface — always citing the source episode and speaker.

### Core User Story
> Chris opens the chat and asks: *"What have I said about brand positioning for small producers?"*  
> The system searches 50+ episodes semantically, finds the 5 most relevant segments across different episodes and speakers, and returns a synthesised answer like:  
> *"You've covered this in three episodes. In Episode 12, you said [quote] (Chris, 14:32). In Episode 29, your guest Alex Chen added [quote] (Alex Chen, 08:15)..."*

### System Constraints
- **Single user:** Chris only (no auth complexity needed)
- **Desktop UI only** (for now)
- **Budget:** $0 (Supabase free tier + existing Claude API subscription)
- **Automation:** New episode processed weekly with zero Chris effort
- **Memory:** Permanent — conversations stored forever

---

## 2. Architecture Decision: AI Agent vs MCP

### Why AI Agent (not MCP)

| Criteria | MCP | AI Agent (LangChain) |
|---|---|---|
| Custom retrieval logic | ❌ Limited | ✅ Full control |
| Citation system | ❌ Hard to enforce | ✅ Built into tool responses |
| Persistent memory across sessions | ❌ Not native | ✅ Custom memory layer |
| Multiple search strategies | ❌ Single connection | ✅ Multiple tools per query |
| Cost | Free | Free (uses existing Claude API) |
| UI flexibility | Locked to Claude.ai | ✅ Custom Chainlit interface |
| Learning value for internship | Low | ✅ High — industry-standard pattern |

**Decision: LangChain AI Agent with custom tools, Chainlit UI, Supabase backend.**

MCP would be appropriate if the goal were to add a data source to Claude.ai's existing chat. This project requires a bespoke system, so an Agent is the right choice.

---

## 3. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         MAFFEO VAULT                                │
│                                                                      │
│  ┌──────────────┐    ┌─────────────────────────────────────────┐   │
│  │   INGESTION  │    │              CHAT INTERFACE              │   │
│  │   PIPELINE   │    │              (Chainlit)                  │   │
│  │              │    │                                          │   │
│  │ Transistor   │    │  Chris types a question                  │   │
│  │ API / JSON   │    │  ↓                                       │   │
│  │     ↓        │    │  AI Agent receives query                 │   │
│  │ Parser &     │    │  ↓                                       │   │
│  │ Validator    │    │  Agent selects tools                     │   │
│  │     ↓        │    │  ↓                                       │   │
│  │ Embeddings   │    │  Tools query Supabase                    │   │
│  │ Generator    │    │  ↓                                       │   │
│  │     ↓        │    │  Agent synthesises answer with citations │   │
│  │ Concept      │    │  ↓                                       │   │
│  │ Extractor    │    │  Response displayed with source cards    │   │
│  └──────┬───────┘    └──────────────────┬──────────────────────┘   │
│         │                               │                           │
│         ▼                               ▼                           │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                    SUPABASE (PostgreSQL + pgvector)           │  │
│  │                                                               │  │
│  │  episodes  │  segments  │  concepts  │  conversations        │  │
│  │  speakers  │  segment_concepts       │  concept_relationships │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                               │                                     │
│                               ▼                                     │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                    LANGCHAIN AI AGENT                         │  │
│  │                                                               │  │
│  │  Tool: semantic_search    Tool: episode_lookup               │  │
│  │  Tool: speaker_search     Tool: concept_search               │  │
│  │  Tool: memory_recall      Tool: conversation_history         │  │
│  │                                                               │  │
│  │  Memory: Supabase-backed permanent conversation store        │  │
│  │  Model: Claude (claude-sonnet-4)                              │  │
│  └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 4. Layer-by-Layer Breakdown

### Layer 1 — Data Ingestion Pipeline
Responsible for moving data from Transistor.fm into Supabase. Runs automatically once per week (or manually triggered).

**Inputs:** JSON transcript files from Transistor.fm  
**Outputs:** Rows in `episodes`, `segments`, embeddings, concepts

**Steps:**
1. Poll Transistor API for new episodes
2. Download JSON if new episode found
3. Parse and validate JSON structure
4. Insert episode metadata into `episodes` table
5. Insert each speaker segment into `segments` table
6. Generate vector embeddings for each segment
7. Run concept extraction (NLP)
8. Store concepts and link to segments
9. Log result (success / failure / skipped)

---

### Layer 2 — Supabase Database
The single source of truth. All data lives here. The Agent reads from here. The Pipeline writes here.

See Section 5 for full schema.

---

### Layer 3 — LangChain AI Agent
The brain of the system. Receives Chris's question, decides which tools to use, retrieves context, and generates a cited response.

**Key design principle:** The agent does NOT answer from its own training knowledge alone. Every claim in the response must be grounded in retrieved segments from the vault.

See Section 6 for agent design.

---

### Layer 4 — Chainlit Chat Interface
The UI layer Chris interacts with. A desktop web app that looks and feels like a chat product (similar to ChatGPT but connected to the vault).

**Features:**
- Chat input field
- Message history in session
- Source cards (collapsible) showing episode number, speaker, timestamp, quote
- Session persistence (Chris can close and reopen)
- Simple admin panel for pipeline status

---

## 5. Database Schema (Supabase)

### Table: `episodes`
```
id                  bigint (PK, auto)
transistor_id       text (unique — Transistor's own ID)
episode_number      integer
title               text
published_date      date
duration_seconds    integer
raw_json            jsonb  ← store the complete original JSON
processed_at        timestamptz
created_at          timestamptz (default now())
```
**Purpose:** Master record for each podcast episode. Raw JSON is stored so you can reprocess without re-fetching.

---

### Table: `segments`
```
id                  bigint (PK, auto)
episode_id          bigint (FK → episodes.id)
episode_number      integer  ← denormalised for fast citation display
speaker             text     ← "Chris", "Alex Chen", etc.
text                text     ← the spoken words
start_time          float    ← seconds from episode start
end_time            float
word_count          integer
embedding           vector(384)  ← pgvector semantic search
created_at          timestamptz
```
**Purpose:** The core retrieval unit. Every search returns segments. Each segment knows its episode and speaker — this is what powers citations.

**Index required:**
```sql
CREATE INDEX segments_embedding_idx 
ON segments USING hnsw (embedding vector_cosine_ops);
```

---

### Table: `speakers`
```
id                  bigint (PK, auto)
name                text (unique)
total_segments      integer
first_episode_id    bigint (FK → episodes.id)
is_host             boolean  ← true for Chris
notes               text
```
**Purpose:** Lookup and stats. Useful for "what did Chris say vs what did guests say" queries.

---

### Table: `concepts`
```
id                  bigint (PK, auto)
name                text (unique)
type                text  ← "topic", "person", "brand", "strategy", "place"
times_mentioned     integer
first_episode_id    bigint (FK → episodes.id)
embedding           vector(384)  ← for concept-level semantic search
created_at          timestamptz
```
**Purpose:** The knowledge network layer. Extracted from transcripts via NLP.

---

### Table: `segment_concepts` (junction)
```
segment_id          bigint (FK → segments.id)
concept_id          bigint (FK → concepts.id)
relevance_score     float    ← 0.0–1.0, how central is this concept to this segment
PRIMARY KEY (segment_id, concept_id)
```
**Purpose:** Links concepts to the specific segments where they appear.

---

### Table: `concept_relationships`
```
id                  bigint (PK, auto)
concept_a_id        bigint (FK → concepts.id)
concept_b_id        bigint (FK → concepts.id)
relationship_type   text    ← "co_occurs_with", "builds_on", "contrasts_with"
strength            float   ← 0.0–1.0
evidence_segment_ids bigint[]  ← array of segment IDs showing this relationship
created_at          timestamptz
```
**Purpose:** The "neural network" of ideas. Enables Chris to discover connections he didn't know existed.

---

### Table: `conversations`
```
id                  bigint (PK, auto)
session_id          uuid    ← groups messages into a conversation
turn_number         integer ← order within session
role                text    ← "user" or "assistant"
content             text    ← the message
segments_used       bigint[]  ← which segment IDs were cited
concepts_used       bigint[]  ← which concept IDs were referenced
embedding           vector(384)  ← so past conversations are searchable
created_at          timestamptz
```
**Purpose:** Permanent memory. Every conversation is stored and searchable. The agent can recall what Chris asked about before.

---

## 6. AI Agent Design

### Agent Type
**ReAct Agent** (Reasoning + Acting) via LangChain. The agent reasons about which tools to use, executes them, observes the results, and repeats until it has enough context to answer.

### Agent Tools

#### Tool 1: `semantic_search`
- **Input:** A natural language query string
- **Process:** Converts query to embedding → searches `segments` table via cosine similarity → returns top N segments
- **Output:** List of segments with episode number, speaker, timestamp, and text
- **Used for:** Most general questions ("what have I said about X?")

#### Tool 2: `episode_lookup`
- **Input:** Episode number (integer)
- **Process:** Fetches all segments for that episode in order
- **Output:** Full episode transcript with speakers and timestamps
- **Used for:** "What happened in episode 45?", "What did we discuss in the early episodes?"

#### Tool 3: `speaker_search`
- **Input:** Speaker name + optional topic query
- **Process:** Filters segments by speaker, optionally combines with semantic search
- **Output:** Segments attributed to that speaker on that topic
- **Used for:** "What did Alex Chen say about distribution?" / "What are my most common arguments?"

#### Tool 4: `concept_search`
- **Input:** Concept name or related phrase
- **Process:** Finds matching concepts → retrieves linked segments → follows relationship graph for related concepts
- **Output:** Segments organised by concept and sub-concept
- **Used for:** "What connects pricing strategy and brand positioning in my episodes?"

#### Tool 5: `memory_recall`
- **Input:** A topic or question
- **Process:** Searches `conversations` table semantically → finds past exchanges where Chris asked about something related
- **Output:** Previous conversation turns with dates
- **Used for:** "Have we talked about this before?", providing continuity across sessions

#### Tool 6: `time_range_search`
- **Input:** Topic + date range (e.g. "last 6 months", "2023")
- **Process:** Filters segments by episode published_date + semantic search
- **Output:** Relevant segments within the time window
- **Used for:** "What's my most recent thinking on X?" / tracking how ideas evolved

---

### Agent System Prompt (Core Design)

The system prompt instructs the agent to:
1. Always ground answers in retrieved segments — do not answer from Claude's general knowledge unless explicitly asked
2. Always cite source: Episode number, speaker name, approximate timestamp
3. Use the format: *"In Episode [N], [Speaker] said: '[quote]' ([timestamp])"*
4. If multiple segments contradict each other, surface the contradiction — Chris's thinking evolves
5. If no relevant segments found, say so clearly rather than hallucinating
6. Maintain conversational tone — this is a working tool, not an academic paper

---

### Retrieval Strategy (Hybrid Search)

For best results, combine two search strategies and merge results:

```
Query: "What have I said about direct-to-consumer?"

Step 1 — Semantic Search:
  → Embed query
  → Find segments with high cosine similarity
  → Returns segments that are conceptually related even if exact words differ

Step 2 — Keyword Search:
  → SQL ILIKE on segment text
  → Returns exact phrase matches that semantic search might miss

Step 3 — Merge & Re-rank:
  → Combine results, remove duplicates
  → Score by: (semantic similarity × 0.6) + (keyword match × 0.4)
  → Return top 8 segments

Step 4 — Agent synthesis:
  → Agent formats the top segments into a coherent answer with citations
```

---

## 7. Data Pipeline Design

### Trigger Options (choose one to start)
| Method | How | Complexity | Recommended |
|---|---|---|---|
| Manual script | Run `python pipeline.py` | Lowest | ✅ Start here |
| GitHub Actions cron | Scheduled weekly job | Medium | ✅ Week 7 target |
| Supabase Edge Function | Webhook on storage upload | Medium | Optional |
| Transistor webhook | Transistor notifies on publish | High | Future |

### Pipeline Flow (Step by Step)

```
START
  │
  ▼
1. CHECK FOR NEW EPISODES
   └── Call Transistor API: GET /v1/episodes
   └── Compare transistor_ids against episodes table
   └── If no new episodes → LOG "Nothing new" → END
  │
  ▼
2. DOWNLOAD JSON
   └── Fetch transcript JSON for new episode
   └── Save raw JSON to local temp file
   └── Validate: does it have segments? Does it have speaker names?
   └── If invalid → LOG error → ALERT → END
  │
  ▼
3. INSERT EPISODE RECORD
   └── INSERT into episodes (transistor_id, title, episode_number, published_date, raw_json)
   └── Get back the new episode.id
  │
  ▼
4. INSERT SEGMENTS
   └── Loop through JSON segments array
   └── For each segment: INSERT into segments (episode_id, speaker, text, start_time, end_time)
   └── Batch insert for performance (100 segments at a time)
  │
  ▼
5. GENERATE EMBEDDINGS
   └── Load sentence-transformer model (all-MiniLM-L6-v2)
   └── For each segment: encode segment.text → 384-dimension vector
   └── UPDATE segments SET embedding = [vector] WHERE id = segment.id
   └── Batch process: 50 segments at a time to manage memory
  │
  ▼
6. EXTRACT CONCEPTS
   └── Run KeyBERT on full episode transcript
   └── Run spaCy NER for people/brands/places
   └── Deduplicate against existing concepts table
   └── INSERT new concepts
   └── INSERT segment_concepts linking table entries
  │
  ▼
7. UPDATE CONCEPT RELATIONSHIPS
   └── Calculate co-occurrence for new concepts vs existing
   └── UPDATE concept_relationships strength scores
  │
  ▼
8. LOG SUCCESS
   └── INSERT pipeline_log (episode_id, status="success", duration, segment_count)
   └── (Optional) Send notification: email or Slack message to Chris
  │
  ▼
END
```

### Error Handling Rules
- If step 3 fails → rollback, log, alert, stop pipeline
- If step 5 fails for a segment → skip that segment, continue, flag for retry
- If duplicate transistor_id → skip silently (idempotent)
- All failures logged to a `pipeline_logs` table in Supabase

---

## 8. Conversation Memory System

This is what makes the system feel alive across sessions.

### Three Memory Layers

```
LAYER 1 — IMMEDIATE CONTEXT (in-memory, within current conversation)
  └── Last 6 message turns passed directly in the prompt
  └── Managed by LangChain ConversationBufferWindowMemory
  └── Lost when session ends (but stored in Supabase)

LAYER 2 — SESSION HISTORY (Supabase query, same day)
  └── On new session start: load last 3 exchanges from conversations table
  └── Gives continuity: "Earlier today you asked about..."
  └── Simple datetime filter query

LAYER 3 — LONG-TERM RECALL (vector search on conversations table)
  └── Embed the current user query
  └── Search conversations.embedding for semantically similar past exchanges
  └── Surface: "You asked something similar on [date]: [past question]"
  └── Agent can reference this in its answer
```

### Conversation Storage Flow
```
Chris sends message
  → Store in conversations (role="user", content=query, session_id)
Agent generates response
  → Store in conversations (role="assistant", content=response, segments_used=[...], concepts_used=[...])
  → Generate embedding for both turns
  → UPDATE conversations SET embedding = [vector]
```

---

## 9. Citation System

Every response must be traceable. This is a non-negotiable design requirement.

### Citation Format in Responses

```
"You've touched on this topic in several episodes.

In Episode 12 (March 2024), you argued that small brands 
should prioritise depth over breadth when it comes to 
distribution: 'One case in one bar beats one bottle in 
six bars.' [Chris, 14:32]

Your guest in Episode 29, Alex Chen, pushed back on this 
slightly, noting that 'the economics change completely 
once you hit 500 cases per month.' [Alex Chen, 08:15]

By Episode 41, your own position had shifted — you said 
'I've changed my mind on this...' [Chris, 22:40]"
```

### How Citations Are Built

Each tool returns segment objects, not raw text. The segment object always contains:
- `episode_number` 
- `speaker`
- `start_time` (formatted as MM:SS)
- `text` (the actual quote)

The agent system prompt instructs Claude to embed these citation references naturally in the response prose, and the Chainlit UI renders them as expandable source cards at the bottom.

### Source Card UI Component
```
┌─────────────────────────────────────────────────┐
│ 📻 Episode 12 · Chris · 14:32                   │
│ "One case in one bar beats one bottle in         │
│  six bars."                                      │
│ [▼ See more context]                             │
└─────────────────────────────────────────────────┘
```

---

## 10. Tech Stack Summary

| Layer | Technology | Why |
|---|---|---|
| Database | Supabase (PostgreSQL + pgvector) | Free, managed, vector search built-in |
| Embeddings | sentence-transformers (all-MiniLM-L6-v2) | Free, runs locally, good quality |
| NLP / Concepts | KeyBERT + spaCy | Standard, well-documented, free |
| AI Agent | LangChain (Python) | Industry standard, great tool support |
| LLM | Claude API (claude-sonnet-4) | Chris already pays, best reasoning |
| Chat UI | Chainlit | Purpose-built for LangChain chat apps |
| Pipeline Scheduling | GitHub Actions | Free, code lives in same repo |
| Language | Python 3.11+ | Best AI/ML ecosystem |
| Version Control | GitHub | Required for GitHub Actions |

---

## 11. Implementation Phases

### Phase 1: Data Foundation (Weeks 1–2)
**Goal:** All 50+ episodes in Supabase, validated, segments queryable

Milestones:
- [ ] Supabase project created, schema deployed
- [ ] Single episode manually imported and verified
- [ ] Batch import script for all 50+ episodes
- [ ] Validation queries pass (segment count, speaker consistency)
- [ ] Embeddings generated for all segments

---

### Phase 2: Knowledge Network (Weeks 3–4)
**Goal:** Concepts extracted, relationships mapped, semantic search working

Milestones:
- [ ] Concept extraction running on full episode set
- [ ] segment_concepts table populated
- [ ] concept_relationships calculated
- [ ] Semantic search function tested: returns relevant segments in <500ms

---

### Phase 3: AI Agent (Weeks 5–6)
**Goal:** Chris can ask questions and get cited answers

Milestones:
- [ ] LangChain agent with 4 core tools (semantic, episode, speaker, memory)
- [ ] Chainlit UI running locally
- [ ] Citation format rendering correctly
- [ ] Conversation memory storing and retrieving correctly
- [ ] Chris tests and gives feedback

---

### Phase 4: Automation & Polish (Weeks 7–8)
**Goal:** Zero-maintenance system, documented, handed off

Milestones:
- [ ] GitHub Actions pipeline running weekly
- [ ] Error handling and pipeline logging complete
- [ ] Admin dashboard showing system status
- [ ] Full documentation written
- [ ] Chris trained on the system

---

## 12. Open Questions & Future Decisions

These are deferred — decide when you reach that phase.

| Question | Options | When to Decide |
|---|---|---|
| Concept extraction quality — is KeyBERT good enough for drinks industry terms? | KeyBERT / Claude-based extraction / manual tagging | Week 3 |
| Should the agent ever answer from Claude's general knowledge (not the vault)? | Vault-only / Hybrid mode / User-selectable | Week 5 |
| How to handle episodes where Chris and guest disagree — show contradiction or synthesise? | Show both views / Let Chris configure | Week 6 |
| Mobile UI in the future? | Chainlit is responsive, low effort to extend | Post-handoff |
| Multiple users (Chris's team)? | Add Supabase Auth, separate conversation histories | Post-handoff |
| Export feature (generate a report from conversation)? | Add to admin dashboard | Post-handoff |

---

*Document last updated: March 2026. Update this document as architectural decisions are made during implementation.*
