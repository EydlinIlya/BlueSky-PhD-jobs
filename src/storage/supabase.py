"""Supabase storage backend."""

import logging
import os
from datetime import datetime

from supabase import create_client, Client

from .base import StorageBackend

logger = logging.getLogger(__name__)


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
            if "disciplines" in post:
                record["disciplines"] = post["disciplines"]  # PostgreSQL handles list as array
            if "is_verified_job" in post:
                record["is_verified_job"] = post["is_verified_job"]
            if "country" in post:
                record["country"] = post["country"]
            if "position_type" in post:
                record["position_type"] = post["position_type"]

            records.append(record)

        # Upsert to avoid duplicates (uri is unique)
        try:
            self.client.table(self.table).upsert(records, on_conflict="uri").execute()
            return len(records)
        except Exception as e:
            logger.error(f"Failed to save posts to Supabase: {e}")
            return 0

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

    def get_posts_for_dedup(self) -> list[dict]:
        """Get all canonical Bluesky posts for deduplication.

        Returns posts where duplicate_of IS NULL and is_verified_job is True,
        with only the fields needed for similarity comparison.
        """
        all_posts = []
        page_size = 1000
        offset = 0

        while True:
            response = (
                self.client.table(self.table)
                .select("uri, message, created_at")
                .eq("is_verified_job", True)
                .is_("duplicate_of", "null")
                .range(offset, offset + page_size - 1)
                .execute()
            )

            if not response.data:
                break

            all_posts.extend(response.data)

            if len(response.data) < page_size:
                break
            offset += page_size

        return all_posts

    def mark_duplicate(self, old_uri: str, new_uri: str) -> bool:
        """Mark an old post as a duplicate of a newer post.

        Args:
            old_uri: URI of the older post to mark as duplicate
            new_uri: URI of the newer (canonical) post
        """
        try:
            self.client.table(self.table).update(
                {"duplicate_of": new_uri}
            ).eq("uri", old_uri).execute()
            return True
        except Exception as e:
            logger.error(f"Failed to mark duplicate {old_uri}: {e}")
            return False

    def mark_duplicates_batch(self, updates: list[tuple[str, str]]) -> int:
        """Mark multiple posts as duplicates.

        Args:
            updates: List of (old_uri, canonical_uri) tuples

        Returns:
            Number of posts updated
        """
        count = 0
        for old_uri, canonical_uri in updates:
            if self.mark_duplicate(old_uri, canonical_uri):
                count += 1
        return count
