"""Configuration settings for spotDL GUI application."""

import os
import pathlib
from typing import Any, Optional

import project_meta
from app.settings import SettingsStore

# Application settings
APP_NAME = project_meta.APP_NAME
APP_VERSION = project_meta.APP_VERSION
BUNDLE_ID = project_meta.BUNDLE_ID
APP_CATEGORY = project_meta.APP_CATEGORY
APP_COPYRIGHT = project_meta.APP_COPYRIGHT
VERSION = APP_VERSION
PORT = int(os.getenv("SPOTDL_PORT", "5001"))
WINDOW_WIDTH = 920
WINDOW_HEIGHT = 660

# Download settings
DEFAULT_DOWNLOAD_DIR = pathlib.Path.home() / "Downloads" / "spotdl"
SETTINGS_DIR = pathlib.Path.home() / ".spotdl-web-downloader"
SETTINGS_FILE = SETTINGS_DIR / "settings.json"
DOWNLOAD_DIR = DEFAULT_DOWNLOAD_DIR
settings_store = SettingsStore(
    default_download_dir=DEFAULT_DOWNLOAD_DIR,
    settings_dir=SETTINGS_DIR,
    settings_file=SETTINGS_FILE,
)

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

FORMAT_OPTIONS = ["mp3", "flac", "m4a", "opus", "ogg", "wav"]

OUTPUT_TEMPLATES = {
    "artist_title": "{artists} - {title}.{output-ext}",
    "title_artist": "{title} - {artists}.{output-ext}",
    "album_track": "{album}/{track-number}. {title}.{output-ext}",
    "artist_album_track": "{artist}/{album}/{track-number}. {title}.{output-ext}",
}


def _normalize_download_directory(value: Any) -> Optional[pathlib.Path]:
    """Convert a persisted path value into a clean absolute directory path."""
    return settings_store.normalize_download_directory(value)


def _settings_payload(download_dir: Optional[pathlib.Path]) -> dict[str, Any]:
    """Build the app settings payload for persistence and API responses."""
    return settings_store.build_payload(download_dir)


def load_app_settings() -> dict[str, Any]:
    """Load persisted app settings from disk."""
    return settings_store.load()


def save_app_settings(*, download_dir: Optional[pathlib.Path]) -> dict[str, Any]:
    """Persist app settings to disk and return the normalized payload."""
    return settings_store.save(download_dir=download_dir)


def get_download_dir() -> Optional[pathlib.Path]:
    """Return the user-selected default download directory, if configured."""
    return settings_store.get_download_dir()


def set_download_dir(path_value: str | pathlib.Path) -> pathlib.Path:
    """Persist and return a user-selected download directory."""
    return settings_store.set_download_dir(path_value)
