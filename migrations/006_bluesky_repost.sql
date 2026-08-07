-- Migration 006: Bluesky repost bot watermark
--
-- Adds a per-row watermark so a standalone cron (scripts/repost_to_bluesky.py)
-- can quote-post non-aggregator positions to a dedicated Bluesky account exactly
-- once. Mirrors the posted_to_telegram_at pattern from migration 001.
--
-- NULL  = not yet reposted (a candidate for the bot)
-- set   = already reposted at this timestamp
--
-- Apply in the Supabase SQL editor.

ALTER TABLE phd_positions
  ADD COLUMN IF NOT EXISTS reposted_to_bluesky_at TIMESTAMPTZ;  -- NULL = un-reposted

-- Keeps the bot's "find un-reposted" query fast.
CREATE INDEX IF NOT EXISTS phd_positions_unreposted_idx
  ON phd_positions (created_at)
  WHERE reposted_to_bluesky_at IS NULL;

-- ---------------------------------------------------------------------------
-- ONE-TIME START-FRESH STEP (run once, right after switching BLUESKY_HANDLE/
-- PASSWORD to the new bot account):
--
-- Pre-mark the entire existing backlog as already-reposted so the bot only
-- handles positions ingested AFTER launch. Without this, every existing
-- non-aggregator position would be treated as a candidate and flood the feed.
--
--   UPDATE phd_positions
--     SET reposted_to_bluesky_at = NOW()
--     WHERE reposted_to_bluesky_at IS NULL;
-- ---------------------------------------------------------------------------
