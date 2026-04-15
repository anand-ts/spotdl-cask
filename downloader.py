"""Compatibility facade for the refactored download services."""

import subprocess
import sys

from app.services.downloads import (
    ALLOWED_AUDIO_PROVIDERS,
    AUDIO_PROVIDER_ENV_VARS,
    DEBUG_OUTPUT,
    DEFAULT_AUDIO_PROVIDERS,
    MUSIC_EXTENSIONS,
    PRESTART_CANCEL_WINDOW_SECONDS,
    SAFE_FALLBACK_OUTPUT_TEMPLATE,
    TITLE_ONLY_SEARCH_QUERY,
    DownloadFileService,
    DownloadManager,
    DownloadService,
    ErrorMessageFormatter,
    ProgressParser,
    SpotdlCommandBuilder,
    download_manager,
)

__all__ = [
    "ALLOWED_AUDIO_PROVIDERS",
    "AUDIO_PROVIDER_ENV_VARS",
    "DEFAULT_AUDIO_PROVIDERS",
    "DEBUG_OUTPUT",
    "DownloadFileService",
    "DownloadManager",
    "DownloadService",
    "ErrorMessageFormatter",
    "MUSIC_EXTENSIONS",
    "PRESTART_CANCEL_WINDOW_SECONDS",
    "ProgressParser",
    "SAFE_FALLBACK_OUTPUT_TEMPLATE",
    "SpotdlCommandBuilder",
    "TITLE_ONLY_SEARCH_QUERY",
    "download_manager",
    "subprocess",
    "sys",
]
