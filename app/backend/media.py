"""Helpers for external-link metadata extraction and song payload construction."""

from __future__ import annotations

from typing import Any

from yt_dlp import YoutubeDL

from app.backend.inputs import UnsupportedInputError


def _clean_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _coalesce_text(*values: Any) -> str:
    for value in values:
        cleaned = _clean_text(value)
        if cleaned:
            return cleaned
    return ""


def _join_artists(value: Any) -> str:
    if isinstance(value, str):
        return _clean_text(value)
    if not isinstance(value, (list, tuple)):
        return ""

    artists = []
    for artist in value:
        if isinstance(artist, dict):
            artist = artist.get("name")
        cleaned = _clean_text(artist)
        if cleaned:
            artists.append(cleaned)
    return ", ".join(artists)


def _best_thumbnail(info: dict[str, Any]) -> str:
    cover = _clean_text(info.get("thumbnail"))
    thumbnails = info.get("thumbnails")
    if cover or not isinstance(thumbnails, list):
        return cover

    candidates = [
        thumbnail
        for thumbnail in thumbnails
        if isinstance(thumbnail, dict) and _clean_text(thumbnail.get("url"))
    ]
    if not candidates:
        return ""

    best = max(
        candidates,
        key=lambda thumbnail: (thumbnail.get("width", 0) or 0)
        * (thumbnail.get("height", 0) or 0),
    )
    return _clean_text(best.get("url"))


def _normalize_entries(info: dict[str, Any]) -> dict[str, Any]:
    entries = info.get("entries")
    if isinstance(entries, list):
        valid_entries = [entry for entry in entries if isinstance(entry, dict)]
        if len(valid_entries) != 1:
            raise UnsupportedInputError(
                "Playlist and collection links are not supported in this version."
            )
        return valid_entries[0]
    return info


def extract_external_info(link: str) -> dict[str, Any]:
    """Extract direct-media metadata without downloading the media."""
    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": False,
    }
    with YoutubeDL(options) as youtube_dl:
        info = youtube_dl.extract_info(link, download=False)

    if not isinstance(info, dict):
        raise RuntimeError("yt-dlp did not return metadata for this link.")
    return _normalize_entries(info)


def metadata_from_song_payload(song_payload: dict[str, Any]) -> dict[str, str]:
    """Map a normalized song payload to the frontend metadata shape."""
    return {
        "title": _coalesce_text(song_payload.get("name")) or "(unknown)",
        "artist": _join_artists(song_payload.get("artists"))
        or _coalesce_text(song_payload.get("artist")),
        "album": _coalesce_text(song_payload.get("album_name")),
        "cover": _coalesce_text(song_payload.get("cover_url")),
    }


def build_song_payload_from_external_info(
    link: str,
    info: dict[str, Any],
) -> dict[str, Any]:
    """Create a complete-ish Song payload for a direct media link."""
    title = _coalesce_text(
        info.get("track"),
        info.get("title"),
        info.get("fulltitle"),
    ) or "(unknown)"
    artist = _join_artists(info.get("artists")) or _coalesce_text(
        info.get("artist"),
        info.get("creator"),
        info.get("uploader"),
        info.get("channel"),
    )
    album = _coalesce_text(info.get("album"))
    upload_date = _clean_text(info.get("upload_date"))
    if len(upload_date) == 8 and upload_date.isdigit():
        date = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:8]}"
        year = int(upload_date[:4])
    else:
        date = ""
        year = 0

    song_id = _coalesce_text(info.get("id")) or title.lower().replace(" ", "-")
    artist_names = [artist] if artist else []

    return {
        "name": title,
        "artists": artist_names,
        "artist": artist,
        "genres": [],
        "disc_number": 1,
        "disc_count": 1,
        "album_name": album,
        "album_artist": artist,
        "duration": int(info.get("duration") or 0),
        "year": year,
        "date": date,
        "track_number": 1,
        "tracks_count": 1,
        "song_id": song_id,
        "explicit": False,
        "publisher": _coalesce_text(info.get("channel"), info.get("uploader")),
        "url": link,
        "isrc": None,
        "cover_url": _best_thumbnail(info),
        "copyright_text": None,
        "download_url": link,
        "lyrics": None,
        "popularity": None,
        "album_id": f"external-{song_id}",
        "list_name": None,
        "list_url": None,
        "list_position": None,
        "list_length": None,
        "artist_id": None,
        "album_type": None,
    }
