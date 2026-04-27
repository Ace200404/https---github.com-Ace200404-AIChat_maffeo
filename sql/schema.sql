-- ============================================================
-- MAFFEO VAULT — Database Schema
-- Run this entire file in: Supabase → SQL Editor → New Query
-- ============================================================

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS episodes (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    transistor_id       TEXT UNIQUE NOT NULL,
    episode_number      INTEGER,
    title               TEXT NOT NULL,
    published_date      DATE,
    duration_seconds    INTEGER,
    raw_json            JSONB NOT NULL,
    processed_at        TIMESTAMPTZ,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_episodes_number    ON episodes(episode_number);
CREATE INDEX IF NOT EXISTS idx_episodes_published ON episodes(published_date);

CREATE TABLE IF NOT EXISTS speakers (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name                TEXT UNIQUE NOT NULL,
    is_host             BOOLEAN DEFAULT FALSE,
    total_segments      INTEGER DEFAULT 0,
    first_episode_id    BIGINT REFERENCES episodes(id),
    notes               TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS segments (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    episode_id          BIGINT NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
    episode_number      INTEGER,
    speaker             TEXT NOT NULL,
    text                TEXT NOT NULL,
    start_time          FLOAT,
    end_time            FLOAT,
    word_count          INTEGER,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_segments_episode  ON segments(episode_id);
CREATE INDEX IF NOT EXISTS idx_segments_speaker  ON segments(speaker);
CREATE INDEX IF NOT EXISTS idx_segments_ep_num   ON segments(episode_number);
CREATE INDEX IF NOT EXISTS idx_segments_text_fts
    ON segments USING GIN (to_tsvector('english', text));

CREATE TABLE IF NOT EXISTS pipeline_logs (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    transistor_id       TEXT,
    episode_number      INTEGER,
    status              TEXT NOT NULL,
    segment_count       INTEGER DEFAULT 0,
    error_message       TEXT,
    duration_seconds    FLOAT,
    ran_at              TIMESTAMPTZ DEFAULT NOW()
);
