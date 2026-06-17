"""Shared Spotify credential/bootstrap helpers for isolated worker processes."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from spotdl.utils.config import get_config, get_config_file
from spotdl.utils.spotify import SpotifyClient

_LOCAL_ENV_LOADED = False


class SpotifyConfigurationError(RuntimeError):
    """Raised when Spotify credentials are missing or unusable."""


def _load_local_env_file() -> None:
    """Load repo-local environment variables from `.env` once per process."""
    global _LOCAL_ENV_LOADED
    if _LOCAL_ENV_LOADED:
        return

    _LOCAL_ENV_LOADED = True
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]

        if key and key not in os.environ:
            os.environ[key] = value


def _get_env_override(*names: str) -> Optional[str]:
    _load_local_env_file()
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return None


def load_spotify_settings() -> tuple[dict[str, Any], str]:
    """Resolve Spotify credentials from env vars or the spotDL config file."""
    config = get_config()
    config_path = str(get_config_file())

    settings = {
        "client_id": _get_env_override("SPOTDL_CLIENT_ID", "SPOTIPY_CLIENT_ID")
        or config.get("client_id", ""),
        "client_secret": _get_env_override(
            "SPOTDL_CLIENT_SECRET",
            "SPOTIPY_CLIENT_SECRET",
        )
        or config.get("client_secret", ""),
        "user_auth": config.get("user_auth", False),
        "cache_path": config.get("cache_path"),
        "no_cache": config.get("no_cache", False),
        "use_cache_file": config.get("use_cache_file", False),
    }
    return settings, config_path


def configure_spotify_client() -> str:
    """Initialize the spotDL Spotify client or raise a clear configuration error."""
    settings, config_path = load_spotify_settings()
    if not settings["client_id"] or not settings["client_secret"]:
        raise SpotifyConfigurationError(
            "Missing Spotify credentials. Set SPOTDL_CLIENT_ID and "
            f"SPOTDL_CLIENT_SECRET, or update {config_path}."
        )

    try:
        SpotifyClient.init(
            client_id=settings["client_id"],
            client_secret=settings["client_secret"],
            user_auth=settings["user_auth"],
            cache_path=settings["cache_path"],
            no_cache=settings["no_cache"],
            max_retries=0,
            use_cache_file=settings["use_cache_file"],
        )
    except Exception as exc:
        if "already been initialized" not in str(exc):
            raise SpotifyConfigurationError(str(exc)) from exc

    return config_path

