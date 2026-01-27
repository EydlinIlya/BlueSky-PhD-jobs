"""Mock storage backend for testing."""

from datetime import datetime

from src.storage.base import StorageBackend


class MockStorage(StorageBackend):
    """In-memory storage backend for testing.

    Simulates Supabase-like behavior with a disciplines TEXT[] column
    and upsert-on-conflict semantics.
    """

    def __init__(self):
        self.posts: dict[str, dict] = {}  # uri -> record

    def save_posts(self, posts: list[dict]) -> int:
        if not posts:
            return 0

        for post in posts:
            uri = post["uri"]
            record = {
                "uri": uri,
                "message": post["message"],
                "url": post["url"],
                "user_handle": post.get("user", post.get("user_handle")),
                "created_at": post.get("created", post.get("created_at")),
                "indexed_at": datetime.now().isoformat(),
            }

            if "disciplines" in post and post["disciplines"] is not None:
                record["disciplines"] = post["disciplines"]
            if "is_verified_job" in post:
                record["is_verified_job"] = post["is_verified_job"]
            if "country" in post and post["country"] is not None:
                record["country"] = post["country"]
            if "position_type" in post and post["position_type"] is not None:
                record["position_type"] = post["position_type"]

            # Upsert: overwrite if uri exists
            self.posts[uri] = record

        return len(posts)

    def get_existing_uris(self) -> set[str]:
        return set(self.posts.keys())

    def get_last_timestamp(self) -> str | None:
        if not self.posts:
            return None
        timestamps = [
            p["created_at"] for p in self.posts.values() if p.get("created_at")
        ]
        return max(timestamps) if timestamps else None

    def get_post(self, uri: str) -> dict | None:
        """Get a single post by URI (test helper)."""
        return self.posts.get(uri)

    def get_all_posts(self) -> list[dict]:
        """Get all posts (test helper)."""
        return list(self.posts.values())

    def clear(self):
        """Clear all stored data (test helper)."""
        self.posts.clear()
