"""Base classes for data sources."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Post:
    """Unified post data from any source."""

    uri: str
    message: str
    url: str
    user_handle: str
    created_at: str
    source: str
    country: str | None = None
    disciplines: list[str] = field(default_factory=list)
    position_type: list[str] = field(default_factory=list)
    is_verified_job: bool | None = None
    quoted_uri: str | None = None
    reply_parent_uri: str | None = None

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        d = {
            "uri": self.uri,
            "message": self.message,
            "url": self.url,
            "user": self.user_handle,
            "created": self.created_at,
            "country": self.country,
            "disciplines": self.disciplines,
            "position_type": self.position_type,
            "is_verified_job": self.is_verified_job,
        }
        if self.quoted_uri is not None:
            d["quoted_uri"] = self.quoted_uri
        if self.reply_parent_uri is not None:
            d["reply_parent_uri"] = self.reply_parent_uri
        return d


class DataSource(ABC):
    """Abstract base class for data sources."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the source name (e.g., 'bluesky', 'scholarshipdb')."""
        pass

    @abstractmethod
    def fetch_posts(
        self,
        since_timestamp: str | None = None,
        existing_uris: set[str] | None = None,
    ) -> tuple[list[Post], set[str]]:
        """Fetch posts from this source.

        Args:
            since_timestamp: Only include posts newer than this ISO timestamp
            existing_uris: Set of URIs already processed (for deduplication)

        Returns:
            Tuple of (list of Post objects, set of all seen URIs)
        """
        pass
