"""Per-job subprocess that resolves one song and downloads it with the spotDL API."""

from __future__ import annotations

import json
import logging
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz
from spotdl.download.downloader import Downloader
from spotdl.download.progress_handler import ProgressHandler
from spotdl.types.song import Song
from spotdl.utils.formatter import create_file_name
from yt_dlp import YoutubeDL

from app.backend.inputs import UnsupportedInputError, ensure_supported_single_track
from app.backend.media import build_song_payload_from_external_info, extract_external_info
from app.backend.protocol import OUTPUT_TEMPLATE
from app.backend.spotify import SpotifyConfigurationError, configure_spotify_client

LOGGER = logging.getLogger(__name__)

_LAST_PROGRESS_DETAIL: str | None = None
_LAST_PROGRESS_VALUE: float | None = None


def _emit(event: dict[str, object]) -> None:
    print(json.dumps(event, ensure_ascii=True), flush=True)


def _detail_to_phase(detail: str) -> str:
    lowered = detail.strip().lower()
    if "download" in lowered:
        return "downloading"
    if "convert" in lowered or "embed" in lowered:
        return "postprocessing"
    if "process" in lowered or "search" in lowered or "resolv" in lowered:
        return "resolving"
    return "downloading"


def _progress_callback(tracker, detail: str) -> None:
    global _LAST_PROGRESS_DETAIL, _LAST_PROGRESS_VALUE

    progress = float(getattr(tracker, "progress", 0.0) or 0.0)
    progress_known = detail.strip().lower() != "processing"
    if _LAST_PROGRESS_DETAIL == detail and _LAST_PROGRESS_VALUE == progress:
        return

    _LAST_PROGRESS_DETAIL = detail
    _LAST_PROGRESS_VALUE = progress
    _emit(
        {
            "type": "progress",
            "phase": _detail_to_phase(detail),
            "detail": detail,
            "progress": progress,
            "progress_known": progress_known,
        }
    )


def _build_downloader(
    *,
    provider: str,
    bitrate: str,
    format_name: str,
    output_template: str,
    search_query: str | None,
    skip_album_art: bool,
) -> Downloader:
    downloader = Downloader(
        {
            "audio_providers": [provider],
            "bitrate": bitrate,
            "format": format_name,
            "output": output_template,
            "search_query": search_query,
            "simple_tui": True,
            "threads": 1,
            "scan_for_songs": False,
            "lyrics_providers": [],
            "skip_album_art": skip_album_art,
        }
    )
    downloader.progress_handler = ProgressHandler(
        simple_tui=True,
        update_callback=_progress_callback,
    )
    return downloader


def _build_song(link: str, song_payload: dict[str, Any] | None) -> Song:
    info = ensure_supported_single_track(link)

    if song_payload is not None:
        _emit({"type": "phase", "phase": "starting", "detail": "Using cached metadata"})
        return Song.from_dict(song_payload)

    if info.kind == "spotify_track":
        _emit({"type": "phase", "phase": "resolving", "detail": "Resolving Spotify track"})
        configure_spotify_client()
        return Song.from_url(info.normalized)

    _emit({"type": "phase", "phase": "resolving", "detail": "Resolving direct media link"})
    external_info = extract_external_info(info.normalized)
    payload = build_song_payload_from_external_info(info.normalized, external_info)
    return Song.from_dict(payload)


def _apply_source_override(song: Song, source_url: str | None) -> None:
    """Use a caller-provided media URL while keeping the row's song metadata."""
    cleaned = str(source_url or "").strip()
    if not cleaned:
        return

    source_info = ensure_supported_single_track(cleaned)
    if source_info.kind == "spotify_track":
        raise UnsupportedInputError("Manual source must be a direct media link, not another Spotify link.")

    song.download_url = source_info.normalized


def _expected_output_path(song: Song, output_template: str, format_name: str) -> Path:
    """Compute the deterministic final output path for the current job."""
    return create_file_name(
        song=song,
        template=output_template,
        file_extension=format_name,
    )


def _finalize_output_path(
    downloaded_song: Song,
    output_path: Path | None,
    expected_output: Path,
) -> Path:
    """Resolve the final output path even when spotDL returns `None`."""
    final_path = output_path if output_path is not None else None
    if final_path is None and expected_output.exists():
        LOGGER.warning(
            "spotDL returned no output path for %s, but the file exists at %s",
            downloaded_song.display_name,
            expected_output,
        )
        final_path = expected_output

    if final_path is None:
        raise RuntimeError(
            f'spotDL did not produce an output file for "{downloaded_song.display_name}".'
        )

    return final_path


def _unique_queries(queries: list[str]) -> list[str]:
    """Deduplicate non-empty search queries while preserving order."""
    seen: set[str] = set()
    result: list[str] = []
    for query in queries:
        cleaned = " ".join(str(query or "").split())
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
    return result


def _search_queries_for_song(song: Song) -> list[str]:
    """Build a small set of practical YouTube search queries for a song."""
    artists = [artist.strip() for artist in song.artists if str(artist).strip()]
    primary_artist = artists[0] if artists else str(song.artist or "").strip()
    secondary_artists = ", ".join(artists[:2]) if artists else primary_artist
    title = str(song.name or "").strip()
    album = str(song.album_name or "").strip()

    queries = [
        f"{primary_artist} - {title}",
        f"{primary_artist} {title}",
        f"{title} {primary_artist}",
        f"{secondary_artists} - {title}",
        f"{title} official audio",
    ]
    if album:
        queries.append(f"{primary_artist} {title} {album}")

    return _unique_queries(queries)


def _youtube_search_entries(query: str, *, limit: int = 5) -> list[dict[str, Any]]:
    """Search YouTube via yt-dlp and return flat entry metadata."""
    options = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "skip_download": True,
    }
    with YoutubeDL(options) as youtube_dl:
        data = youtube_dl.extract_info(f"ytsearch{limit}:{query}", download=False)

    entries = data.get("entries") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return []
    return [entry for entry in entries if isinstance(entry, dict)]


def _candidate_url(entry: dict[str, Any]) -> str:
    """Build a watch URL for a flat yt-dlp search entry."""
    url = str(entry.get("url") or "").strip()
    if url.startswith("http://") or url.startswith("https://"):
        return url

    video_id = str(entry.get("id") or "").strip()
    if video_id:
        return f"https://www.youtube.com/watch?v={video_id}"
    return ""


def _score_search_entry(song: Song, entry: dict[str, Any]) -> float:
    """Score a YouTube search result against the desired song metadata."""
    title = str(entry.get("title") or "")
    channel = str(entry.get("channel") or entry.get("uploader") or "")
    haystack = f"{title} {channel}"

    title_score = fuzz.token_set_ratio(song.name or "", title)
    artist_names = [artist for artist in song.artists if artist] or [song.artist or ""]
    artist_score = max(
        (fuzz.token_set_ratio(artist, haystack) for artist in artist_names if artist),
        default=0.0,
    )
    combined_score = (0.65 * title_score) + (0.35 * artist_score)

    duration = entry.get("duration")
    if isinstance(duration, (int, float)) and song.duration:
        difference = abs(int(duration) - int(song.duration))
        if difference <= 3:
            combined_score += 8
        elif difference <= 10:
            combined_score += 4
        elif difference > 45:
            combined_score -= 15

    lowered_title = title.lower()
    if "official" in lowered_title:
        combined_score += 2
    if any(token in lowered_title for token in ("lyrics", "karaoke", "cover", "nightcore")):
        combined_score -= 10

    return combined_score


def _resolve_download_url(song: Song) -> tuple[str | None, str | None]:
    """Resolve a concrete downloadable media URL for a Spotify-backed song."""
    best_url: str | None = None
    best_score = float("-inf")
    best_query: str | None = None

    for query in _search_queries_for_song(song):
        try:
            entries = _youtube_search_entries(query)
        except Exception as exc:
            LOGGER.warning("Search query failed for %s: %s", query, exc)
            continue

        for entry in entries:
            url = _candidate_url(entry)
            if not url:
                continue
            score = _score_search_entry(song, entry)
            if score > best_score:
                best_score = score
                best_url = url
                best_query = query

        if best_score >= 92:
            break

    if best_url is None or best_score < 60:
        return None, best_query

    LOGGER.info(
        "Resolved %s via YouTube search with query %r (score %.1f): %s",
        song.display_name,
        best_query,
        best_score,
        best_url,
    )
    return best_url, best_query


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    try:
        payload = json.load(sys.stdin)
        link = str(payload.get("link") or "").strip()
        song_payload = payload.get("song_payload")
        download_directory = Path(str(payload.get("download_directory") or "")).expanduser().resolve()
        audio_providers = list(payload.get("audio_providers") or ("youtube-music", "piped", "youtube"))
        format_name = str(payload.get("format") or "mp3")
        source_url = str(payload.get("source_url") or "").strip() or None
        output_template = str(download_directory / OUTPUT_TEMPLATE)
        is_spotify_track = "open.spotify.com/track/" in link.lower()

        song = _build_song(link, song_payload if isinstance(song_payload, dict) else None)
        _apply_source_override(song, source_url)
        song_seed = deepcopy(song.json)
        bitrate = str(payload.get("bitrate") or "auto")

        _emit({"type": "phase", "phase": "starting", "detail": "Preparing spotDL"})
        if song.download_url is not None:
            _emit({"type": "phase", "phase": "downloading", "detail": "Downloading direct media"})
            downloader = _build_downloader(
                provider=audio_providers[0],
                bitrate=bitrate,
                format_name=format_name,
                output_template=output_template,
                search_query=None,
                skip_album_art=not is_spotify_track,
            )
            expected_output = _expected_output_path(song, output_template, format_name)
            downloaded_song, output_path = downloader.download_song(song)
            final_path = _finalize_output_path(downloaded_song, output_path, expected_output)
            _emit({"type": "completed", "file_path": str(final_path)})
            return

        _emit({"type": "phase", "phase": "resolving", "detail": "Searching YouTube"})
        provider_song = Song.from_dict(deepcopy(song_seed))
        resolved_url, query_used = _resolve_download_url(provider_song)
        if not resolved_url:
            if query_used:
                LOGGER.warning(
                    "No usable YouTube match for %s using query %r",
                    provider_song.display_name,
                    query_used,
                )
            raise RuntimeError(f"No results found for song: {provider_song.display_name}")

        provider_song.download_url = resolved_url
        _emit({"type": "phase", "phase": "resolving", "detail": "Matched YouTube"})
        downloader = _build_downloader(
            provider="youtube",
            bitrate=bitrate,
            format_name=format_name,
            output_template=output_template,
            search_query=None,
            skip_album_art=False,
        )
        expected_output = _expected_output_path(provider_song, output_template, format_name)
        downloaded_song, output_path = downloader.download_song(provider_song)

        try:
            final_path = _finalize_output_path(downloaded_song, output_path, expected_output)
        except RuntimeError:
            provider_error = downloader.errors[-1] if downloader.errors else ""
            if provider_error:
                raise RuntimeError(provider_error.split(": ", 1)[-1]) from None
            raise RuntimeError("YouTube did not return a downloadable result.") from None

        _emit({"type": "completed", "file_path": str(final_path)})
        return
    except UnsupportedInputError as exc:
        _emit({"type": "failed", "error": str(exc)})
    except SpotifyConfigurationError as exc:
        _emit({"type": "failed", "error": str(exc)})
    except Exception as exc:
        LOGGER.exception("Download worker failed")
        _emit({"type": "failed", "error": str(exc) or "Download failed."})


if __name__ == "__main__":
    main()
