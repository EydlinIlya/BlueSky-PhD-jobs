-- SEO job metadata used for truthful active-job pages and JobPosting markup.
-- Apply before deploying ingestion or running scripts/backfill_seo_metadata.py.

ALTER TABLE phd_positions
  ADD COLUMN IF NOT EXISTS job_title TEXT,
  ADD COLUMN IF NOT EXISTS hiring_organization TEXT,
  ADD COLUMN IF NOT EXISTS application_url TEXT,
  ADD COLUMN IF NOT EXISTS application_deadline DATE,
  ADD COLUMN IF NOT EXISTS location_text TEXT,
  ADD COLUMN IF NOT EXISTS seo_enriched_at TIMESTAMPTZ;

ALTER TABLE phd_positions_staging
  ADD COLUMN IF NOT EXISTS job_title TEXT,
  ADD COLUMN IF NOT EXISTS hiring_organization TEXT,
  ADD COLUMN IF NOT EXISTS application_url TEXT,
  ADD COLUMN IF NOT EXISTS application_deadline DATE,
  ADD COLUMN IF NOT EXISTS location_text TEXT,
  ADD COLUMN IF NOT EXISTS seo_enriched_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS phd_positions_seo_backfill_idx
  ON phd_positions (created_at DESC)
  WHERE is_verified_job = TRUE
    AND duplicate_of IS NULL
    AND seo_enriched_at IS NULL;
