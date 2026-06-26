-- Migration 003: User profiles (Supabase Auth)
-- Enables account creation (email + Google + GitHub via Supabase Auth / GoTrue).
-- One profile row per auth.users row, created automatically on sign-up.
--
-- Manual setup in the Supabase dashboard (not expressible in SQL):
--   Auth -> Providers: enable Email, Google, GitHub.
--   Add OAuth client IDs/secrets (Google Cloud console + GitHub OAuth app).
--   Auth -> URL Configuration: add redirect URLs for https://phdsky.org and
--   http://localhost (local dev).

CREATE TABLE profiles (
    id           UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    display_name TEXT,
    handle       TEXT,
    email        TEXT,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

-- Owner-only access. The public anon key must NOT be able to read other users.
ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;

CREATE POLICY "own profile read"   ON profiles FOR SELECT USING (auth.uid() = id);
CREATE POLICY "own profile insert" ON profiles FOR INSERT WITH CHECK (auth.uid() = id);
CREATE POLICY "own profile update" ON profiles FOR UPDATE USING (auth.uid() = id);

-- Auto-create a profile row whenever a new auth user is created.
CREATE OR REPLACE FUNCTION handle_new_user()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    INSERT INTO public.profiles (id, email, display_name)
    VALUES (
        NEW.id,
        NEW.email,
        COALESCE(NEW.raw_user_meta_data->>'full_name', NEW.raw_user_meta_data->>'name')
    )
    ON CONFLICT (id) DO NOTHING;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION handle_new_user();
