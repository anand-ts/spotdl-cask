"""Configuration settings for spotDL GUI application."""

import json
import pathlib
from typing import Any, Optional

# Application settings
APP_NAME = "spotDL Web Downloader"
VERSION = "rev-5"
PORT = 5001
WINDOW_WIDTH = 920
WINDOW_HEIGHT = 660

# Download settings
DEFAULT_DOWNLOAD_DIR = pathlib.Path.home() / "Downloads" / "spotdl"
SETTINGS_DIR = pathlib.Path.home() / ".spotdl-web-downloader"
SETTINGS_FILE = SETTINGS_DIR / "settings.json"
DOWNLOAD_DIR = DEFAULT_DOWNLOAD_DIR

# Default settings for downloads
DEFAULT_SETTINGS = {
    "quality": "best",
    "format": "mp3", 
    "output": "{artists} - {title}.{output-ext}",
    "playlistNumbering": False,
    "skipExplicit": False,
    "generateLrc": False,
    "downloadDirectory": "",
}

# SpotDL command options mapping
QUALITY_OPTIONS = {
    # spotdl defaults to 128k when --bitrate is omitted, so explicitly use
    # "auto" to preserve the source bitrate for the best-quality option.
    "best": "auto",
    "default": "192k",  # Good balance of quality and file size
    "efficient": "128k",  # Smaller file size, decent quality
}

FORMAT_OPTIONS = [
    "mp3", "flac", "m4a", "opus", "ogg", "wav"
]

OUTPUT_TEMPLATES = {
    "artist_title": "{artists} - {title}.{output-ext}",
    "title_artist": "{title} - {artists}.{output-ext}",
    "album_track": "{album}/{track-number}. {title}.{output-ext}",
    "artist_album_track": "{artist}/{album}/{track-number}. {title}.{output-ext}"
}


def _normalize_download_directory(value: Any) -> Optional[pathlib.Path]:
    """Convert a persisted path value into a clean absolute directory path."""
    if not isinstance(value, str) or not value.strip():
        return None

    return pathlib.Path(value).expanduser().resolve()


def _settings_payload(download_dir: Optional[pathlib.Path]) -> dict[str, Any]:
    """Build the app settings payload for persistence and API responses."""
    return {
        "downloadDirectory": str(download_dir) if download_dir else "",
        "hasDownloadDirectory": download_dir is not None,
        "defaultDownloadDirectory": str(DEFAULT_DOWNLOAD_DIR),
    }


def load_app_settings() -> dict[str, Any]:
    """Load persisted app settings from disk."""
    if not SETTINGS_FILE.exists():
        return _settings_payload(None)

    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _settings_payload(None)

    return _settings_payload(_normalize_download_directory(data.get("downloadDirectory")))


def save_app_settings(*, download_dir: Optional[pathlib.Path]) -> dict[str, Any]:
    """Persist app settings to disk and return the normalized payload."""
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    payload = _settings_payload(download_dir)
    SETTINGS_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def get_download_dir() -> Optional[pathlib.Path]:
    """Return the user-selected default download directory, if configured."""
    settings = load_app_settings()
    return _normalize_download_directory(settings.get("downloadDirectory"))


def set_download_dir(path_value: str | pathlib.Path) -> pathlib.Path:
    """Persist and return a user-selected download directory."""
    download_dir = pathlib.Path(path_value).expanduser().resolve()
    download_dir.mkdir(parents=True, exist_ok=True)
    save_app_settings(download_dir=download_dir)
    return download_dir
