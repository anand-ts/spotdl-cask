from __future__ import annotations

import unittest
from pathlib import Path

from app.backend.metadata import MetadataError
from app.web import create_app


class _SettingsStoreStub:
    def __init__(self) -> None:
        self.download_dir = Path("/tmp/music")

    def load(self):
        return {
            "downloadDirectory": str(self.download_dir),
            "hasDownloadDirectory": True,
            "defaultDownloadDirectory": str(self.download_dir),
        }

    def get_download_dir(self):
        return self.download_dir

    def set_download_dir(self, value):
        self.download_dir = Path(value)
        return self.download_dir


class _MetadataStub:
    def get_metadata(self, link: str):
        if link.endswith("bad"):
            raise MetadataError("bad metadata", status_code=502)
        return {
            "title": "Song",
            "artist": "Artist",
            "album": "Album",
            "cover": "",
        }

    def get_cached_song_payload(self, _link: str):
        return None


class _DownloadStub:
    def __init__(self) -> None:
        self.started = []

    def start_download(self, link, request) -> None:
        self.started.append((link, request))

    def get_status(self, links):
        return {
            link: {
                "status": "queued",
                "phase": "queued",
                "detail": "Queued",
                "progress": 0,
                "progress_known": False,
                "can_reveal": False,
            }
            for link in links
        }

    def cancel_download(self, _link):
        return True

    def reveal_downloaded_file(self, _link):
        return Path("/tmp/music/song.mp3")


class AppRouteTests(unittest.TestCase):
    def test_download_route_accepts_current_frontend_shape(self) -> None:
        metadata = _MetadataStub()
        downloads = _DownloadStub()
        app = create_app(
            metadata_service=metadata,
            download_service=downloads,
            active_settings_store=_SettingsStoreStub(),
        )
        client = app.test_client()

        response = client.post(
            "/download",
            json={
                "link": "https://open.spotify.com/track/123",
                "quality": "default",
                "format": "flac",
                "sourceUrl": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "output": "ignored",
                "playlistNumbering": True,
            },
        )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(len(downloads.started), 1)
        link, request = downloads.started[0]
        self.assertEqual(link, "https://open.spotify.com/track/123")
        self.assertEqual(request.format, "flac")
        self.assertEqual(request.bitrate, "192k")
        self.assertEqual(
            request.source_url,
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        )

    def test_status_route_returns_detail_and_phase(self) -> None:
        app = create_app(
            metadata_service=_MetadataStub(),
            download_service=_DownloadStub(),
            active_settings_store=_SettingsStoreStub(),
        )
        client = app.test_client()

        response = client.get("/status?links=https://open.spotify.com/track/123")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["https://open.spotify.com/track/123"]["phase"], "queued")
        self.assertEqual(payload["https://open.spotify.com/track/123"]["detail"], "Queued")


if __name__ == "__main__":
    unittest.main()
