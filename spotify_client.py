"""Spotify client wrapper for spotDL integration."""

import html
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional, TypedDict, cast
from urllib.parse import urlsplit, urlunsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    from spotipy.exceptions import SpotifyException
    from spotdl.utils.config import get_config, get_config_file
    from spotdl.utils.spotify import SpotifyClient
except ImportError as e:
    raise SystemExit(
        "spotdl>=4 must be installed. Run `uv sync` and then `uv run app.py`."
    ) from e


_LOCAL_ENV_LOADED = False


class DownloadInputPayload(TypedDict):
    """Structured handoff from metadata resolution into the downloader."""

    input: str
    temporary_input_file: Optional[str]
    fallback_missing_artist: bool


def _load_local_env_file() -> None:
    """Load repo-local environment variables from `.env` once."""
    global _LOCAL_ENV_LOADED
    if _LOCAL_ENV_LOADED:
        return

    _LOCAL_ENV_LOADED = True
    env_path = Path(__file__).resolve().with_name(".env")
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
        self, message: str, *, code: str = "metadata_error", retry_after: Optional[int] = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retry_after = retry_after


class SpotifyManager:
    """Manages Spotify client initialization and song metadata retrieval."""

    def __init__(self):
        self._ready = False
        self._credential_source = "spotDL config"
        self._config_path = str(get_config_file())
        self._fallback_tracks: Dict[str, Dict[str, Any]] = {}

    @staticmethod
    def _fallback_missing_artist(song: Optional[Dict[str, Any]]) -> bool:
        """Return True when fallback metadata lacks usable artist values."""
        if not song:
            return True

        artists = [str(artist).strip() for artist in song.get("artists") or [] if str(artist).strip()]
        if artists:
            return False

        return not str(song.get("artist") or "").strip()

    @staticmethod
    def _build_no_retry_session() -> requests.Session:
        """Create a requests session that fails fast on HTTP 429 responses."""
        session = requests.Session()
        allowed_methods = frozenset({"GET", "POST", "PUT", "DELETE"})
        status_forcelist = frozenset[int]()
        try:
            retry = Retry(
                total=0,
                connect=0,
                read=0,
                redirect=0,
                status=0,
                other=0,
                backoff_factor=0.0,
                status_forcelist=status_forcelist,
                allowed_methods=allowed_methods,
                respect_retry_after_header=False,
            )
        except TypeError:
            retry = Retry(
                total=0,
                connect=0,
                read=0,
                redirect=0,
                status=0,
                backoff_factor=0.0,
                status_forcelist=status_forcelist,
                allowed_methods=allowed_methods,
            )

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

    @staticmethod
    def _get_env_override(*names: str) -> tuple[Optional[str], Optional[str]]:
        """Return the first non-empty environment override and its name."""
        _load_local_env_file()
        for name in names:
            value = os.getenv(name, "").strip()
            if value:
                return value, name
        return None, None

    @staticmethod
    def _format_retry_after(retry_after: Optional[int]) -> str:
        """Format Retry-After in seconds and human-friendly larger units."""
        if retry_after is None:
            return ""

        message = f" Retry after about {retry_after} seconds"
        if retry_after >= 3600 and retry_after % 3600 == 0:
            message += f" ({retry_after // 3600} hours)"
        elif retry_after >= 60 and retry_after % 60 == 0:
            message += f" ({retry_after // 60} minutes)"
        return message + "."

    @staticmethod
    def _normalize_spotify_track_url(link: str) -> str:
        """Normalize a Spotify track URL so cache keys stay stable."""
        parsed = urlsplit(link.strip())
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))

    @staticmethod
    def _extract_track_id(link: str) -> str:
        """Extract the Spotify track id from a track URL."""
        match = re.search(r"/track/([A-Za-z0-9]+)", link)
        return match.group(1) if match else "unknown"

    @staticmethod
    def _find_meta_content(document: str, attr_name: str, attr_value: str) -> Optional[str]:
        """Find a meta tag's content regardless of attribute ordering."""
        escaped_attr_value = re.escape(attr_value)
        patterns = [
            rf'<meta[^>]+{attr_name}=["\']{escaped_attr_value}["\'][^>]+content=["\']([^"\']+)["\']',
            rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+{attr_name}=["\']{escaped_attr_value}["\']',
        ]
        for pattern in patterns:
            match = re.search(pattern, document, flags=re.IGNORECASE)
            if match:
                return html.unescape(match.group(1)).strip()
        return None

    @staticmethod
    def _extract_json_ld(document: str) -> Dict[str, str]:
        """Parse JSON-LD blocks for public track metadata when available."""
        results: Dict[str, str] = {}
        script_pattern = re.compile(
            r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            flags=re.IGNORECASE | re.DOTALL,
        )
        for match in script_pattern.finditer(document):
            raw_payload = html.unescape(match.group(1)).strip()
            if not raw_payload:
                continue

            try:
                payload = json.loads(raw_payload)
            except json.JSONDecodeError:
                continue

            candidates = payload if isinstance(payload, list) else [payload]
            for candidate in candidates:
                if not isinstance(candidate, dict):
                    continue

                name = candidate.get("name")
                if isinstance(name, str) and name.strip():
                    results.setdefault("title", name.strip())

                image = candidate.get("image")
                if isinstance(image, str) and image.strip():
                    results.setdefault("cover", image.strip())

                by_artist = candidate.get("byArtist")
                if isinstance(by_artist, dict):
                    artist_name = by_artist.get("name")
                    if isinstance(artist_name, str) and artist_name.strip():
                        results.setdefault("artist", artist_name.strip())

                in_album = candidate.get("inAlbum")
                if isinstance(in_album, dict):
                    album_name = in_album.get("name")
                    if isinstance(album_name, str) and album_name.strip():
                        results.setdefault("album", album_name.strip())

        return results

    @staticmethod
    def _extract_artist_and_album(description: str, title: str) -> tuple[str, str]:
        """Best-effort parse of artist and album from public page descriptions."""
        cleaned = description.strip()
        if not cleaned:
            return "", ""

        by_match = re.search(
            r"\bby\s+(?P<artist>.+?)(?:\s+on Spotify|[.,]|$)",
            cleaned,
            flags=re.IGNORECASE,
        )
        if by_match:
            return by_match.group("artist").strip(), ""

        pieces = [piece.strip() for piece in re.split(r"\s*[·•|]\s*", cleaned) if piece.strip()]
        artist = ""
        album = ""
        if pieces:
            if title and pieces[0].casefold() == title.casefold():
                pieces = pieces[1:]
            if pieces:
                artist = pieces[0]
            if len(pieces) >= 2:
                album = pieces[1]

        return artist, album

    def _song_to_metadata(self, song: Dict[str, Any]) -> Dict[str, Any]:
        """Convert an internal fallback song dict to the API metadata shape."""
        return {
            "title": song.get("name") or "(unknown)",
            "artist": ", ".join(song.get("artists") or []),
            "album": song.get("album_name") or "",
            "cover": song.get("cover_url") or "",
        }

    @staticmethod
    def _download_input_payload(
        download_input: str,
        *,
        temporary_input_file: Optional[str] = None,
        fallback_missing_artist: bool = False,
    ) -> DownloadInputPayload:
        """Build a consistent download-input payload for the app layer."""
        return {
            "input": download_input,
            "temporary_input_file": temporary_input_file,
            "fallback_missing_artist": fallback_missing_artist,
        }

    @classmethod
    def _can_use_fallback_save_file(cls, song: Optional[Dict[str, Any]]) -> bool:
        """Return True when fallback metadata is complete enough for `.spotdl` input."""
        if song is None:
            return False

        title = str(song.get("name") or "").strip()
        return bool(title and title != "(unknown)")

    @classmethod
    def _prepare_fallback_save_file_song(cls, song: Dict[str, Any]) -> Dict[str, Any]:
        """Sanitize fallback metadata so spotDL can load it without re-querying Spotify."""
        prepared_song = dict(song)
        artists = [
            str(artist).strip()
            for artist in prepared_song.get("artists") or []
            if str(artist).strip()
        ]
        artist = str(prepared_song.get("artist") or "").strip()

        if artists:
            prepared_song["artists"] = artists
            prepared_song["artist"] = artist or artists[0]
            return prepared_song

        if artist:
            prepared_song["artists"] = [artist]
            prepared_song["artist"] = artist
            return prepared_song

        # spotDL's formatter eagerly reads song.artists[0], even when the
        # selected output template doesn't use artist placeholders. Keep a
        # blank placeholder so title-only fallback downloads can still run.
        prepared_song["artists"] = [""]
        prepared_song["artist"] = ""
        return prepared_song

    def _build_fallback_song(self, link: str) -> Optional[Dict[str, Any]]:
        """Build a minimal song dict from public Spotify page metadata."""
        normalized_link = self._normalize_spotify_track_url(link)
        cached_song = self._fallback_tracks.get(normalized_link)
        if cached_song is not None:
            return cached_song

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        }

        title = ""
        artist = ""
        album = ""
        cover = ""

        try:
            response = requests.get(
                "https://open.spotify.com/oembed",
                params={"url": normalized_link},
                headers=headers,
                timeout=5,
            )
            if response.ok:
                payload = response.json()
                title = str(payload.get("title") or "").strip()
                artist = str(payload.get("author_name") or "").strip()
                cover = str(payload.get("thumbnail_url") or "").strip()
        except Exception:
            pass

        try:
            response = requests.get(normalized_link, headers=headers, timeout=5)
            response.raise_for_status()
            document = response.text

            json_ld = self._extract_json_ld(document)
            title = title or json_ld.get("title", "")
            artist = artist or json_ld.get("artist", "")
            album = album or json_ld.get("album", "")
            cover = cover or json_ld.get("cover", "")

            title = title or self._find_meta_content(document, "property", "og:title") or ""
            cover = cover or self._find_meta_content(document, "property", "og:image") or ""
            description = (
                self._find_meta_content(document, "property", "og:description")
                or self._find_meta_content(document, "name", "twitter:description")
                or ""
            )

            parsed_artist, parsed_album = self._extract_artist_and_album(description, title)
            artist = artist or parsed_artist
            album = album or parsed_album
        except Exception:
            pass

        if not title and not artist:
            return None

        track_id = self._extract_track_id(normalized_link)
        fallback_song = {
            "name": title or "(unknown)",
            "artists": [artist] if artist else [],
            "artist": artist or "",
            "genres": [],
            "disc_number": 1,
            "disc_count": 1,
            "album_name": album or "",
            "album_artist": artist or "",
            "duration": 0,
            "year": 0,
            "date": "",
            "track_number": 1,
            "tracks_count": 1,
            "song_id": track_id,
            "explicit": False,
            "publisher": "",
            "url": normalized_link,
            "isrc": None,
            "cover_url": cover or None,
            "copyright_text": None,
            "download_url": None,
            "lyrics": None,
            "popularity": None,
            "album_id": f"fallback-{track_id}",
            "list_name": None,
            "list_url": None,
            "list_position": None,
            "list_length": None,
            "artist_id": None,
            "album_type": None,
        }
        self._fallback_tracks[normalized_link] = fallback_song
        return fallback_song

    def get_download_input(self, link: str) -> DownloadInputPayload:
        """Resolve the best input for spotdl, preferring safe fallback save files."""
        if "open.spotify.com/track" not in link:
            return self._download_input_payload(link)

        normalized_link = self._normalize_spotify_track_url(link)
        fallback_song = self._fallback_tracks.get(normalized_link) or self._build_fallback_song(
            normalized_link
        )
        fallback_missing_artist = self._fallback_missing_artist(fallback_song)

        if not self._can_use_fallback_save_file(fallback_song):
            if fallback_song is not None:
                print(
                    "DEBUG - Fallback Spotify metadata is incomplete; "
                    "using the original track URL instead of a temporary .spotdl file."
                )
            return self._download_input_payload(normalized_link)

        save_file_song = self._prepare_fallback_save_file_song(fallback_song)
        if fallback_missing_artist:
            print(
                "DEBUG - Fallback Spotify metadata is missing artist info; "
                "using a sanitized temporary .spotdl file with title-only search."
            )

        temp_file = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".spotdl",
            prefix="spotdl-cask-",
            dir=tempfile.gettempdir(),
            delete=False,
        )
        with temp_file:
            json.dump([save_file_song], temp_file, ensure_ascii=True, indent=2)

        return self._download_input_payload(
            temp_file.name,
            temporary_input_file=temp_file.name,
            fallback_missing_artist=fallback_missing_artist,
        )

    def _load_spotify_settings(self) -> Dict[str, Any]:
        """Load Spotify settings from the spotDL config with env overrides."""
        config = get_config()
        self._config_path = str(get_config_file())

        client_id, client_id_env = self._get_env_override(
            "SPOTDL_CLIENT_ID",
            "SPOTIPY_CLIENT_ID",
        )
        client_secret, client_secret_env = self._get_env_override(
            "SPOTDL_CLIENT_SECRET",
            "SPOTIPY_CLIENT_SECRET",
        )

        overrides = [name for name in (client_id_env, client_secret_env) if name]
        if overrides:
            self._credential_source = ", ".join(overrides)
        else:
            self._credential_source = self._config_path

        return {
            "client_id": client_id or config.get("client_id", ""),
            "client_secret": client_secret or config.get("client_secret", ""),
            "user_auth": config.get("user_auth", False),
            "cache_path": config.get("cache_path"),
            "no_cache": config.get("no_cache", False),
            "use_cache_file": config.get("use_cache_file", False),
        }

    def ensure_client(self) -> None:
        """Initialize Spotify client if not already done."""
        if self._ready:
            return

        try:
            settings = self._load_spotify_settings()
            client_id = settings["client_id"]
            client_secret = settings["client_secret"]

            if not client_id or not client_secret:
                raise RuntimeError(
                    "Missing Spotify credentials. Set SPOTDL_CLIENT_ID and "
                    f"SPOTDL_CLIENT_SECRET, or update {self._config_path}."
                )

            spotify = cast(
                Any,
                SpotifyClient.init(
                    client_id=client_id,
                    client_secret=client_secret,
                    user_auth=settings["user_auth"],
                    cache_path=settings["cache_path"],
                    no_cache=settings["no_cache"],
                    max_retries=0,
                    use_cache_file=settings["use_cache_file"],
                ),
            )
            # spotipy retries HTTP 429 responses by default and can sleep for
            # the server's entire Retry-After window. Replace the session so the
            # app can fail fast and show a useful message instead of appearing hung.
            spotify._session = self._build_no_retry_session()
            spotify.requests_timeout = 5
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

        normalized_link = self._normalize_spotify_track_url(link)
        cached_song = self._fallback_tracks.get(normalized_link)
        if cached_song is not None:
            return self._song_to_metadata(cached_song)

        try:
            self.ensure_client()
            spotify = SpotifyClient()
            raw_track = spotify.track(normalized_link)  # type: ignore[arg-type]

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
                fallback_song = self._build_fallback_song(normalized_link)
                if fallback_song is not None:
                    return self._song_to_metadata(fallback_song)

                message = (
                    "Spotify rejected the credentials this app is using for track lookups."
                )
                message += self._format_retry_after(retry_after)
                message += (
                    f" This is not caused by the pasted link itself. Update the "
                    f"Spotify credentials in {self._config_path}, or override them "
                    "with SPOTDL_CLIENT_ID and SPOTDL_CLIENT_SECRET."
                )
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
            fallback_song = self._build_fallback_song(normalized_link)
            if fallback_song is not None:
                return self._song_to_metadata(fallback_song)

            raise MetadataError(
                "Failed to load track metadata.",
                code="metadata_error",
            ) from e


# Global instance
spotify_manager = SpotifyManager()
