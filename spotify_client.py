"""Compatibility facade for the refactored Spotify services."""

from app.services.spotify import (
    DownloadInputPayload,
    DownloadInputResolver,
    ExternalMetadataService,
    MetadataError,
    MetadataService,
    SpotifyConfigLoader,
    SpotifyManager,
    SpotifyPageMetadataService,
    spotify_manager,
)

__all__ = [
    "DownloadInputPayload",
    "DownloadInputResolver",
    "ExternalMetadataService",
    "MetadataError",
    "MetadataService",
    "SpotifyConfigLoader",
    "SpotifyManager",
    "SpotifyPageMetadataService",
    "spotify_manager",
]
