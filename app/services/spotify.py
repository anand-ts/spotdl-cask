"""Metadata resolution for Spotify tracks and external links."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Optional, cast
from urllib.parse import urlsplit, urlunsplit

try:
    from spotdl.utils.config import get_config, get_config_file
    from spotdl.utils.spotify import SpotifyClient
    from spotipy.exceptions import SpotifyException
except ImportError as exc:
    raise SystemExit(
        "spotdl>=4 must be installed. Run `./setup`, then `./dev` or `./run`."
    ) from exc


LOGGER = logging.getLogger(__name__)
_LOCAL_ENV_LOADED = False


def _unknown_metadata() -> dict[str, str]:
    return {
        "title": "(unknown)",
        "artist": "",
        "album": "",
        "cover": "",
    }


def _load_local_env_file() -> None:
    """Load repo-local environment variables from `.env` once."""
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


class MetadataError(RuntimeError):
    """Structured metadata lookup failure for the API layer."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "metadata_error",
        retry_after: Optional[int] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retry_after = retry_after


class MetadataService:
    """Resolve UI metadata for Spotify and external links."""

    def __init__(self) -> None:
        self._ready = False
        self._config_path = str(get_config_file())

    @staticmethod
    def _is_spotify_track_url(link: str) -> bool:
        return "open.spotify.com/track" in link

    @staticmethod
    def _normalize_spotify_track_url(link: str) -> str:
        parsed = urlsplit(link.strip())
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))

    @staticmethod
    def _clean_text(value: Any) -> str:
        return "" if value is None else str(value).strip()

    @classmethod
    def _coalesce_text(cls, *values: Any) -> str:
        for value in values:
            cleaned = cls._clean_text(value)
            if cleaned:
                return cleaned
        return ""

    @classmethod
    def _join_artists(cls, value: Any) -> str:
        if isinstance(value, str):
            return cls._clean_text(value)
        if not isinstance(value, (list, tuple)):
            return ""

        artists = []
        for artist in value:
            if isinstance(artist, dict):
                artist = artist.get("name")
            cleaned = cls._clean_text(artist)
            if cleaned:
                artists.append(cleaned)
        return ", ".join(artists)

    @staticmethod
    def _parse_retry_after(headers: Optional[dict[str, Any]]) -> Optional[int]:
        if not headers:
            return None

        retry_after = headers.get("Retry-After")
        if retry_after is None:
            return None

        try:
            return int(float(str(retry_after).strip()))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _format_retry_after(retry_after: Optional[int]) -> str:
        if retry_after is None:
            return ""

        message = f" Retry after about {retry_after} seconds"
        if retry_after >= 3600 and retry_after % 3600 == 0:
            message += f" ({retry_after // 3600} hours)"
        elif retry_after >= 60 and retry_after % 60 == 0:
            message += f" ({retry_after // 60} minutes)"
        return message + "."

    @staticmethod
    def _get_env_override(*names: str) -> Optional[str]:
        _load_local_env_file()
        for name in names:
            value = os.getenv(name, "").strip()
            if value:
                return value
        return None

    def _load_spotify_settings(self) -> dict[str, Any]:
        config = get_config()
        self._config_path = str(get_config_file())

        return {
            "client_id": self._get_env_override(
                "SPOTDL_CLIENT_ID",
                "SPOTIPY_CLIENT_ID",
            )
            or config.get("client_id", ""),
            "client_secret": self._get_env_override(
                "SPOTDL_CLIENT_SECRET",
                "SPOTIPY_CLIENT_SECRET",
            )
            or config.get("client_secret", ""),
            "user_auth": config.get("user_auth", False),
            "cache_path": config.get("cache_path"),
            "no_cache": config.get("no_cache", False),
            "use_cache_file": config.get("use_cache_file", False),
        }

    def _ensure_client(self) -> None:
        if self._ready:
            return

        settings = self._load_spotify_settings()
        if not settings["client_id"] or not settings["client_secret"]:
            raise MetadataError(
                "Missing Spotify credentials. Set SPOTDL_CLIENT_ID and "
                f"SPOTDL_CLIENT_SECRET, or update {self._config_path}.",
                code="missing_spotify_credentials",
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
            self._ready = True
        except Exception as exc:
            if "already been initialized" in str(exc):
                self._ready = True
                return
            raise

    @classmethod
    def _external_info_to_metadata(cls, info: dict[str, Any]) -> dict[str, str]:
        thumbnails = info.get("thumbnails")
        cover = cls._clean_text(info.get("thumbnail"))
        if not cover and isinstance(thumbnails, list):
            candidates = [
                thumbnail
                for thumbnail in thumbnails
                if isinstance(thumbnail, dict) and cls._clean_text(thumbnail.get("url"))
            ]
            if candidates:
                best = max(
                    candidates,
                    key=lambda thumbnail: (
                        (thumbnail.get("width") or 0)
                        * (thumbnail.get("height") or 0)
                    ),
                )
                cover = cls._clean_text(best.get("url"))

        return {
            "title": cls._coalesce_text(
                info.get("track"),
                info.get("title"),
                info.get("fulltitle"),
            )
            or "(unknown)",
            "artist": cls._join_artists(info.get("artists"))
            or cls._coalesce_text(
                info.get("artist"),
                info.get("creator"),
                info.get("uploader"),
                info.get("channel"),
                info.get("album_artist"),
            ),
            "album": cls._coalesce_text(
                info.get("album"),
                info.get("album_title"),
                info.get("playlist_title"),
                info.get("playlist"),
                info.get("collection"),
            ),
            "cover": cover,
        }

    def _get_external_metadata(self, link: str) -> Optional[dict[str, str]]:
        try:
            import yt_dlp
        except ImportError:
            LOGGER.warning(
                "yt-dlp is unavailable; external metadata lookup is disabled."
            )
            return None

        try:
            with yt_dlp.YoutubeDL(
                {
                    "quiet": True,
                    "no_warnings": True,
                    "noplaylist": True,
                    "extract_flat": False,
                    "skip_download": True,
                }
            ) as downloader:
                info = downloader.extract_info(link, download=False)
        except Exception:
            LOGGER.exception("External metadata lookup failed for %s", link)
            return None

        if isinstance(info, dict) and info.get("entries"):
            entries = info.get("entries") or []
            info = next((entry for entry in entries if isinstance(entry, dict)), info)

        if not isinstance(info, dict):
            return None

        metadata = self._external_info_to_metadata(info)
        if any(value for value in metadata.values() if value and value != "(unknown)"):
            return metadata
        return None

    @staticmethod
    def _spotify_track_to_metadata(raw_track: dict[str, Any]) -> dict[str, str]:
        album = raw_track.get("album") or {}
        images = album.get("images") or []
        cover = ""
        if images:
            cover = max(
                images,
                key=lambda image: image.get("width", 0) * image.get("height", 0),
            ).get("url", "")

        artists = [
            artist.get("name", "")
            for artist in raw_track.get("artists", [])
            if artist.get("name")
        ]

        return {
            "title": raw_track.get("name") or "(unknown)",
            "artist": ", ".join(artists),
            "album": album.get("name") or "",
            "cover": cover,
        }

    def get_metadata(self, link: str) -> dict[str, str]:
        """Return normalized UI metadata for the provided link."""
        if not self._is_spotify_track_url(link):
            return self._get_external_metadata(link) or _unknown_metadata()

        normalized_link = self._normalize_spotify_track_url(link)
        try:
            self._ensure_client()
            spotify = cast(Any, SpotifyClient())
            raw_track = spotify.track(normalized_link)  # type: ignore[arg-type]
            if raw_track is None:
                raise MetadataError(
                    "Couldn't fetch metadata for this track.",
                    code="metadata_unavailable",
                )
            return self._spotify_track_to_metadata(raw_track)
        except MetadataError:
            raise
        except SpotifyException as exc:
            retry_after = self._parse_retry_after(getattr(exc, "headers", None))
            if exc.http_status == 429:
                message = (
                    "Spotify rejected the credentials this app is using for track "
                    "lookups."
                    + self._format_retry_after(retry_after)
                    + f" Update the Spotify credentials in {self._config_path}, or "
                    "override them with SPOTDL_CLIENT_ID and SPOTDL_CLIENT_SECRET."
                )
                raise MetadataError(
                    message,
                    code="rate_limited",
                    retry_after=retry_after,
                ) from exc

            raise MetadataError(
                f"Spotify metadata request failed: {exc.msg}",
                code="spotify_error",
            ) from exc
        except Exception as exc:
            LOGGER.exception("Metadata error for %s", link)
            raise MetadataError(
                "Failed to load track metadata.",
                code="metadata_error",
            ) from exc
