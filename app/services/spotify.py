"""Compatibility shim for the rewritten metadata backend."""

from app.backend.metadata import MetadataError, MetadataService

__all__ = ["MetadataError", "MetadataService"]
