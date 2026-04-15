"""Regression tests for metadata extraction and Finder reveal behavior."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import downloader as downloader_module
from downloader import DownloadManager
from spotify_client import SpotifyManager


class SpotifyMetadataTests(unittest.TestCase):
    """Cover metadata normalization for added song links."""

    def setUp(self) -> None:
        self.manager = SpotifyManager()

    def test_song_to_metadata_uses_singular_artist_and_album_fallbacks(self) -> None:
        """Fallback song dicts should still populate artist and album cells."""
        metadata = self.manager._song_to_metadata(
            {
                "name": "Night Drive",
                "artist": "Test Artist",
                "album": "Midnight EP",
                "cover_url": "https://example.com/cover.jpg",
            }
        )

        self.assertEqual(
            metadata,
            {
                "title": "Night Drive",
                "artist": "Test Artist",
                "album": "Midnight EP",
                "cover": "https://example.com/cover.jpg",
            },
        )

    def test_external_info_to_metadata_maps_ytdlp_fields(self) -> None:
        """yt-dlp metadata should populate the track row with useful values."""
        metadata = self.manager._external_info_to_metadata(
            {
                "track": "Ocean Avenue",
                "artists": ["Yellowcard"],
                "album": "Ocean Avenue",
                "thumbnails": [
                    {
                        "url": "https://example.com/small.jpg",
                        "width": 120,
                        "height": 90,
                    },
                    {
                        "url": "https://example.com/large.jpg",
                        "width": 1280,
                        "height": 720,
                    },
                ],
            }
        )

        self.assertEqual(
            metadata,
            {
                "title": "Ocean Avenue",
                "artist": "Yellowcard",
                "album": "Ocean Avenue",
                "cover": "https://example.com/large.jpg",
            },
        )

    def test_get_metadata_uses_external_lookup_for_non_spotify_links(self) -> None:
        """Non-Spotify song links should use the external metadata resolver."""
        expected = {
            "title": "Some Video",
            "artist": "Example Artist",
            "album": "Example Album",
            "cover": "https://example.com/thumb.jpg",
        }

        with mock.patch.object(
            self.manager, "_get_external_metadata", return_value=expected
        ) as patched:
            metadata = self.manager.get_metadata("https://youtu.be/example")

        patched.assert_called_once_with("https://youtu.be/example")
        self.assertEqual(metadata, expected)

    def test_extract_artist_and_album_skips_generic_song_markers(self) -> None:
        """Spotify page descriptions should ignore generic `Song` markers."""
        artist, album = self.manager._extract_artist_and_album(
            "Ocean Avenue · Song · Yellowcard · Ocean Avenue",
            "Ocean Avenue",
        )

        self.assertEqual(artist, "Yellowcard")
        self.assertEqual(album, "Ocean Avenue")


class DownloadRevealTests(unittest.TestCase):
    """Cover completed-download reveal behavior."""

    def setUp(self) -> None:
        self.manager = DownloadManager()

    def test_get_status_marks_completed_downloads_as_revealable(self) -> None:
        """Completed downloads should advertise when Finder reveal is available."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "song.mp3"
            file_path.write_text("audio", encoding="utf-8")

            link = "https://example.com/track"
            self.manager.status[link] = "done"
            self.manager.downloaded_files[link] = str(file_path)

            status = self.manager.get_status([link])[link]

        self.assertEqual(status["status"], "done")
        self.assertEqual(status["progress"], 100.0)
        self.assertTrue(status["can_reveal"])

    def test_reveal_downloaded_file_uses_finder_on_macos(self) -> None:
        """macOS reveal requests should use `open -R` on the downloaded file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "song.mp3"
            file_path.write_text("audio", encoding="utf-8")

            link = "https://example.com/track"
            self.manager.downloaded_files[link] = str(file_path)

            with (
                mock.patch.object(downloader_module.sys, "platform", "darwin"),
                mock.patch.object(
                    downloader_module.subprocess,
                    "run",
                    return_value=mock.Mock(returncode=0, stdout="", stderr=""),
                ) as run_mock,
            ):
                revealed_path = self.manager.reveal_downloaded_file(link)

        self.assertEqual(revealed_path, file_path)
        run_mock.assert_called_once_with(
            ["open", "-R", str(file_path)],
            capture_output=True,
            text=True,
            check=False,
        )


if __name__ == "__main__":
    unittest.main()
