"""Pipeline run checkpointing.

Checkpoint state is stored in the ``pipeline_runs`` Supabase table.
CRUD operations are implemented as methods on ``SupabaseStorage``:

- ``get_or_create_run(run_date)``  — upsert a run row and return it
- ``update_run(run_date, **fields)`` — update completion timestamps / counts

This module documents the expected schema; see ``storage/supabase.py`` for
the actual implementation.

Required SQL (run once):

    CREATE TABLE pipeline_runs (
        id SERIAL PRIMARY KEY,
        run_date DATE UNIQUE NOT NULL,
        fetch_completed_at TIMESTAMPTZ,
        filter_completed_at TIMESTAMPTZ,
        dedup_completed_at TIMESTAMPTZ,
        publish_completed_at TIMESTAMPTZ,
        raw_count INT DEFAULT 0,
        verified_count INT DEFAULT 0,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
"""
