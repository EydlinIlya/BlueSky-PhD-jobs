-- Migration 005: Follows
-- account_follows: follow specific Bluesky posters (aggregators / universities /
--   labs) -> the "Following" stream shows only their positions.
-- topic_follows: follow disciplines/countries -> powers the "For me" tab.
-- Requires migration 003 (auth/profiles).

CREATE TABLE account_follows (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    handle     TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_id, handle)
);

CREATE TABLE topic_follows (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    token      TEXT NOT NULL,                              -- e.g. 'Computer Science' or 'Germany'
    kind       TEXT NOT NULL CHECK (kind IN ('discipline', 'country')),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_id, token)
);

ALTER TABLE account_follows ENABLE ROW LEVEL SECURITY;
ALTER TABLE topic_follows  ENABLE ROW LEVEL SECURITY;

CREATE POLICY "own acct follows" ON account_follows
    FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);
CREATE POLICY "own topic follows" ON topic_follows
    FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);
