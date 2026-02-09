"""Tests for sync state manager."""

import json
import pytest
from pathlib import Path
from tempfile import NamedTemporaryFile

from src.sync_state import SyncStateManager, load_sync_state, save_sync_state


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


class TestV1ToV2Migration:
    """Tests for migrating v1 format to v2."""

    @pytest.fixture
    def v1_state_file(self, tmp_path):
        """Create a v1 format state file."""
        state_file = tmp_path / "v1_state.json"
        v1_data = {
            "last_timestamp": "2026-01-01T00:00:00Z",
            "seen_uris": ["uri1", "uri2", "uri3"],
            "updated_at": "2026-01-02T00:00:00Z",
        }
        state_file.write_text(json.dumps(v1_data))
        return str(state_file)

    def test_migrates_v1_to_v2(self, v1_state_file):
        """Test that v1 format is migrated to v2."""
        manager = SyncStateManager(v1_state_file)

        # Should have migrated to bluesky source
        state = manager.get_source_state("bluesky")
        assert state["last_timestamp"] == "2026-01-01T00:00:00Z"
        assert state["seen_uris"] == {"uri1", "uri2", "uri3"}

    def test_migration_saves_v2_format(self, v1_state_file):
        """Test that migration saves v2 format."""
        manager = SyncStateManager(v1_state_file)

        # Load file and check format
        with open(v1_state_file) as f:
            data = json.load(f)

        assert data["version"] == 2
        assert "sources" in data
        assert "bluesky" in data["sources"]


class TestLegacyFunctions:
    """Tests for legacy compatibility functions."""

    @pytest.fixture
    def temp_state_file(self, tmp_path):
        """Create a temporary state file path."""
        return str(tmp_path / "legacy_state.json")

    def test_load_sync_state_empty(self, temp_state_file):
        """Test load_sync_state with no file."""
        # Patch the default state file
        import src.sync_state as sync_module
        original = sync_module.DEFAULT_STATE_FILE
        sync_module.DEFAULT_STATE_FILE = temp_state_file

        try:
            state = load_sync_state(temp_state_file)
            assert state["last_timestamp"] is None
            assert state["seen_uris"] == set()
        finally:
            sync_module.DEFAULT_STATE_FILE = original

    def test_save_and_load_sync_state(self, temp_state_file):
        """Test save_sync_state and load_sync_state work together."""
        save_sync_state("2026-01-15T00:00:00Z", ["uri1", "uri2"], temp_state_file)
        state = load_sync_state(temp_state_file)

        assert state["last_timestamp"] == "2026-01-15T00:00:00Z"
        assert "uri1" in state["seen_uris"]
        assert "uri2" in state["seen_uris"]

    def test_legacy_functions_use_bluesky_source(self, temp_state_file):
        """Test that legacy functions use 'bluesky' source."""
        save_sync_state("2026-01-15T00:00:00Z", ["uri1"], temp_state_file)

        # Load directly to check source
        manager = SyncStateManager(temp_state_file)
        assert "bluesky" in manager.get_all_sources()
