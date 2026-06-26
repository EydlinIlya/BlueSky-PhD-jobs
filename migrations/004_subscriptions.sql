-- Migration 004: Saved-search subscriptions
-- A subscription is a saved filter that re-runs as new positions are indexed;
-- new matches are delivered by email digest (and, later, RSS).
-- Requires migration 003 (auth/profiles).

CREATE TABLE subscriptions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    query_text      TEXT,                       -- free-text keyword match (optional)
    disciplines     TEXT[] DEFAULT '{}',        -- OR within; empty = any
    countries       TEXT[] DEFAULT '{}',        -- OR within; empty = any
    position_types  TEXT[] DEFAULT '{}',        -- OR within; empty = any
    hide_aggregators BOOLEAN DEFAULT FALSE,
    cadence         TEXT NOT NULL DEFAULT 'daily'
                    CHECK (cadence IN ('instant', 'daily', 'weekly', 'off')),
    deliver_email   BOOLEAN DEFAULT TRUE,
    deliver_rss     BOOLEAN DEFAULT FALSE,
    -- Watermark: max created_at already emailed. The digest sends positions with
    -- created_at > last_notified_at, then advances it. Idempotent on failure.
    last_notified_at TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Owner-only access (the frontend uses the public anon key with an auth session).
ALTER TABLE subscriptions ENABLE ROW LEVEL SECURITY;
CREATE POLICY "own subs all" ON subscriptions
    FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

-- The digest job reads due subscriptions with the service-role key (bypasses RLS).
CREATE INDEX subscriptions_cadence_idx ON subscriptions (cadence)
    WHERE cadence <> 'off';
