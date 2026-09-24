-- Migration 009: Owner-wide unsubscribe for combined saved-search digests.
-- A token from any one of the owner's subscriptions authorizes only the safe,
-- narrowing action of disabling email delivery for all of that owner's alerts.
-- Requires migration 007 (unsubscribe_token).

CREATE OR REPLACE FUNCTION unsubscribe_owner_by_token(p_token uuid)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    owner_id uuid;
    changed integer;
BEGIN
    SELECT user_id
      INTO owner_id
      FROM subscriptions
     WHERE unsubscribe_token = p_token;

    IF NOT FOUND THEN
        RETURN 0;
    END IF;

    UPDATE subscriptions
       SET deliver_email = false,
           cadence       = 'off'
     WHERE user_id = owner_id
       AND (deliver_email = true OR cadence <> 'off');

    GET DIAGNOSTICS changed = ROW_COUNT;
    RETURN changed;
END;
$$;

REVOKE ALL ON FUNCTION unsubscribe_owner_by_token(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION unsubscribe_owner_by_token(uuid) TO anon, authenticated;
