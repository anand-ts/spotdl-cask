"""Compatibility exports for older imports."""

from app.backend.metadata import MetadataError, MetadataService
from app.services.downloads import DownloadService

__all__ = ["DownloadService", "MetadataError", "MetadataService"]
