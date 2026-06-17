"""Input normalization and supported-link classification."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

SPOTIFY_INTL_PATTERN = re.compile(r"/intl-\w+/")


class UnsupportedInputError(ValueError):
    """Raised when an input cannot be handled by the lean v1 backend."""


@dataclass(frozen=True)
class LinkInfo:
    """Normalized description of a user-provided link."""

    original: str
    normalized: str
    kind: str


def normalize_link(link: str) -> str:
    """Strip whitespace and normalize link variants we intentionally support."""
    cleaned = str(link or "").strip()
    if not cleaned:
        return ""

    cleaned = SPOTIFY_INTL_PATTERN.sub("/", cleaned)
    parsed = urlsplit(cleaned)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))


def classify_link(link: str) -> LinkInfo:
    """Classify the link into a small set of backend-relevant kinds."""
    normalized = normalize_link(link)
    lower = normalized.lower()

    if not lower.startswith(("http://", "https://")):
        return LinkInfo(original=link, normalized=normalized, kind="unsupported")

    if "open.spotify.com/track/" in lower:
        parsed = urlsplit(normalized)
        spotify_track = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
        return LinkInfo(original=link, normalized=spotify_track, kind="spotify_track")

    if "open.spotify.com/" in lower:
        return LinkInfo(original=link, normalized=normalized, kind="spotify_unsupported")

    if "youtube.com/playlist" in lower or "music.youtube.com/playlist" in lower:
        return LinkInfo(original=link, normalized=normalized, kind="external_unsupported")

    if "soundcloud.com/" in lower and "/sets/" in lower:
        return LinkInfo(original=link, normalized=normalized, kind="external_unsupported")

    if "bandcamp.com/album/" in lower:
        return LinkInfo(original=link, normalized=normalized, kind="external_unsupported")

    return LinkInfo(original=link, normalized=normalized, kind="external_media")


def ensure_supported_single_track(link: str) -> LinkInfo:
    """Validate that the input fits the v1 single-row download model."""
    info = classify_link(link)
    if info.kind == "spotify_track":
        return info
    if info.kind == "spotify_unsupported":
        raise UnsupportedInputError(
            "Spotify playlists, albums, and artists are not supported in this version."
        )
    if info.kind == "external_unsupported":
        raise UnsupportedInputError(
            "Playlist and collection links are not supported in this version."
        )
    if info.kind == "external_media":
        return info
    raise UnsupportedInputError("Only direct Spotify track links and direct media links are supported.")

