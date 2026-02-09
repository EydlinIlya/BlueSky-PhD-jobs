"""Multi-source sync state management.

This module manages sync state across multiple data sources, tracking
the last sync timestamp and seen URIs for each source independently.
"""

import json
from datetime import datetime
from pathlib import Path

from src.logger import setup_logger

logger = setup_logger()

DEFAULT_STATE_FILE = "last_sync.json"


class SyncStateManager:
    """Manages sync state for multiple data sources."""

    def __init__(self, state_file: str = DEFAULT_STATE_FILE):
        """Initialize sync state manager.

        Args:
            state_file: Path to the state file
        """
        self.state_file = state_file
        self._state: dict = {}
        self._load()

    def _load(self):
        """Load state from file, migrating old format if needed."""
        if not Path(self.state_file).exists():
            self._state = {"sources": {}, "version": 2}
            return

        try:
            with open(self.state_file, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Could not load sync state: {e}")
            self._state = {"sources": {}, "version": 2}
            return

        # Check if this is the old format (no version or version 1)
        if "version" not in data or data.get("version", 1) < 2:
            self._migrate_v1_to_v2(data)
        else:
            self._state = data

    def _migrate_v1_to_v2(self, old_data: dict):
        """Migrate from v1 (single-source) to v2 (multi-source) format.

        V1 format:
            {
                "last_timestamp": "2026-01-01T00:00:00Z",
                "seen_uris": ["uri1", "uri2"],
                "updated_at": "..."
            }

        V2 format:
            {
                "version": 2,
                "sources": {
                    "bluesky": {
                        "last_timestamp": "...",
                        "seen_uris": [...],
                        "updated_at": "..."
                    }
                }
            }
        """
        logger.info("Migrating sync state from v1 to v2 format")

        # Old data is assumed to be Bluesky data
        bluesky_state = {
            "last_timestamp": old_data.get("last_timestamp"),
            "seen_uris": old_data.get("seen_uris", []),
            "updated_at": old_data.get("updated_at"),
        }

        self._state = {
            "version": 2,
            "sources": {"bluesky": bluesky_state},
        }

        # Save migrated state
        self._save()

    def _save(self):
        """Save state to file."""
        self._state["updated_at"] = datetime.now().isoformat()
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(self._state, f, indent=2)
        logger.debug(f"Saved sync state to {self.state_file}")

    def get_source_state(self, source: str) -> dict:
        """Get sync state for a specific source.

        Args:
            source: Source name (e.g., 'bluesky', 'scholarshipdb')

        Returns:
            Dict with 'last_timestamp' and 'seen_uris' keys
        """
        source_state = self._state.get("sources", {}).get(source, {})
        return {
            "last_timestamp": source_state.get("last_timestamp"),
            "seen_uris": set(source_state.get("seen_uris", [])),
        }

    def update_source_state(
        self,
        source: str,
        last_timestamp: str | None,
        seen_uris: set[str],
    ):
        """Update sync state for a specific source.

        Args:
            source: Source name
            last_timestamp: ISO timestamp of the most recent post
            seen_uris: Set of all processed post URIs
        """
        if "sources" not in self._state:
            self._state["sources"] = {}

        self._state["sources"][source] = {
            "last_timestamp": last_timestamp,
            "seen_uris": list(seen_uris),
            "updated_at": datetime.now().isoformat(),
        }

        self._save()
        logger.debug(
            f"Updated {source} state: {len(seen_uris)} URIs, "
            f"last_timestamp={last_timestamp}"
        )

    def get_all_sources(self) -> list[str]:
        """Get list of all sources with saved state.

        Returns:
            List of source names
        """
        return list(self._state.get("sources", {}).keys())

    def clear_source(self, source: str):
        """Clear state for a specific source.

        Args:
            source: Source name to clear
        """
        if source in self._state.get("sources", {}):
            del self._state["sources"][source]
            self._save()
            logger.info(f"Cleared sync state for {source}")


# Legacy functions for backward compatibility with existing code
def load_sync_state(state_file: str = DEFAULT_STATE_FILE) -> dict:
    """Load sync state (legacy single-source format).

    This function provides backward compatibility with the old sync state
    format. It returns state for the 'bluesky' source.
    """
    manager = SyncStateManager(state_file)
    return manager.get_source_state("bluesky")


def save_sync_state(
    last_timestamp: str | None,
    seen_uris: list[str],
    state_file: str = DEFAULT_STATE_FILE,
):
    """Save sync state (legacy single-source format).

    This function provides backward compatibility with the old sync state
    format. It saves state for the 'bluesky' source.
    """
    manager = SyncStateManager(state_file)
    manager.update_source_state("bluesky", last_timestamp, set(seen_uris))
