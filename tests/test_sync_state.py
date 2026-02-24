"""Tests for sync state manager."""

import json
import pytest
from pathlib import Path

from src.sync_state import SyncStateManager


class TestSyncStateManager:
    """Tests for SyncStateManager class."""

    @pytest.fixture
    def temp_state_file(self, tmp_path):
        """Create a temporary state file path."""
        return str(tmp_path / "test_sync_state.json")

    def test_creates_empty_state(self, temp_state_file):
        """Test that manager creates empty state when file doesn't exist."""
        manager = SyncStateManager(temp_state_file)
        state = manager.get_source_state("bluesky")
        assert state["last_timestamp"] is None
        assert state["seen_uris"] == set()

    def test_update_source_state(self, temp_state_file):
        """Test updating source state."""
        manager = SyncStateManager(temp_state_file)
        manager.update_source_state(
            "bluesky",
            "2026-01-15T00:00:00Z",
            {"uri1", "uri2"},
        )

        state = manager.get_source_state("bluesky")
        assert state["last_timestamp"] == "2026-01-15T00:00:00Z"
        assert state["seen_uris"] == {"uri1", "uri2"}

    def test_multiple_sources(self, temp_state_file):
        """Test managing multiple sources."""
        manager = SyncStateManager(temp_state_file)

        manager.update_source_state("bluesky", "2026-01-01T00:00:00Z", {"uri1"})
        manager.update_source_state("scholarshipdb", "2026-02-01T00:00:00Z", {"uri2"})

        bluesky_state = manager.get_source_state("bluesky")
        scholarshipdb_state = manager.get_source_state("scholarshipdb")

        assert bluesky_state["last_timestamp"] == "2026-01-01T00:00:00Z"
        assert scholarshipdb_state["last_timestamp"] == "2026-02-01T00:00:00Z"

    def test_get_all_sources(self, temp_state_file):
        """Test getting list of all sources."""
        manager = SyncStateManager(temp_state_file)
        manager.update_source_state("bluesky", "2026-01-01T00:00:00Z", set())
        manager.update_source_state("scholarshipdb", "2026-02-01T00:00:00Z", set())

        sources = manager.get_all_sources()
        assert "bluesky" in sources
        assert "scholarshipdb" in sources

    def test_clear_source(self, temp_state_file):
        """Test clearing a source's state."""
        manager = SyncStateManager(temp_state_file)
        manager.update_source_state("bluesky", "2026-01-01T00:00:00Z", {"uri1"})
        manager.clear_source("bluesky")

        state = manager.get_source_state("bluesky")
        assert state["last_timestamp"] is None
        assert state["seen_uris"] == set()

    def test_persists_to_file(self, temp_state_file):
        """Test that state persists to file."""
        manager1 = SyncStateManager(temp_state_file)
        manager1.update_source_state("bluesky", "2026-01-15T00:00:00Z", {"uri1"})

        # Create new manager with same file
        manager2 = SyncStateManager(temp_state_file)
        state = manager2.get_source_state("bluesky")
        assert state["last_timestamp"] == "2026-01-15T00:00:00Z"
        assert "uri1" in state["seen_uris"]
