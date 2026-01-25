"""Supabase storage backend."""

import os
from datetime import datetime

from supabase import create_client, Client

from .base import StorageBackend


class SupabaseStorage(StorageBackend):
    """Supabase PostgreSQL storage backend."""

    def __init__(
        self,
        url: str | None = None,
        key: str | None = None,
        table: str = "phd_positions",
    ):
        """Initialize Supabase storage.

        Args:
            url: Supabase project URL (or SUPABASE_URL env var)
            key: Supabase anon key (or SUPABASE_KEY env var)
            table: Table name to use
        """
        url = url or os.environ.get("SUPABASE_URL")
        key = key or os.environ.get("SUPABASE_KEY")

        if not url or not key:
            raise ValueError(
                "Supabase credentials required. Set SUPABASE_URL and SUPABASE_KEY "
                "environment variables or pass url and key parameters."
            )

        self.client: Client = create_client(url, key)
        self.table = table

    def save_posts(self, posts: list[dict]) -> int:
        """Save posts to Supabase using upsert.

        Args:
            posts: List of post dictionaries

        Returns:
            Number of posts saved
        """
        if not posts:
            return 0

        # Transform posts to match Supabase schema
        records = []
        for post in posts:
            record = {
                "uri": post["uri"],
                "message": post["message"],
                "url": post["url"],
                "user_handle": post["user"],
                "created_at": post["created"],
                "indexed_at": datetime.now().isoformat(),
            }

            # Add optional fields if present
            if "discipline" in post:
                record["discipline"] = post["discipline"]
            if "is_verified_job" in post:
                record["is_verified_job"] = post["is_verified_job"]

            records.append(record)

        # Upsert to avoid duplicates (uri is unique)
        self.client.table(self.table).upsert(records, on_conflict="uri").execute()

        return len(records)

    def get_existing_uris(self) -> set[str]:
        """Get all URIs from Supabase.

        Returns:
            Set of URIs in the database
        """
        response = self.client.table(self.table).select("uri").execute()
        return {row["uri"] for row in response.data}

    def get_last_timestamp(self) -> str | None:
        """Get most recent post timestamp from Supabase.

        Returns:
            Most recent created_at timestamp or None
        """
        response = (
            self.client.table(self.table)
            .select("created_at")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )

        if response.data:
            return response.data[0]["created_at"]
        return None
