"""Regression tests for fallback download input handling."""

import json
from pathlib import Path
import unittest

from downloader import (
    DEFAULT_AUDIO_PROVIDERS,
    DownloadManager,
    SAFE_FALLBACK_OUTPUT_TEMPLATE,
)
from spotify_client import SpotifyManager


class SpotifyDownloadInputTests(unittest.TestCase):
    """Cover the Spotify fallback input handoff into the downloader."""

    def setUp(self) -> None:
        self.manager = SpotifyManager()

    def test_incomplete_fallback_uses_sanitized_temporary_save_file(self) -> None:
        """Missing-artist fallback metadata should still avoid a Spotify re-query."""
        link = "https://open.spotify.com/track/abc123"
        self.manager._fallback_tracks[link] = {
            "name": "Test Song",
            "artists": [],
            "artist": "",
            "album_name": "",
            "cover_url": None,
        }

        payload = self.manager.get_download_input(link)
        temporary_input_file = payload["temporary_input_file"]

        try:
            self.assertEqual(payload["input"], temporary_input_file)
            self.assertIsNotNone(temporary_input_file)
            self.assertTrue(payload["fallback_missing_artist"])

            with open(str(temporary_input_file), "r", encoding="utf-8") as handle:
                save_file_payload = json.load(handle)

            self.assertEqual(save_file_payload[0]["artists"], [""])
            self.assertEqual(save_file_payload[0]["artist"], "")
        finally:
            if temporary_input_file:
                Path(temporary_input_file).unlink(missing_ok=True)

    def test_complete_fallback_uses_temporary_save_file(self) -> None:
        """Complete fallback metadata can still go through a `.spotdl` file."""
        link = "https://open.spotify.com/track/xyz789"
        self.manager._fallback_tracks[link] = {
            "name": "Complete Song",
            "artists": ["Example Artist"],
            "artist": "Example Artist",
            "album_name": "Example Album",
            "cover_url": None,
        }

        payload = self.manager.get_download_input(link)
        temporary_input_file = payload["temporary_input_file"]

        try:
            self.assertEqual(payload["input"], temporary_input_file)
            self.assertIsNotNone(temporary_input_file)
            self.assertFalse(payload["fallback_missing_artist"])
        finally:
            if temporary_input_file:
                Path(temporary_input_file).unlink(missing_ok=True)

    def test_missing_fallback_uses_original_url(self) -> None:
        """If no fallback metadata can be built, fall back to the raw Spotify URL."""
        link = "https://open.spotify.com/track/no-fallback"
        self.manager._build_fallback_song = lambda _link: None  # type: ignore[assignment]

        payload = self.manager.get_download_input(link)

        self.assertEqual(payload["input"], link)
        self.assertIsNone(payload["temporary_input_file"])
        self.assertFalse(payload["fallback_missing_artist"])


class DownloaderTemplateTests(unittest.TestCase):
    """Ensure filename-template fallbacks only trigger for temp-file inputs."""

    def test_direct_url_fallback_keeps_user_template(self) -> None:
        """Direct Spotify URL retries should not be forced into title-only filenames."""
        output_template = "{artists} - {title}.{output-ext}"

        resolved_template = DownloadManager._resolve_output_template(
            {
                "output": output_template,
                "_fallback_missing_artist": True,
                "_temporary_input_file": None,
            }
        )

        self.assertEqual(resolved_template, output_template)

    def test_temporary_fallback_file_uses_safe_template(self) -> None:
        """Temp save-file inputs still need the safe filename template when incomplete."""
        resolved_template = DownloadManager._resolve_output_template(
            {
                "output": "{artists} - {title}.{output-ext}",
                "_fallback_missing_artist": True,
                "_temporary_input_file": "/tmp/fallback.spotdl",
            }
        )

        self.assertEqual(resolved_template, SAFE_FALLBACK_OUTPUT_TEMPLATE)

    def test_temporary_fallback_file_uses_title_only_search(self) -> None:
        """Incomplete fallback metadata should search providers by title only."""
        resolved_query = DownloadManager._resolve_search_query(
            {
                "_fallback_missing_artist": True,
                "_temporary_input_file": "/tmp/fallback.spotdl",
            }
        )

        self.assertEqual(resolved_query, "{title}")

    def test_direct_url_fallback_has_no_search_override(self) -> None:
        """Raw-URL fallback should not force a search-query override."""
        resolved_query = DownloadManager._resolve_search_query(
            {
                "_fallback_missing_artist": True,
                "_temporary_input_file": None,
            }
        )

        self.assertIsNone(resolved_query)

    def test_default_audio_providers_prefer_youtube_first(self) -> None:
        """The default provider chain should avoid piping every download through Piped."""
        self.assertEqual(DEFAULT_AUDIO_PROVIDERS, ("youtube", "piped"))

    def test_missing_output_message_includes_directory(self) -> None:
        """Missing-file errors should explain that no audio file was created."""
        message = DownloadManager._missing_output_message(
            Path("/tmp/downloads"),
            "JSONDecodeError: Expecting value: line 1 column 1 (char 0)",
        )

        self.assertIn("invalid data", message.lower())
        self.assertIn("/tmp/downloads", message)


if __name__ == "__main__":
    unittest.main()
