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
            if "duplicate_of" in post:
                record["duplicate_of"] = post["duplicate_of"]

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

    def get_canonical_posts(self) -> list[dict]:
        """Get all canonical posts for deduplication.

        Returns posts where duplicate_of IS NULL and is_verified_job is True.
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

    # -------------------------------------------------------------------------
    # Pipeline support methods
    # -------------------------------------------------------------------------

    def _run_date_str(self, run_date) -> str:
        return run_date.isoformat() if hasattr(run_date, "isoformat") else str(run_date)

    def get_or_create_run(self, run_date) -> dict:
        """Upsert a pipeline_runs row and return it."""
        run_date_str = self._run_date_str(run_date)
        response = (
            self.client.table("pipeline_runs")
            .select("*")
            .eq("run_date", run_date_str)
            .execute()
        )
        if response.data:
            return response.data[0]
        response = (
            self.client.table("pipeline_runs")
            .insert({"run_date": run_date_str})
            .execute()
        )
        return response.data[0]

    def update_run(self, run_date, **fields) -> None:
        """Update fields on a pipeline_runs row."""
        run_date_str = self._run_date_str(run_date)
        self.client.table("pipeline_runs").update(fields).eq(
            "run_date", run_date_str
        ).execute()

    def insert_staging(self, run_date, posts: list[dict]) -> None:
        """Bulk-upsert posts into phd_positions_staging."""
        if not posts:
            return
        run_date_str = self._run_date_str(run_date)
        records = []
        for post in posts:
            record = {
                "run_date": run_date_str,
                "uri": post["uri"],
                "message": post.get("message"),
                "raw_text": post.get("raw_text"),
                "metadata_text": post.get("metadata_text"),
                "url": post.get("url"),
                "user_handle": post.get("user"),
                "created_at": post.get("created"),
                "source": post.get("source"),
                "quoted_uri": post.get("quoted_uri"),
                "reply_parent_uri": post.get("reply_parent_uri"),
                "is_verified_job": post.get("is_verified_job"),
                "disciplines": post.get("disciplines"),
                "country": post.get("country"),
                "position_type": post.get("position_type"),
            }
            records.append(record)
        self.client.table("phd_positions_staging").upsert(
            records, on_conflict="run_date,uri"
        ).execute()

    def get_staging_unfiltered(
        self, run_date, source: str | None = None
    ) -> list[dict]:
        """Return staging rows where filter_completed=False."""
        run_date_str = self._run_date_str(run_date)
        query = (
            self.client.table("phd_positions_staging")
            .select("*")
            .eq("run_date", run_date_str)
            .eq("filter_completed", False)
        )
        if source:
            query = query.eq("source", source)
        return query.execute().data

    def update_staging_filter(self, run_date, uri: str, result: dict) -> None:
        """Set LLM output fields and mark filter_completed=True for one row."""
        run_date_str = self._run_date_str(run_date)
        update_data = {
            "is_verified_job": result.get("is_verified_job"),
            "disciplines": result.get("disciplines"),
            "country": result.get("country"),
            "position_type": result.get("position_type"),
            "filter_completed": True,
        }
        self.client.table("phd_positions_staging").update(update_data).eq(
            "run_date", run_date_str
        ).eq("uri", uri).execute()

    def get_staging_verified(self, run_date) -> list[dict]:
        """Return staging rows where is_verified_job=True."""
        run_date_str = self._run_date_str(run_date)
        return (
            self.client.table("phd_positions_staging")
            .select("*")
            .eq("run_date", run_date_str)
            .eq("is_verified_job", True)
            .execute()
            .data
        )

    def get_staging_all(self, run_date) -> list[dict]:
        """Return all staging rows for this run_date."""
        run_date_str = self._run_date_str(run_date)
        return (
            self.client.table("phd_positions_staging")
            .select("*")
            .eq("run_date", run_date_str)
            .execute()
            .data
        )

    def update_staging_dedup(
        self, run_date, uri: str, duplicate_of: str
    ) -> None:
        """Set duplicate_of on a staging row."""
        run_date_str = self._run_date_str(run_date)
        self.client.table("phd_positions_staging").update(
            {"duplicate_of": duplicate_of}
        ).eq("run_date", run_date_str).eq("uri", uri).execute()

    def delete_staging(self, run_date) -> None:
        """Delete all staging rows for this run_date (post-publish cleanup)."""
        run_date_str = self._run_date_str(run_date)
        self.client.table("phd_positions_staging").delete().eq(
            "run_date", run_date_str
        ).execute()

    def delete_run(self, run_date) -> None:
        """Delete the pipeline_runs row for this run_date.

        Called after a successful publish so the next run of the same day
        creates a fresh row and runs all stages again (for multiple daily runs).
        """
        run_date_str = self._run_date_str(run_date)
        self.client.table("pipeline_runs").delete().eq(
            "run_date", run_date_str
        ).execute()

    def update_post_classification(
        self,
        uri: str,
        disciplines: list,
        country: str,
        position_type: list,
    ) -> None:
        """Update disciplines, country, and position_type on an existing phd_positions row."""
        try:
            self.client.table(self.table).update(
                {
                    "disciplines": disciplines,
                    "country": country,
                    "position_type": position_type,
                }
            ).eq("uri", uri).execute()
        except Exception as e:
            logger.error(f"Failed to update classification for {uri}: {e}")

    def update_post_message(
        self,
        uri: str,
        message: str,
        raw_text: str | None = None,
        metadata_text: str | None = None,
    ) -> None:
        """Update the message of an existing phd_positions entry.

        Args:
            uri: URI of the post to update
            message: New message text
            raw_text: Unused (phd_positions has no raw_text column; accepted for API symmetry)
            metadata_text: Unused (phd_positions has no metadata_text column)
        """
        try:
            self.client.table(self.table).update({"message": message}).eq(
                "uri", uri
            ).execute()
        except Exception as e:
            logger.error(f"Failed to update message for {uri}: {e}")

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
