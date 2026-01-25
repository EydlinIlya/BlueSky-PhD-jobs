"""Storage backends for PhD position data."""

from .base import StorageBackend
from .csv_storage import CSVStorage
from .supabase import SupabaseStorage

__all__ = ["StorageBackend", "CSVStorage", "SupabaseStorage"]
