"""Configuration constants for the spotDL GUI application."""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "spotDL Web Downloader"
PORT = int(os.getenv("SPOTDL_PORT", "5001"))
WINDOW_WIDTH = 920
WINDOW_HEIGHT = 660

DEFAULT_DOWNLOAD_DIR = Path.home() / "Downloads" / "spotdl"
SETTINGS_DIR = Path.home() / ".spotdl-web-downloader"
SETTINGS_FILE = SETTINGS_DIR / "settings.json"

QUALITY_OPTIONS = {
    "best": "auto",
    "default": "192k",
    "efficient": "128k",
}
