"""CSV storage backend."""

import csv
import json
from pathlib import Path

from .base import StorageBackend


class CSVStorage(StorageBackend):
    """CSV file storage backend."""

    def __init__(self, filename: str = "phd_positions.csv"):
        """Initialize CSV storage.

        Args:
            filename: Path to CSV file
        """
        self.filename = filename
        self.base_fields = ["uri", "message", "url", "user", "created"]
        self.extra_fields = ["disciplines", "is_verified_job", "country", "position_type"]

    def save_posts(self, posts: list[dict]) -> int:
        """Save posts to CSV file.

        Args:
            posts: List of post dictionaries

        Returns:
            Number of posts saved
        """
        if not posts:
            return 0

        # Determine fieldnames based on what fields are present
        fieldnames = self.base_fields.copy()
        if any(f in posts[0] for f in self.extra_fields):
            fieldnames.extend([f for f in self.extra_fields if f in posts[0]])

        # Serialize list fields to JSON for CSV compatibility
        rows = []
        for post in posts:
            row = dict(post)
            if "disciplines" in row and isinstance(row["disciplines"], list):
                row["disciplines"] = json.dumps(row["disciplines"])
            if "position_type" in row and isinstance(row["position_type"], list):
                row["position_type"] = json.dumps(row["position_type"])
            rows.append(row)

        with open(self.filename, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)

        return len(rows)

    def get_existing_uris(self) -> set[str]:
        """Get URIs from existing CSV file.

        Returns:
            Set of URIs in the CSV file
        """
        uris = set()
        if not Path(self.filename).exists():
            return uris

        try:
            with open(self.filename, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if "uri" in row:
                        uris.add(row["uri"])
        except (IOError, csv.Error):
            pass

        return uris

    def get_last_timestamp(self) -> str | None:
        """Get most recent timestamp from CSV.

        Returns:
            Most recent created timestamp or None
        """
        if not Path(self.filename).exists():
            return None

        timestamps = []
        try:
            with open(self.filename, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if "created" in row:
                        timestamps.append(row["created"])
        except (IOError, csv.Error):
            return None

        return max(timestamps) if timestamps else None
