"""Smoke tests for the refactored Flask route registration."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.settings import SettingsStore
from app.web import create_app
from spotify_client import MetadataError


class FakeMetadataManager:
    """Minimal metadata facade for route tests."""

    def __init__(self) -> None:
        self.metadata_error_class = MetadataError
        self.metadata_payload = {
            "title": "Track Title",
            "artist": "Track Artist",
            "album": "Track Album",
            "cover": "https://example.com/cover.jpg",
        }
        self.download_input_payload = {
            "input": "https://open.spotify.com/track/example",
            "temporary_input_file": None,
            "fallback_missing_artist": False,
        }
        self.metadata_error = None
        self.last_download_input_link = None

    def get_metadata(self, link: str):
        if self.metadata_error is not None:
            raise self.metadata_error
        return {**self.metadata_payload, "link": link}

    def get_download_input(self, link: str):
        self.last_download_input_link = link
        return dict(self.download_input_payload)


class FakeDownloadService:
    """Minimal download facade for route tests."""

    def __init__(self) -> None:
        self.started = []
        self.status_payload = {}
        self.cancel_result = True
        self.revealed_path = Path("/tmp/example.mp3")

    def start_download(self, link: str, settings: dict) -> None:
        self.started.append((link, settings))

    def get_status(self, links: list[str]) -> dict:
        return {
            link: self.status_payload.get(link, {"status": "idle", "progress": 0.0})
            for link in links
        }

    def cancel_download(self, link: str) -> bool:
        return self.cancel_result

    def reveal_downloaded_file(self, link: str) -> Path:
        if link == "missing":
            raise FileNotFoundError("Downloaded file could not be found.")
        return self.revealed_path


class RouteSmokeTests(unittest.TestCase):
    """Ensure the refactored routes preserve their public contract."""

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.settings_store = SettingsStore(
            default_download_dir=self.root / "Downloads" / "spotdl",
            settings_dir=self.root / ".settings",
            settings_file=self.root / ".settings" / "settings.json",
        )
        self.metadata_manager = FakeMetadataManager()
        self.download_service = FakeDownloadService()
        self.app = create_app(
            metadata_manager=self.metadata_manager,
            download_service=self.download_service,
            active_settings_store=self.settings_store,
        )
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_index_route_renders_main_shell(self) -> None:
        """The main page should still render the application shell."""
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("spotDL Web Downloader", response.get_data(as_text=True))
        self.assertIn('rel="icon"', response.get_data(as_text=True))

    def test_favicon_route_serves_bundled_icon(self) -> None:
        """The browser favicon request should resolve without a 404."""
        response = self.client.get("/favicon.ico")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "image/svg+xml")

    def test_settings_routes_return_and_persist_download_directory_payload(
        self,
    ) -> None:
        """Settings endpoints should preserve the existing response shape."""
        initial_response = self.client.get("/settings")
        initial_payload = initial_response.get_json()

        self.assertEqual(initial_response.status_code, 200)
        self.assertEqual(initial_payload["downloadDirectory"], "")
        self.assertIn("hasDownloadDirectory", initial_payload)
        self.assertIn("defaultDownloadDirectory", initial_payload)

        selected_dir = self.root / "music"
        update_response = self.client.post(
            "/settings",
            json={"downloadDirectory": str(selected_dir)},
        )
        update_payload = update_response.get_json()

        self.assertEqual(update_response.status_code, 200)
        self.assertEqual(
            update_payload["downloadDirectory"], str(selected_dir.resolve())
        )
        self.assertTrue(update_payload["hasDownloadDirectory"])

    def test_pick_download_directory_route_supports_cancel_and_selection(self) -> None:
        """The native picker route should preserve both cancel and success responses."""
        with (
            mock.patch("app.routes._best_initial_directory", return_value=self.root),
            mock.patch(
                "app.routes._choose_directory",
                side_effect=[None, self.root / "picked"],
            ),
        ):
            cancelled_response = self.client.post(
                "/settings/download-directory/pick", json={"source": "startup"}
            )
            selected_response = self.client.post(
                "/settings/download-directory/pick", json={"source": "settings"}
            )

        self.assertEqual(cancelled_response.status_code, 200)
        self.assertTrue(cancelled_response.get_json()["cancelled"])
        self.assertEqual(selected_response.status_code, 200)
        self.assertEqual(
            selected_response.get_json()["downloadDirectory"],
            str((self.root / "picked").resolve()),
        )

    def test_meta_route_returns_payload_and_rate_limited_errors(self) -> None:
        """Metadata lookup should preserve both success and structured error payloads."""
        response = self.client.post(
            "/meta", json={"link": "https://open.spotify.com/track/example"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["title"], "Track Title")

        self.metadata_manager.metadata_error = MetadataError(
            "Retry later",
            code="rate_limited",
            retry_after=12,
        )
        error_response = self.client.post(
            "/meta", json={"link": "https://open.spotify.com/track/example"}
        )
        error_payload = error_response.get_json()

        self.assertEqual(error_response.status_code, 429)
        self.assertEqual(error_payload["code"], "rate_limited")
        self.assertEqual(error_payload["retry_after"], 12)

    def test_meta_route_normalizes_legacy_metadata_shapes(self) -> None:
        """The route should coerce raw/legacy metadata fields into UI-safe keys."""
        self.metadata_manager.metadata_payload = {
            "name": "Track Title",
            "artists": ["Track Artist"],
            "album_name": "Track Album",
            "cover_url": "https://example.com/cover.jpg",
        }

        response = self.client.post(
            "/meta", json={"link": "https://open.spotify.com/track/example"}
        )

        self.assertEqual(
            response.get_json(),
            {
                "title": "Track Title",
                "artist": "Track Artist",
                "album": "Track Album",
                "cover": "https://example.com/cover.jpg",
            },
        )

    def test_download_route_merges_download_input_and_saved_directory(self) -> None:
        """Download starts should still compose settings exactly once at the route layer."""
        self.settings_store.set_download_dir(self.root / "downloads")

        response = self.client.post(
            "/download",
            json={
                "link": "https://open.spotify.com/track/example",
                "quality": "best",
                "format": "mp3",
            },
        )

        self.assertEqual(response.status_code, 204)
        self.assertEqual(
            self.metadata_manager.last_download_input_link,
            "https://open.spotify.com/track/example",
        )
        self.assertEqual(len(self.download_service.started), 1)

        started_link, started_settings = self.download_service.started[0]
        self.assertEqual(started_link, "https://open.spotify.com/track/example")
        self.assertEqual(
            started_settings["_download_directory"],
            str((self.root / "downloads").resolve()),
        )
        self.assertEqual(
            started_settings["_download_input"],
            "https://open.spotify.com/track/example",
        )
        self.assertIsNone(started_settings["_temporary_input_file"])
        self.assertFalse(started_settings["_fallback_missing_artist"])

    def test_status_cancel_and_reveal_routes_preserve_response_shapes(self) -> None:
        """The remaining operational routes should still return their previous contracts."""
        link = "https://open.spotify.com/track/example"
        self.download_service.status_payload[link] = {
            "status": "done",
            "progress": 100.0,
            "can_reveal": True,
        }

        status_response = self.client.get(f"/status?links={link}")
        cancel_response = self.client.post("/cancel", json={"link": link})
        reveal_response = self.client.post("/reveal", json={"link": link})

        self.assertEqual(status_response.status_code, 200)
        self.assertEqual(status_response.get_json()[link]["status"], "done")
        self.assertEqual(cancel_response.status_code, 204)
        self.assertEqual(reveal_response.status_code, 200)
        self.assertEqual(
            reveal_response.get_json()["path"], str(self.download_service.revealed_path)
        )


if __name__ == "__main__":
    unittest.main()
