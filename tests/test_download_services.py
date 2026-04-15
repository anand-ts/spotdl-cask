"""Tests for extracted download orchestration helpers."""

import tempfile
import time
import unittest
from pathlib import Path

from app.services.downloads import (
    SAFE_FALLBACK_OUTPUT_TEMPLATE,
    TITLE_ONLY_SEARCH_QUERY,
    DownloadManager,
    ProgressParser,
    SpotdlCommandBuilder,
)


class SpotdlCommandBuilderTests(unittest.TestCase):
    """Cover explicit command construction logic."""

    def test_build_uses_extracted_settings_and_fallback_flags(self) -> None:
        """Commands should reflect quality, format, provider, and fallback overrides."""
        with tempfile.TemporaryDirectory() as tmpdir:
            builder = SpotdlCommandBuilder()
            settings = {
                "_download_directory": tmpdir,
                "_download_input": "/tmp/example.spotdl",
                "_temporary_input_file": "/tmp/example.spotdl",
                "_fallback_missing_artist": True,
                "output": "{artists} - {title}.{output-ext}",
                "audioProviders": ["youtube", "piped"],
                "quality": "default",
                "format": "flac",
                "playlistNumbering": True,
                "skipExplicit": True,
                "generateLrc": True,
            }

            command = builder.build("https://open.spotify.com/track/example", settings)

        self.assertEqual(command[:4], [command[0], "-m", "spotdl", "download"])
        self.assertIn("/tmp/example.spotdl", command)
        self.assertIn("--output", command)
        self.assertIn(
            f"{Path(tmpdir).resolve()}/{SAFE_FALLBACK_OUTPUT_TEMPLATE}", command
        )
        self.assertIn("--search-query", command)
        self.assertIn(TITLE_ONLY_SEARCH_QUERY, command)
        self.assertIn("--audio", command)
        self.assertIn("youtube", command)
        self.assertIn("piped", command)
        self.assertIn("--bitrate", command)
        self.assertIn("192k", command)
        self.assertIn("--format", command)
        self.assertIn("flac", command)
        self.assertIn("--playlist-numbering", command)
        self.assertIn("--skip-explicit", command)
        self.assertIn("--generate-lrc", command)


class ProgressParserTests(unittest.TestCase):
    """Cover extracted progress parsing logic."""

    def test_parse_extracts_percentage_from_download_output(self) -> None:
        """The parser should recognize yt-dlp style percentages."""
        parser = ProgressParser(debug_output=False)

        progress = parser.parse("[download] 48.3% of 3.14MiB at 1.20MiB/s ETA 00:02")

        self.assertEqual(progress, 48.3)

    def test_parse_returns_none_for_non_progress_lines(self) -> None:
        """Noise lines should not produce fake percentages."""
        parser = ProgressParser(debug_output=False)

        progress = parser.parse("Resolving metadata and selecting provider")

        self.assertIsNone(progress)


class DownloadCancellationTests(unittest.TestCase):
    """Cover extracted cancellation behavior in the stateful facade."""

    def test_cancel_download_records_prestart_deadline_for_idle_link(self) -> None:
        """Cancelling before process start should defer and short-circuit the next start."""
        manager = DownloadManager()
        link = "https://open.spotify.com/track/prestart"

        cancelled = manager.cancel_download(link)

        self.assertTrue(cancelled)
        self.assertEqual(manager.status[link], "idle")
        self.assertIn(link, manager.pending_cancel_deadlines)

    def test_start_download_skips_when_prestart_cancel_is_still_active(self) -> None:
        """A queued prestart cancel should stop a new worker from launching."""
        manager = DownloadManager()
        link = "https://open.spotify.com/track/skipped"
        manager.pending_cancel_deadlines[link] = time.monotonic() + 30.0

        started = manager.start_download(link, {})

        self.assertFalse(started)
        self.assertEqual(manager.status[link], "idle")
        self.assertEqual(manager.progress[link], 0.0)
        self.assertNotIn(link, manager.pending_cancel_deadlines)


if __name__ == "__main__":
    unittest.main()
