"""Settings persistence primitives for the desktop app."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional


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
        """Build the settings payload used for persistence and API responses."""
        return {
            "downloadDirectory": str(download_dir) if download_dir else "",
            "hasDownloadDirectory": download_dir is not None,
            "defaultDownloadDirectory": str(self.default_download_dir),
        }

    def load(self) -> dict[str, Any]:
        """Load persisted app settings from disk."""
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
        """Persist app settings to disk and return the normalized payload."""
        self.settings_dir.mkdir(parents=True, exist_ok=True)
        payload = self.build_payload(download_dir)
        self.settings_file.write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
        )
        return payload

    def get_download_dir(self) -> Optional[Path]:
        """Return the configured default download directory, if any."""
        return self.normalize_download_directory(self.load().get("downloadDirectory"))

    def set_download_dir(self, path_value: str | Path) -> Path:
        """Persist and return a user-selected download directory."""
        download_dir = Path(path_value).expanduser().resolve()
        download_dir.mkdir(parents=True, exist_ok=True)
        self.save(download_dir=download_dir)
        return download_dir
