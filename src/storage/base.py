"""Abstract base class for storage backends."""

from abc import ABC, abstractmethod


class StorageBackend(ABC):
    """Abstract base class for storage backends."""

    @abstractmethod
    def save_posts(self, posts: list[dict]) -> int:
        """Save posts to storage.

        Args:
            posts: List of post dictionaries to save

        Returns:
            Number of posts saved
        """
        pass

    @abstractmethod
    def get_existing_uris(self) -> set[str]:
        """Get set of URIs already in storage.

        Returns:
            Set of post URIs that already exist
        """
        pass

    @abstractmethod
    def get_last_timestamp(self) -> str | None:
        """Get timestamp of most recent post in storage.

        Returns:
            ISO timestamp string or None if no posts exist
        """
        pass
