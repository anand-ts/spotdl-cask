"""Configuration settings for spotDL GUI application."""

import pathlib

# Application settings
APP_NAME = "spotDL Web Downloader"
VERSION = "rev-5"
PORT = 5001
WINDOW_WIDTH = 920
WINDOW_HEIGHT = 660

# Download settings
DOWNLOAD_DIR = pathlib.Path.home() / "Downloads" / "spotdl"

# Default settings for downloads
DEFAULT_SETTINGS = {
    "quality": "best",
    "format": "mp3", 
    "output": "{artists} - {title}.{output-ext}",
    "playlistNumbering": False,
    "skipExplicit": False,
    "generateLrc": False
}

# SpotDL command options mapping
QUALITY_OPTIONS = {
    "best": None,  # Don't add --bitrate flag for best (highest available)
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
