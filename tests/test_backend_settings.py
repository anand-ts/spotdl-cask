from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.backend.inputs import UnsupportedInputError, ensure_supported_single_track
from app.backend.settings import (
    DownloadRequest,
    SettingsStore,
    build_download_request,
    normalize_format,
    normalize_quality,
)


class BackendSettingsTests(unittest.TestCase):
    def test_quality_and_format_normalization_fall_back_to_defaults(self) -> None:
        self.assertEqual(normalize_quality("weird"), "best")
        self.assertEqual(normalize_format("aac"), "mp3")

    def test_build_download_request_ignores_unknown_fields(self) -> None:
        request = build_download_request(
            {
                "quality": "efficient",
                "format": "flac",
                "output": "ignored",
                "generateLrc": True,
            },
            download_dir=Path("/tmp/music"),
        )
        self.assertIsInstance(request, DownloadRequest)
        self.assertEqual(request.download_directory, Path("/tmp/music").resolve())
        self.assertEqual(request.quality, "efficient")
        self.assertEqual(request.format, "flac")
        self.assertEqual(request.bitrate, "128k")
        self.assertIsNone(request.source_url)

    def test_build_download_request_keeps_manual_source_url(self) -> None:
        request = build_download_request(
            {
                "sourceUrl": " https://www.youtube.com/watch?v=dQw4w9WgXcQ ",
            },
            download_dir=Path("/tmp/music"),
        )

        self.assertEqual(
            request.source_url,
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        )

    def test_spotify_playlist_is_rejected(self) -> None:
        with self.assertRaises(UnsupportedInputError):
            ensure_supported_single_track("https://open.spotify.com/playlist/abc123")

    def test_settings_store_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            store = SettingsStore(
                default_download_dir=temp_path / "default",
                settings_dir=temp_path / "settings",
                settings_file=temp_path / "settings" / "settings.json",
            )
            self.assertEqual(store.load()["downloadDirectory"], "")

            selected = store.set_download_dir(temp_path / "downloads")
            payload = store.load()
            self.assertEqual(Path(payload["downloadDirectory"]), selected)
            self.assertTrue(payload["hasDownloadDirectory"])


if __name__ == "__main__":
    unittest.main()
