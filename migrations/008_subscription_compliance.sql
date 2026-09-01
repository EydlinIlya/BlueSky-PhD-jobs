-- Migration 008: explicit weekly-alert consent, safe unsubscribe, and account deletion.
-- Requires migrations 003, 004, 005, and 007.

-- Saved searches are retained, but legacy delivery is paused until the owner
-- explicitly confirms the new consent language in the website.
ALTER TABLE public.subscriptions
    ADD COLUMN IF NOT EXISTS email_consent_at timestamptz,
    ADD COLUMN IF NOT EXISTS email_consent_version text,
    ADD COLUMN IF NOT EXISTS unsubscribed_at timestamptz,
    ADD COLUMN IF NOT EXISTS last_processed_at timestamptz;

-- Retire migration 007's GET-era RPC. The new human page and HTTP endpoint use
-- the explicit current/all functions below.
DROP FUNCTION IF EXISTS public.unsubscribe_by_token(uuid);

UPDATE public.subscriptions
   SET cadence = 'weekly',
       deliver_email = false,
       email_consent_at = NULL,
       email_consent_version = NULL
 WHERE email_consent_version IS NULL;

ALTER TABLE public.subscriptions
    ALTER COLUMN cadence SET DEFAULT 'weekly',
    ALTER COLUMN deliver_email SET DEFAULT false;

ALTER TABLE public.subscriptions DROP CONSTRAINT IF EXISTS subscriptions_cadence_check;
ALTER TABLE public.subscriptions
    ADD CONSTRAINT subscriptions_cadence_weekly_only CHECK (cadence = 'weekly');

DROP INDEX IF EXISTS subscriptions_cadence_idx;
CREATE INDEX IF NOT EXISTS subscriptions_weekly_delivery_idx
    ON public.subscriptions (created_at)
    WHERE deliver_email = true AND email_consent_at IS NOT NULL;

CREATE OR REPLACE FUNCTION public.normalized_text_array(value text[])
RETURNS text[]
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
AS $$
    SELECT COALESCE(array_agg(item ORDER BY item), ARRAY[]::text[])
      FROM (SELECT DISTINCT btrim(v) AS item
              FROM unnest(COALESCE(value, ARRAY[]::text[])) AS v
             WHERE btrim(v) <> '') AS normalized;
$$;

-- Keep one representative of exact legacy duplicates before enforcing the
-- invariant. Account ownership and the saved search itself are preserved.
WITH ranked AS (
    SELECT id,
           row_number() OVER (
               PARTITION BY user_id,
                            lower(btrim(COALESCE(query_text, ''))),
                            public.normalized_text_array(disciplines),
                            public.normalized_text_array(countries),
                            public.normalized_text_array(position_types),
                            COALESCE(hide_aggregators, false)
               ORDER BY created_at, id
           ) AS duplicate_number
      FROM public.subscriptions
)
DELETE FROM public.subscriptions s
 USING ranked r
 WHERE s.id = r.id AND r.duplicate_number > 1;

CREATE UNIQUE INDEX IF NOT EXISTS subscriptions_unique_normalized_filter_idx
    ON public.subscriptions (
        user_id,
        lower(btrim(COALESCE(query_text, ''))),
        public.normalized_text_array(disciplines),
        public.normalized_text_array(countries),
        public.normalized_text_array(position_types),
        COALESCE(hide_aggregators, false)
    );

-- Keep the profile copy current when an Auth user changes their address.
CREATE OR REPLACE FUNCTION public.sync_profile_email()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    UPDATE public.profiles SET email = NEW.email WHERE id = NEW.id;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS on_auth_user_email_changed ON auth.users;
CREATE TRIGGER on_auth_user_email_changed
    AFTER UPDATE OF email ON auth.users
    FOR EACH ROW
    WHEN (OLD.email IS DISTINCT FROM NEW.email)
    EXECUTE FUNCTION public.sync_profile_email();

-- Token-scoped, idempotent unsubscribe operations. These functions expose no
-- account identity and can only turn delivery off.
DROP FUNCTION IF EXISTS public.unsubscribe_subscription_by_token(uuid);
CREATE FUNCTION public.unsubscribe_subscription_by_token(p_token uuid)
RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    was_enabled boolean;
BEGIN
    SELECT deliver_email INTO was_enabled
      FROM public.subscriptions
     WHERE unsubscribe_token = p_token;
    IF NOT FOUND THEN
        RETURN 'not-found';
    END IF;
    UPDATE public.subscriptions
       SET deliver_email = false,
           unsubscribed_at = COALESCE(unsubscribed_at, now())
     WHERE unsubscribe_token = p_token;
    RETURN CASE WHEN was_enabled THEN 'unsubscribed' ELSE 'already-unsubscribed' END;
END;
$$;

DROP FUNCTION IF EXISTS public.unsubscribe_all_by_token(uuid);
CREATE FUNCTION public.unsubscribe_all_by_token(p_token uuid)
RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    owner_id uuid;
    enabled_count integer;
BEGIN
    SELECT user_id INTO owner_id
      FROM public.subscriptions
     WHERE unsubscribe_token = p_token;
    IF owner_id IS NULL THEN
        RETURN 'not-found';
    END IF;

    SELECT count(*) INTO enabled_count
      FROM public.subscriptions
     WHERE user_id = owner_id AND deliver_email = true;

    UPDATE public.subscriptions
       SET deliver_email = false,
           unsubscribed_at = COALESCE(unsubscribed_at, now())
     WHERE user_id = owner_id;
    RETURN CASE WHEN enabled_count > 0 THEN 'unsubscribed' ELSE 'already-unsubscribed' END;
END;
$$;

REVOKE ALL ON FUNCTION public.unsubscribe_subscription_by_token(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.unsubscribe_all_by_token(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.unsubscribe_subscription_by_token(uuid) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION public.unsubscribe_all_by_token(uuid) TO anon, authenticated;

-- Deleting the Auth record activates the existing ON DELETE CASCADE foreign
-- keys for profiles, follows, and subscriptions.
CREATE OR REPLACE FUNCTION public.delete_own_account()
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    caller_id uuid := auth.uid();
BEGIN
    IF caller_id IS NULL THEN
        RAISE EXCEPTION 'Authentication required';
    END IF;
    DELETE FROM auth.users WHERE id = caller_id;
END;
$$;

REVOKE ALL ON FUNCTION public.delete_own_account() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.delete_own_account() TO authenticated;
