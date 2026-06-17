from __future__ import annotations

import unittest
from unittest.mock import patch

from spotdl.types.song import Song

from app.backend.download_worker import _apply_source_override, _resolve_download_url
from app.backend.inputs import UnsupportedInputError


def _song_payload() -> dict[str, object]:
    return {
        "name": "Never Gonna Give You Up",
        "artists": ["Rick Astley"],
        "artist": "Rick Astley",
        "genres": [],
        "disc_number": 1,
        "disc_count": 1,
        "album_name": "Whenever You Need Somebody",
        "album_artist": "Rick Astley",
        "duration": 213,
        "year": 1987,
        "date": "1987-01-01",
        "track_number": 1,
        "tracks_count": 1,
        "song_id": "4PTG3Z6ehGkBFwjybzWkR8",
        "explicit": False,
        "publisher": "RCA",
        "url": "https://open.spotify.com/track/4PTG3Z6ehGkBFwjybzWkR8",
        "isrc": "GBARL0600786",
        "cover_url": "",
        "copyright_text": None,
        "download_url": None,
        "lyrics": None,
        "popularity": 0,
        "album_id": "album-1",
        "list_name": None,
        "list_url": None,
        "list_position": None,
        "list_length": None,
        "artist_id": "artist-1",
        "album_type": "album",
    }


class DownloadWorkerSearchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.song = Song.from_dict(_song_payload())

    def test_resolve_download_url_returns_best_match(self) -> None:
        entries = [
            {
                "id": "wrong123",
                "title": "Never Gonna Give You Up but not really",
                "channel": "Some Random Uploader",
                "duration": 500,
            },
            {
                "id": "dQw4w9WgXcQ",
                "title": "Rick Astley - Never Gonna Give You Up (Official Music Video)",
                "channel": "Rick Astley",
                "duration": 213,
            },
        ]

        with patch(
            "app.backend.download_worker._youtube_search_entries",
            return_value=entries,
        ):
            url, query = _resolve_download_url(self.song)

        self.assertEqual(query, "Rick Astley - Never Gonna Give You Up")
        self.assertEqual(url, "https://www.youtube.com/watch?v=dQw4w9WgXcQ")

    def test_resolve_download_url_returns_none_when_results_are_weak(self) -> None:
        entries = [
            {
                "id": "totally-wrong",
                "title": "City traffic in Dakar",
                "channel": "Travel Clips",
                "duration": 47,
            }
        ]

        with patch(
            "app.backend.download_worker._youtube_search_entries",
            return_value=entries,
        ):
            url, query = _resolve_download_url(self.song)

        self.assertIsNone(url)
        self.assertIsInstance(query, str)
        self.assertTrue(query)

    def test_apply_source_override_keeps_song_metadata(self) -> None:
        _apply_source_override(
            self.song,
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ&feature=share",
        )

        self.assertEqual(self.song.name, "Never Gonna Give You Up")
        self.assertEqual(
            self.song.download_url,
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ&feature=share",
        )

    def test_apply_source_override_rejects_spotify_source(self) -> None:
        with self.assertRaises(UnsupportedInputError):
            _apply_source_override(
                self.song,
                "https://open.spotify.com/track/4PTG3Z6ehGkBFwjybzWkR8",
            )


if __name__ == "__main__":
    unittest.main()
