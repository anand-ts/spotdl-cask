"""Shared protocol types for download jobs and metadata responses."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

DEFAULT_AUDIO_PROVIDERS = ("youtube-music", "piped", "youtube")
DEFAULT_SEARCH_QUERY = "{artist} - {title}"
OUTPUT_TEMPLATE = "{artists} - {title}.{output-ext}"


@dataclass(frozen=True)
class DownloadJobSpec:
    """Normalized payload sent to a per-job worker subprocess."""

    job_id: str
    link: str
    download_directory: str
    format: str
    bitrate: str
    song_payload: Optional[dict[str, Any]]
    source_url: Optional[str] = None
    audio_providers: tuple[str, ...] = DEFAULT_AUDIO_PROVIDERS
    search_query: str = DEFAULT_SEARCH_QUERY

    def to_payload(self) -> dict[str, Any]:
        """Return a JSON-serializable worker payload."""
        return {
            "job_id": self.job_id,
            "link": self.link,
            "download_directory": self.download_directory,
            "format": self.format,
            "bitrate": self.bitrate,
            "song_payload": self.song_payload,
            "source_url": self.source_url,
            "audio_providers": list(self.audio_providers),
            "search_query": self.search_query,
        }
