"""Compatibility shim for the rewritten download backend."""

from app.backend.jobs import DownloadSupervisor
from app.backend.metadata import MetadataService


class DownloadService(DownloadSupervisor):
    """Backward-compatible alias with the old zero-argument constructor shape."""

    def __init__(self, metadata_service: MetadataService | None = None, **kwargs) -> None:
        super().__init__(metadata_service or MetadataService(), **kwargs)
