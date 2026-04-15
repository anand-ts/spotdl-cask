"""Spotify and metadata services used by the Flask layer."""

from __future__ import annotations

import html
import json
import logging
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
    from spotdl.utils.config import get_config, get_config_file
    from spotdl.utils.spotify import SpotifyClient
    from spotipy.exceptions import SpotifyException
except ImportError as e:
    raise SystemExit(
        "spotdl>=4 must be installed. Run `./setup`, then `./dev` or `./run`."
    ) from e


_LOCAL_ENV_LOADED = False
LOGGER = logging.getLogger(__name__)


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


class SpotifyConfigLoader:
    """Load Spotify credentials from spotDL config and environment overrides."""

    def __init__(self, manager: "SpotifyManager") -> None:
        self.manager = manager

    @staticmethod
    def get_env_override(*names: str) -> tuple[Optional[str], Optional[str]]:
        """Return the first non-empty environment override and its name."""
        _load_local_env_file()
        for name in names:
            value = os.getenv(name, "").strip()
            if value:
                return value, name
        return None, None

    @staticmethod
    def format_retry_after(retry_after: Optional[int]) -> str:
        """Format Retry-After in seconds and human-friendly larger units."""
        if retry_after is None:
            return ""

        message = f" Retry after about {retry_after} seconds"
        if retry_after >= 3600 and retry_after % 3600 == 0:
            message += f" ({retry_after // 3600} hours)"
        elif retry_after >= 60 and retry_after % 60 == 0:
            message += f" ({retry_after // 60} minutes)"
        return message + "."

    def load_spotify_settings(self) -> Dict[str, Any]:
        """Load Spotify settings from the spotDL config with env overrides."""
        config = get_config()
        self.manager._config_path = str(get_config_file())

        client_id, client_id_env = self.get_env_override(
            "SPOTDL_CLIENT_ID",
            "SPOTIPY_CLIENT_ID",
        )
        client_secret, client_secret_env = self.get_env_override(
            "SPOTDL_CLIENT_SECRET",
            "SPOTIPY_CLIENT_SECRET",
        )

        overrides = [name for name in (client_id_env, client_secret_env) if name]
        if overrides:
            self.manager._credential_source = ", ".join(overrides)
        else:
            self.manager._credential_source = self.manager._config_path

        return {
            "client_id": client_id or config.get("client_id", ""),
            "client_secret": client_secret or config.get("client_secret", ""),
            "user_auth": config.get("user_auth", False),
            "cache_path": config.get("cache_path"),
            "no_cache": config.get("no_cache", False),
            "use_cache_file": config.get("use_cache_file", False),
        }


class ExternalMetadataService:
    """Resolve metadata for non-Spotify links and normalize metadata payloads."""

    @staticmethod
    def clean_metadata_text(value: Any) -> str:
        """Normalize a metadata field into a clean string."""
        if value is None:
            return ""

        return str(value).strip()

    @classmethod
    def coalesce_metadata_text(cls, *values: Any) -> str:
        """Return the first non-empty metadata string from a list of values."""
        for value in values:
            cleaned_value = cls.clean_metadata_text(value)
            if cleaned_value:
                return cleaned_value

        return ""

    @classmethod
    def stringify_artists(cls, song: Dict[str, Any]) -> str:
        """Return the best artist string from a song-like metadata dict."""
        artists = [
            cls.clean_metadata_text(artist)
            for artist in song.get("artists") or []
            if cls.clean_metadata_text(artist)
        ]
        if artists:
            return ", ".join(artists)

        return cls.clean_metadata_text(song.get("artist"))

    @classmethod
    def extract_thumbnail(cls, info: Dict[str, Any]) -> str:
        """Pick the best available thumbnail URL from yt-dlp metadata."""
        direct_thumbnail = cls.clean_metadata_text(info.get("thumbnail"))
        if direct_thumbnail:
            return direct_thumbnail

        thumbnails = info.get("thumbnails") or []
        if isinstance(thumbnails, list):
            candidates = [
                thumbnail
                for thumbnail in thumbnails
                if isinstance(thumbnail, dict)
                and cls.clean_metadata_text(thumbnail.get("url"))
            ]
            if candidates:
                best_thumbnail = max(
                    candidates,
                    key=lambda thumbnail: (
                        (thumbnail.get("width") or 0) * (thumbnail.get("height") or 0)
                    ),
                )
                return cls.clean_metadata_text(best_thumbnail.get("url"))

        return ""

    @classmethod
    def external_info_to_metadata(cls, info: Dict[str, Any]) -> Dict[str, Any]:
        """Map yt-dlp metadata into the app's metadata response shape."""
        artists = info.get("artists")
        artist_text = ""
        if isinstance(artists, (list, tuple)):
            artist_candidates = [
                cls.clean_metadata_text(artist)
                for artist in artists
                if cls.clean_metadata_text(artist)
            ]
            if artist_candidates:
                artist_text = ", ".join(artist_candidates)
        elif isinstance(artists, str):
            artist_text = cls.clean_metadata_text(artists)

        artist_text = artist_text or cls.coalesce_metadata_text(
            info.get("artist"),
            info.get("creator"),
            info.get("uploader"),
            info.get("channel"),
            info.get("album_artist"),
        )

        album_text = cls.coalesce_metadata_text(
            info.get("album"),
            info.get("album_title"),
            info.get("playlist_title"),
            info.get("playlist"),
            info.get("collection"),
        )

        title_text = cls.coalesce_metadata_text(
            info.get("track"),
            info.get("title"),
            info.get("fulltitle"),
        )

        return {
            "title": title_text or "(unknown)",
            "artist": artist_text,
            "album": album_text,
            "cover": cls.extract_thumbnail(info),
        }

    def get_external_metadata(self, link: str) -> Optional[Dict[str, Any]]:
        """Fetch metadata for non-Spotify media links using yt-dlp."""
        try:
            import yt_dlp
        except ImportError:
            LOGGER.warning(
                "yt-dlp is unavailable; external metadata lookup is disabled."
            )
            return None

        options = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "extract_flat": False,
            "skip_download": True,
        }

        try:
            with yt_dlp.YoutubeDL(options) as downloader:
                info = downloader.extract_info(link, download=False)
        except Exception:
            LOGGER.exception("External metadata lookup failed for %s", link)
            return None

        if isinstance(info, dict) and info.get("entries"):
            entries = info.get("entries") or []
            info = next((entry for entry in entries if isinstance(entry, dict)), info)

        if not isinstance(info, dict):
            return None

        metadata = self.external_info_to_metadata(info)
        if not any(
            value for value in metadata.values() if value and value != "(unknown)"
        ):
            return None

        return metadata


class SpotifyPageMetadataService:
    """Resolve fallback metadata directly from public Spotify pages."""

    def __init__(self, fallback_tracks: Dict[str, Dict[str, Any]]) -> None:
        self.fallback_tracks = fallback_tracks

    @staticmethod
    def normalize_spotify_track_url(link: str) -> str:
        """Normalize a Spotify track URL so cache keys stay stable."""
        parsed = urlsplit(link.strip())
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))

    @staticmethod
    def extract_track_id(link: str) -> str:
        """Extract the Spotify track id from a track URL."""
        match = re.search(r"/track/([A-Za-z0-9]+)", link)
        return match.group(1) if match else "unknown"

    @staticmethod
    def normalize_description_piece(value: str) -> str:
        """Clean a description fragment before artist/album inference."""
        cleaned = re.sub(r"\s+", " ", value).strip().strip(".,;:-")
        cleaned = re.sub(r"\s+on spotify$", "", cleaned, flags=re.IGNORECASE)
        return cleaned.strip()

    @staticmethod
    def find_meta_content(
        document: str, attr_name: str, attr_value: str
    ) -> Optional[str]:
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
    def extract_json_ld(document: str) -> Dict[str, str]:
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
    def extract_title_and_artist_from_page_title(raw_title: str) -> tuple[str, str]:
        """Parse Spotify-style page titles like `Track - song by Artist | Spotify`."""
        cleaned = raw_title.strip()
        if not cleaned:
            return "", ""

        cleaned = re.sub(r"\s*\|\s*spotify\s*$", "", cleaned, flags=re.IGNORECASE)
        match = re.match(
            r"^(?P<title>.+?)\s*-\s*(?:song(?:\s+and\s+lyrics)?|single|track)\s+by\s+(?P<artist>.+)$",
            cleaned,
            flags=re.IGNORECASE,
        )
        if match:
            return (
                match.group("title").strip(),
                match.group("artist").strip(),
            )

        return cleaned, ""

    @classmethod
    def extract_artist_and_album(cls, description: str, title: str) -> tuple[str, str]:
        """Best-effort parse of artist and album from public page descriptions."""
        cleaned = re.sub(r"\s+", " ", description).strip()
        if not cleaned:
            return "", ""

        if title:
            cleaned = re.sub(
                rf"^listen to\s+{re.escape(title)}\s+on spotify[.!]?\s*",
                "",
                cleaned,
                flags=re.IGNORECASE,
            )
            cleaned = re.sub(
                rf"^{re.escape(title)}\s*[·•|:-]\s*",
                "",
                cleaned,
                flags=re.IGNORECASE,
            )

        by_match = re.search(
            r"\bby\s+(?P<artist>.+?)(?:\s+on Spotify|[.,]|$)",
            cleaned,
            flags=re.IGNORECASE,
        )
        if by_match:
            return by_match.group("artist").strip(), ""

        pieces = [
            cls.normalize_description_piece(piece)
            for piece in re.split(r"\s*[·•|]\s*", cleaned)
            if cls.normalize_description_piece(piece)
        ]
        if title:
            while pieces and pieces[0].casefold() == title.casefold():
                pieces = pieces[1:]

        generic_tokens = {"song", "single", "album", "ep", "explicit"}
        filtered_pieces = []
        for piece in pieces:
            if piece.casefold() in generic_tokens:
                continue
            if re.fullmatch(r"\d{4}", piece):
                continue
            filtered_pieces.append(piece)

        artist = filtered_pieces[0] if filtered_pieces else ""
        album = ""
        for piece in filtered_pieces[1:]:
            if piece.casefold() == artist.casefold():
                continue
            album = piece
            break

        return artist, album

    def build_fallback_song(self, link: str) -> Optional[Dict[str, Any]]:
        """Build a minimal song dict from public Spotify page metadata."""
        normalized_link = self.normalize_spotify_track_url(link)
        cached_song = self.fallback_tracks.get(normalized_link)
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

            json_ld = self.extract_json_ld(document)
            title = title or json_ld.get("title", "")
            artist = artist or json_ld.get("artist", "")
            album = album or json_ld.get("album", "")
            cover = cover or json_ld.get("cover", "")

            og_title = self.find_meta_content(document, "property", "og:title") or ""
            parsed_page_title, parsed_page_artist = (
                self.extract_title_and_artist_from_page_title(og_title)
            )
            title = title or parsed_page_title or og_title
            artist = artist or parsed_page_artist
            cover = (
                cover or self.find_meta_content(document, "property", "og:image") or ""
            )
            description = (
                self.find_meta_content(document, "property", "og:description")
                or self.find_meta_content(document, "name", "twitter:description")
                or ""
            )

            parsed_artist, parsed_album = self.extract_artist_and_album(
                description, title
            )
            artist = artist or parsed_artist
            album = album or parsed_album
        except Exception:
            pass

        if not title and not artist:
            return None

        track_id = self.extract_track_id(normalized_link)
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
        self.fallback_tracks[normalized_link] = fallback_song
        return fallback_song


class DownloadInputResolver:
    """Resolve the best spotDL input payload for a user-provided link."""

    def __init__(self, manager: "SpotifyManager") -> None:
        self.manager = manager

    @staticmethod
    def download_input_payload(
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

    @staticmethod
    def fallback_missing_artist(song: Optional[Dict[str, Any]]) -> bool:
        """Return True when fallback metadata lacks usable artist values."""
        if not song:
            return True

        artists = [
            str(artist).strip()
            for artist in song.get("artists") or []
            if str(artist).strip()
        ]
        if artists:
            return False

        return not str(song.get("artist") or "").strip()

    @staticmethod
    def can_use_fallback_save_file(song: Optional[Dict[str, Any]]) -> bool:
        """Return True when fallback metadata is complete enough for `.spotdl` input."""
        if song is None:
            return False

        title = str(song.get("name") or "").strip()
        return bool(title and title != "(unknown)")

    @classmethod
    def prepare_fallback_save_file_song(cls, song: Dict[str, Any]) -> Dict[str, Any]:
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

        prepared_song["artists"] = [""]
        prepared_song["artist"] = ""
        return prepared_song

    def get_download_input(self, link: str) -> DownloadInputPayload:
        """Resolve the best input for spotdl, preferring safe fallback save files."""
        if "open.spotify.com/track" not in link:
            return self.download_input_payload(link)

        normalized_link = self.manager._normalize_spotify_track_url(link)
        fallback_song = self.manager._fallback_tracks.get(
            normalized_link
        ) or self.manager._build_fallback_song(normalized_link)
        fallback_missing_artist = self.fallback_missing_artist(fallback_song)

        if not self.can_use_fallback_save_file(fallback_song):
            if fallback_song is not None:
                print(
                    "DEBUG - Fallback Spotify metadata is incomplete; "
                    "using the original track URL instead of a temporary .spotdl file."
                )
            return self.download_input_payload(normalized_link)

        assert fallback_song is not None
        save_file_song = self.prepare_fallback_save_file_song(fallback_song)
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

        return self.download_input_payload(
            temp_file.name,
            temporary_input_file=temp_file.name,
            fallback_missing_artist=fallback_missing_artist,
        )


class MetadataService:
    """Fetch and normalize metadata for Spotify and external links."""

    def __init__(self, manager: "SpotifyManager") -> None:
        self.manager = manager

    def ensure_client(self) -> None:
        """Initialize Spotify client if not already done."""
        if self.manager._ready:
            return

        try:
            settings = self.manager.config_loader.load_spotify_settings()
            client_id = settings["client_id"]
            client_secret = settings["client_secret"]

            if not client_id or not client_secret:
                raise RuntimeError(
                    "Missing Spotify credentials. Set SPOTDL_CLIENT_ID and "
                    f"SPOTDL_CLIENT_SECRET, or update {self.manager._config_path}."
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
            spotify._session = self.manager._build_no_retry_session()
            spotify.requests_timeout = 5
            self.manager._ready = True
        except Exception as e:
            if "already been initialized" in str(e):
                self.manager._ready = True
                return
            raise RuntimeError(f"Failed to initialize Spotify client: {e}") from e

    def get_metadata(self, link: str) -> Dict[str, Any]:
        """Get song metadata from a Spotify or external media link."""
        if "open.spotify.com/track" not in link:
            metadata = self.manager._get_external_metadata(link)
            if metadata is not None:
                return metadata

            return {
                "title": "(unknown)",
                "artist": "",
                "album": "",
                "cover": "",
            }

        normalized_link = self.manager._normalize_spotify_track_url(link)
        cached_song = self.manager._fallback_tracks.get(normalized_link)
        if cached_song is not None:
            return self.manager._song_to_metadata(cached_song)

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
            retry_after = self.manager._parse_retry_after(getattr(e, "headers", None))
            if e.http_status == 429:
                fallback_song = self.manager._build_fallback_song(normalized_link)
                if fallback_song is not None:
                    return self.manager._song_to_metadata(fallback_song)

                message = "Spotify rejected the credentials this app is using for track lookups."
                message += self.manager._format_retry_after(retry_after)
                message += (
                    f" This is not caused by the pasted link itself. Update the "
                    f"Spotify credentials in {self.manager._config_path}, or override them "
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
            LOGGER.exception("Metadata error for %s", link)
            fallback_song = self.manager._build_fallback_song(normalized_link)
            if fallback_song is not None:
                return self.manager._song_to_metadata(fallback_song)

            raise MetadataError(
                "Failed to load track metadata.",
                code="metadata_error",
            ) from e


class SpotifyManager:
    """Compatibility facade that composes the dedicated metadata services."""

    metadata_error_class = MetadataError

    def __init__(self):
        self._ready = False
        self._credential_source = "spotDL config"
        self._config_path = str(get_config_file())
        self._fallback_tracks: Dict[str, Dict[str, Any]] = {}
        self.config_loader = SpotifyConfigLoader(self)
        self.external_metadata_service = ExternalMetadataService()
        self.page_metadata_service = SpotifyPageMetadataService(self._fallback_tracks)
        self.download_input_resolver = DownloadInputResolver(self)
        self.metadata_service = MetadataService(self)

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

    def _get_env_override(self, *names: str) -> tuple[Optional[str], Optional[str]]:
        return self.config_loader.get_env_override(*names)

    def _format_retry_after(self, retry_after: Optional[int]) -> str:
        return self.config_loader.format_retry_after(retry_after)

    def _normalize_spotify_track_url(self, link: str) -> str:
        return self.page_metadata_service.normalize_spotify_track_url(link)

    def _extract_track_id(self, link: str) -> str:
        return self.page_metadata_service.extract_track_id(link)

    def _find_meta_content(
        self, document: str, attr_name: str, attr_value: str
    ) -> Optional[str]:
        return self.page_metadata_service.find_meta_content(
            document, attr_name, attr_value
        )

    def _extract_json_ld(self, document: str) -> Dict[str, str]:
        return self.page_metadata_service.extract_json_ld(document)

    def _extract_artist_and_album(
        self, description: str, title: str
    ) -> tuple[str, str]:
        return self.page_metadata_service.extract_artist_and_album(description, title)

    def _clean_metadata_text(self, value: Any) -> str:
        return self.external_metadata_service.clean_metadata_text(value)

    def _coalesce_metadata_text(self, *values: Any) -> str:
        return self.external_metadata_service.coalesce_metadata_text(*values)

    def _stringify_artists(self, song: Dict[str, Any]) -> str:
        return self.external_metadata_service.stringify_artists(song)

    def _extract_thumbnail(self, info: Dict[str, Any]) -> str:
        return self.external_metadata_service.extract_thumbnail(info)

    def _external_info_to_metadata(self, info: Dict[str, Any]) -> Dict[str, Any]:
        return self.external_metadata_service.external_info_to_metadata(info)

    def _get_external_metadata(self, link: str) -> Optional[Dict[str, Any]]:
        return self.external_metadata_service.get_external_metadata(link)

    def _song_to_metadata(self, song: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "title": self._clean_metadata_text(song.get("name")) or "(unknown)",
            "artist": self._stringify_artists(song),
            "album": self._coalesce_metadata_text(
                song.get("album_name"), song.get("album")
            ),
            "cover": self._clean_metadata_text(song.get("cover_url")),
        }

    def _download_input_payload(
        self,
        download_input: str,
        *,
        temporary_input_file: Optional[str] = None,
        fallback_missing_artist: bool = False,
    ) -> DownloadInputPayload:
        return self.download_input_resolver.download_input_payload(
            download_input,
            temporary_input_file=temporary_input_file,
            fallback_missing_artist=fallback_missing_artist,
        )

    def _fallback_missing_artist(self, song: Optional[Dict[str, Any]]) -> bool:
        return self.download_input_resolver.fallback_missing_artist(song)

    def _can_use_fallback_save_file(self, song: Optional[Dict[str, Any]]) -> bool:
        return self.download_input_resolver.can_use_fallback_save_file(song)

    def _prepare_fallback_save_file_song(self, song: Dict[str, Any]) -> Dict[str, Any]:
        return self.download_input_resolver.prepare_fallback_save_file_song(song)

    def _build_fallback_song(self, link: str) -> Optional[Dict[str, Any]]:
        return self.page_metadata_service.build_fallback_song(link)

    def _load_spotify_settings(self) -> Dict[str, Any]:
        return self.config_loader.load_spotify_settings()

    def ensure_client(self) -> None:
        self.metadata_service.ensure_client()

    def get_download_input(self, link: str) -> DownloadInputPayload:
        return self.download_input_resolver.get_download_input(link)

    def get_metadata(self, link: str) -> Dict[str, Any]:
        return self.metadata_service.get_metadata(link)


spotify_manager = SpotifyManager()
