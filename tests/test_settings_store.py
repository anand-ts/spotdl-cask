"""Tests for the extracted settings persistence primitives."""

import tempfile
import unittest
from pathlib import Path

from app.settings import SettingsStore


class SettingsStoreTests(unittest.TestCase):
    """Cover default loading and persisted download-directory behavior."""

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.store = SettingsStore(
            default_download_dir=self.root / "Downloads" / "spotdl",
            settings_dir=self.root / ".settings",
            settings_file=self.root / ".settings" / "settings.json",
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_load_returns_default_payload_when_settings_are_missing(self) -> None:
        """Missing settings should still produce the expected API payload shape."""
        payload = self.store.load()

        self.assertEqual(payload["downloadDirectory"], "")
        self.assertFalse(payload["hasDownloadDirectory"])
        self.assertEqual(
            payload["defaultDownloadDirectory"],
            str((self.root / "Downloads" / "spotdl").resolve()),
        )

    def test_load_falls_back_to_defaults_for_invalid_json(self) -> None:
        """Corrupt settings files should not crash the app."""
        self.store.settings_dir.mkdir(parents=True, exist_ok=True)
        self.store.settings_file.write_text("{not valid json", encoding="utf-8")

        payload = self.store.load()

        self.assertEqual(payload["downloadDirectory"], "")
        self.assertFalse(payload["hasDownloadDirectory"])

    def test_set_download_dir_creates_directory_and_persists_normalized_path(
        self,
    ) -> None:
        """Selected directories should be created and stored as absolute paths."""
        relative_dir = self.root / "music" / "downloads"

        stored_path = self.store.set_download_dir(relative_dir)
        payload = self.store.load()

        self.assertTrue(stored_path.exists())
        self.assertEqual(stored_path, relative_dir.resolve())
        self.assertEqual(payload["downloadDirectory"], str(relative_dir.resolve()))
        self.assertTrue(payload["hasDownloadDirectory"])
        self.assertEqual(self.store.get_download_dir(), relative_dir.resolve())


if __name__ == "__main__":
    unittest.main()
