"""Spotify client wrapper for spotDL integration."""

from typing import Any, Dict, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    from spotipy.exceptions import SpotifyException  # type: ignore
    from spotdl.utils.config import get_config  # type: ignore
    from spotdl.utils.spotify import SpotifyClient  # type: ignore
except ImportError as e:
    raise SystemExit(
        "spotdl>=4 must be installed. Run `uv sync` and then `uv run app.py`."
    ) from e


class MetadataError(RuntimeError):
    """Structured metadata lookup failure for the API layer."""

    def __init__(
        self, message: str, *, code: str = "metadata_error", retry_after: Optional[int] = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retry_after = retry_after


class SpotifyManager:
    """Manages Spotify client initialization and song metadata retrieval."""

    def __init__(self):
        self._ready = False

    @staticmethod
    def _build_no_retry_session() -> requests.Session:
        """Create a requests session that fails fast on HTTP 429 responses."""
        session = requests.Session()
        retry_kwargs = {
            "total": 0,
            "connect": 0,
            "read": 0,
            "redirect": 0,
            "status": 0,
            "backoff_factor": 0,
            "status_forcelist": (),
            "allowed_methods": frozenset(["GET", "POST", "PUT", "DELETE"]),
        }
        try:
            retry = Retry(other=0, respect_retry_after_header=False, **retry_kwargs)
        except TypeError:
            retry = Retry(**retry_kwargs)

        adapter = HTTPAdapter(max_retries=retry)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    @staticmethod
    def _parse_retry_after(headers: Optional[Dict[str, Any]]) -> Optional[int]:
        """Parse Spotify's Retry-After header into seconds when available."""
        if not headers:
            return None

        retry_after = headers.get("Retry-After")
        if retry_after is None:
            return None

        try:
            return int(float(str(retry_after).strip()))
        except (TypeError, ValueError):
            return None

    def ensure_client(self) -> None:
        """Initialize Spotify client if not already done."""
        if self._ready:
            return

        try:
            config = get_config()
            client_id = config.get("client_id", "")
            client_secret = config.get("client_secret", "")

            if not client_id or not client_secret:
                raise RuntimeError("SpotDL config file missing valid Spotify credentials")

            spotify = SpotifyClient.init(
                client_id=client_id,
                client_secret=client_secret,
                user_auth=config.get("user_auth", False),
                cache_path=config.get("cache_path"),
                no_cache=config.get("no_cache", False),
                max_retries=0,
                use_cache_file=config.get("use_cache_file", False),
            )
            # spotipy retries HTTP 429 responses by default and can sleep for
            # the server's entire Retry-After window. Replace the session so the
            # app can fail fast and show a useful message instead of appearing hung.
            spotify._session = self._build_no_retry_session()  # type: ignore[attr-defined]
            spotify.requests_timeout = 5  # type: ignore[attr-defined]
            self._ready = True

        except Exception as e:
            if "already been initialized" in str(e):
                self._ready = True
                return
            raise RuntimeError(f"Failed to initialize Spotify client: {e}") from e

    def get_metadata(self, link: str) -> Dict[str, Any]:
        """
        Get song metadata from Spotify/YouTube link.

        Args:
            link: Spotify or YouTube URL

        Returns:
            Dictionary containing title, artist, album, and cover URL
        """
        if "open.spotify.com/track" not in link:
            return {
                "title": "(unknown)",
                "artist": "",
                "album": "",
                "cover": "",
            }

        self.ensure_client()

        try:
            spotify = SpotifyClient()
            raw_track = spotify.track(link)  # type: ignore[arg-type]

            if raw_track is None:
                raise MetadataError(
                    "Couldn't fetch metadata for this track.",
                    code="metadata_unavailable",
                )

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
        except MetadataError:
            raise
        except SpotifyException as e:
            retry_after = self._parse_retry_after(getattr(e, "headers", None))
            if e.http_status == 429:
                message = "Spotify API rate limited this track lookup."
                if retry_after is not None:
                    message += f" Retry after about {retry_after} seconds."
                message += " If this keeps happening, update your spotDL Spotify credentials."
                raise MetadataError(
                    message,
                    code="rate_limited",
                    retry_after=retry_after,
                ) from e

            raise MetadataError(
                f"Spotify metadata request failed: {e.msg}",
                code="spotify_error",
            ) from e
        except Exception as e:
            print(f"Metadata error for {link}: {e}")
            raise MetadataError(
                "Failed to load track metadata.",
                code="metadata_error",
            ) from e


# Global instance
spotify_manager = SpotifyManager()
