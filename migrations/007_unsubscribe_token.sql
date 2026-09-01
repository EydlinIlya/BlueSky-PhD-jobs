-- Migration 007: unsubscribe-token foundation (superseded by migration 008).
-- Adds a secret per-subscription token for unauthenticated preference changes.
-- Migration 008 removes this first-generation RPC and replaces it with
-- scanner-safe HTTP POST flows for one alert or all weekly alerts.
-- Requires migration 004 (subscriptions).

-- 1. Secret token column (unguessable; distinct from the row's primary key).
ALTER TABLE subscriptions
    ADD COLUMN IF NOT EXISTS unsubscribe_token UUID UNIQUE DEFAULT gen_random_uuid();

-- Backfill any pre-existing rows, then enforce NOT NULL.
UPDATE subscriptions SET unsubscribe_token = gen_random_uuid() WHERE unsubscribe_token IS NULL;
ALTER TABLE subscriptions ALTER COLUMN unsubscribe_token SET NOT NULL;

-- 2. Token-scoped unsubscribe. Turns email delivery off (and cadence to 'off')
--    for the matching subscription. Returns a human-readable filter label for a
--    friendly confirmation page, or NULL if the token is unknown/already used.
CREATE OR REPLACE FUNCTION unsubscribe_by_token(p_token uuid)
RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    lbl text;
BEGIN
    UPDATE subscriptions
       SET deliver_email = false,
           cadence       = 'off'
     WHERE unsubscribe_token = p_token
     RETURNING NULLIF(
                 array_to_string(disciplines || position_types || countries, ' · '),
                 ''
               )
        INTO lbl;

    IF NOT FOUND THEN
        RETURN NULL;
    END IF;
    RETURN COALESCE(lbl, 'all positions');
END;
$$;

-- Only expose the narrow RPC to the public roles — never the table.
REVOKE ALL ON FUNCTION unsubscribe_by_token(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION unsubscribe_by_token(uuid) TO anon, authenticated;
