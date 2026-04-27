# Maffeo Vault

A conversational AI system that lets Chris query the entire history of the Maffeo Drinks podcast — with citations, permanent memory, and automatic weekly processing.

---

## Phase 1: Setup Checklist

Work through these steps in order. Don't skip ahead.

### Step 1 — Clone and set up Python environment

```bash
# In your terminal
cd ~/Desktop                        # or wherever you keep projects
git clone <your-repo-url> maffeo-vault
cd maffeo-vault

# Create a virtual environment (keeps dependencies isolated)
python3 -m venv venv
venv\Scripts\Activate.ps1            

# Install dependencies
pip install -r requirements.txt
```

### Step 2 — Configure your credentials

```bash
cp .env.example .env
open .env                           # opens in TextEdit — fill in your keys
```

Your `.env` should look like:
```
SUPABASE_URL=https://abcdefgh.supabase.co
SUPABASE_ANON_KEY=eyJhbGci...
```

Find these at: [supabase.com](https://supabase.com) → your project → **Settings → API**

### Step 3 — Create the database schema

1. Go to [supabase.com](https://supabase.com)
2. Open your project → **SQL Editor** → **New Query**
3. Copy and paste the entire contents of `sql/schema.sql`
4. Click **Run**

You should see: "Success. No rows returned."

### Step 4 — Test your connection

```bash
python scripts/test_connection.py
```

Expected output: `✓ All tests passed!`

If it fails, re-check your `.env` credentials.

### Step 5 — Inspect your first JSON file

Before importing, check what your JSON looks like:

```bash
python scripts/import_episode.py data/raw/your_episode.json --inspect
```

This prints the JSON structure WITHOUT writing to the database. Use it to verify the field names match what the parser expects.

If the field names are different (e.g. `episode_number` instead of `number`), update the constants at the top of `pipeline/parser.py`.

### Step 6 — Dry run (validates without writing)

```bash
python scripts/import_episode.py data/raw/your_episode.json --dry-run
```

Parses and validates the file, shows you what would be imported — but doesn't touch the database.

### Step 7 — Import your first episode

```bash
python scripts/import_episode.py data/raw/your_episode.json
```

Expected output: `✓ Import complete! Episode: [title], Segments: [n]`

### Step 8 — Verify the import

```bash
python scripts/verify_episode.py
```

This checks the most recently imported episode and shows:
- Segment count
- Speaker breakdown
- Any missing or empty data
- A preview of the first 5 segments

---

## Project Structure

```
maffeo-vault/
├── pipeline/
│   ├── config.py       — Supabase client + shared constants
│   ├── parser.py       — Reads and validates JSON files
│   └── importer.py     — Writes to Supabase
│
├── scripts/
│   ├── test_connection.py  — Verify setup (run first)
│   ├── import_episode.py   — Import a single episode
│   └── verify_episode.py   — Check imported data quality
│
├── sql/
│   └── schema.sql      — Run this in Supabase SQL Editor
│
├── data/
│   └── raw/            — Put your JSON files here (gitignored)
│
├── .env.example        — Copy to .env and fill in your keys
├── .gitignore
└── requirements.txt
```

---

## Common Issues

**`EnvironmentError: Missing Supabase credentials`**
→ Check your `.env` file exists and has the right keys.

**`relation "episodes" does not exist`**
→ Run `sql/schema.sql` in the Supabase SQL Editor.

**`Parse error: JSON has no 'transcript' field`**
→ Run `--inspect` on your file and check what key holds the transcript. Update `pipeline/parser.py` constants.

**`Skipped: Episode is already in the database`**
→ That episode was imported before. This is intentional — imports are safe to re-run.

---

## What's Coming (Later Phases)

- **Phase 2:** Embeddings + concept extraction (semantic search)
- **Phase 3:** LangChain AI Agent + Chainlit chat UI
- **Phase 4:** Automated weekly pipeline via GitHub Actions
