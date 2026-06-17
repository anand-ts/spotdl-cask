"""Persistent settings and request-time download option normalization."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from config import DEFAULT_DOWNLOAD_DIR, QUALITY_OPTIONS, SETTINGS_DIR, SETTINGS_FILE

SUPPORTED_FORMATS = {"mp3", "flac", "opus", "ogg", "m4a", "wav"}
DEFAULT_QUALITY = "best"
DEFAULT_FORMAT = "mp3"


@dataclass(frozen=True)
class DownloadRequest:
    """Normalized download options used by the supervisor and workers."""

    download_directory: Path
    quality: str
    format: str
    bitrate: str
    source_url: Optional[str] = None


class SettingsStore:
    """Persist and normalize app settings on disk."""

    def __init__(
        self,
        *,
        default_download_dir: Path,
        settings_dir: Path,
        settings_file: Path,
    ) -> None:
        self.default_download_dir = default_download_dir.expanduser().resolve()
        self.settings_dir = settings_dir.expanduser().resolve()
        self.settings_file = settings_file.expanduser().resolve()

    def normalize_download_directory(self, value: Any) -> Optional[Path]:
        """Convert a persisted path value into a clean absolute directory path."""
        if not isinstance(value, str) or not value.strip():
            return None
        return Path(value).expanduser().resolve()

    def build_payload(self, download_dir: Optional[Path]) -> dict[str, Any]:
        """Build the payload used for both persistence and the HTTP API."""
        return {
            "downloadDirectory": str(download_dir) if download_dir else "",
            "hasDownloadDirectory": download_dir is not None,
            "defaultDownloadDirectory": str(self.default_download_dir),
        }

    def load(self) -> dict[str, Any]:
        """Load persisted settings from disk."""
        if not self.settings_file.exists():
            return self.build_payload(None)

        try:
            data = json.loads(self.settings_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return self.build_payload(None)

        return self.build_payload(
            self.normalize_download_directory(data.get("downloadDirectory"))
        )

    def save(self, *, download_dir: Optional[Path]) -> dict[str, Any]:
        """Persist the selected download directory."""
        self.settings_dir.mkdir(parents=True, exist_ok=True)
        payload = self.build_payload(download_dir)
        self.settings_file.write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
        )
        return payload

    def get_download_dir(self) -> Optional[Path]:
        """Return the configured download directory, if any."""
        return self.normalize_download_directory(self.load().get("downloadDirectory"))

    def set_download_dir(self, path_value: str | Path) -> Path:
        """Persist and return a user-selected download directory."""
        download_dir = Path(path_value).expanduser().resolve()
        download_dir.mkdir(parents=True, exist_ok=True)
        self.save(download_dir=download_dir)
        return download_dir


def normalize_quality(value: Any) -> str:
    """Normalize a UI quality selection to one of the supported keys."""
    quality = str(value or DEFAULT_QUALITY).strip().lower()
    return quality if quality in QUALITY_OPTIONS else DEFAULT_QUALITY


def normalize_format(value: Any) -> str:
    """Normalize a UI format selection to a supported spotDL format."""
    format_name = str(value or DEFAULT_FORMAT).strip().lower()
    return format_name if format_name in SUPPORTED_FORMATS else DEFAULT_FORMAT


def build_download_request(
    payload: dict[str, Any],
    *,
    download_dir: Path,
) -> DownloadRequest:
    """Normalize request-time options while intentionally ignoring advanced knobs."""
    quality = normalize_quality(payload.get("quality"))
    format_name = normalize_format(payload.get("format"))
    source_url = str(payload.get("sourceUrl") or "").strip() or None
    return DownloadRequest(
        download_directory=download_dir.expanduser().resolve(),
        quality=quality,
        format=format_name,
        bitrate=QUALITY_OPTIONS[quality],
        source_url=source_url,
    )


def create_default_settings_store() -> SettingsStore:
    """Build the app's default settings store."""
    return SettingsStore(
        default_download_dir=DEFAULT_DOWNLOAD_DIR,
        settings_dir=SETTINGS_DIR,
        settings_file=SETTINGS_FILE,
    )


default_settings_store = create_default_settings_store()
