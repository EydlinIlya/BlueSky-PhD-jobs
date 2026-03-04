-- Migration 002: 4-stage persistent pipeline tables
-- Run after 001. Required for --storage supabase.
--
-- pipeline_runs   — one row per active pipeline run; tracks which stages have
--                   completed. Deleted automatically after a successful publish
--                   so the next run of the same day starts fresh.
--
-- phd_positions_staging — transient staging area for posts in-flight during a
--                         run. Deleted after publish. Allows crash recovery:
--                         re-running on the same day resumes from the last
--                         incomplete stage.

CREATE TABLE pipeline_runs (
    id SERIAL PRIMARY KEY,
    run_date DATE UNIQUE NOT NULL,
    fetch_completed_at TIMESTAMPTZ,
    filter_completed_at TIMESTAMPTZ,
    dedup_completed_at TIMESTAMPTZ,
    raw_count INT DEFAULT 0,
    verified_count INT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE phd_positions_staging (
    id SERIAL PRIMARY KEY,
    run_date DATE NOT NULL,
    uri TEXT NOT NULL,
    message TEXT,
    raw_text TEXT,
    metadata_text TEXT,
    url TEXT,
    user_handle TEXT,
    created_at TIMESTAMPTZ,
    source TEXT,
    quoted_uri TEXT,
    reply_parent_uri TEXT,
    is_verified_job BOOLEAN,
    disciplines TEXT[],
    country TEXT,
    position_type TEXT[],
    duplicate_of TEXT,
    filter_completed BOOLEAN DEFAULT FALSE,
    staged_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(run_date, uri)
);
