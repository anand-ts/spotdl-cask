from __future__ import annotations

import threading
import time
import unittest
from pathlib import Path

from app.backend.jobs import DownloadSupervisor
from app.backend.settings import DownloadRequest
from app.backend.workers import WorkerOutcome


class _MetadataStub:
    def get_cached_song_payload(self, _link: str):
        return None


class _BlockingMonitor:
    def __init__(self, spec, gate: threading.Event) -> None:
        self.spec = spec
        self._gate = gate
        self._terminated = False

    def run(self, on_event):
        on_event(
            {
                "type": "phase",
                "phase": "resolving",
                "detail": f"Running {self.spec.link}",
            }
        )
        self._gate.wait(timeout=2.0)
        if self._terminated:
            return WorkerOutcome(success=False, error_message="Cancelled")
        return WorkerOutcome(
            success=True,
            file_path=f"/tmp/{self.spec.job_id}.mp3",
        )

    def terminate(self, _reason=None) -> None:
        self._terminated = True
        self._gate.set()


class DownloadSupervisorTests(unittest.TestCase):
    def _request(self) -> DownloadRequest:
        return DownloadRequest(
            download_directory=Path("/tmp/music"),
            quality="best",
            format="mp3",
            bitrate="auto",
        )

    def test_queue_respects_two_active_jobs(self) -> None:
        gate = threading.Event()

        def factory(spec):
            return _BlockingMonitor(spec, gate)

        supervisor = DownloadSupervisor(
            _MetadataStub(),
            concurrency_limit=2,
            monitor_factory=factory,
        )
        supervisor.start_download("https://open.spotify.com/track/one", self._request())
        supervisor.start_download("https://open.spotify.com/track/two", self._request())
        supervisor.start_download("https://open.spotify.com/track/three", self._request())
        time.sleep(0.2)

        self.assertEqual(len(supervisor._active), 2)  # noqa: SLF001
        self.assertEqual(len(supervisor._queue), 1)  # noqa: SLF001
        queued = supervisor.get_status(["https://open.spotify.com/track/three"])
        self.assertEqual(queued["https://open.spotify.com/track/three"]["status"], "queued")
        self.assertTrue(queued["https://open.spotify.com/track/three"]["log_path"].endswith(".log"))
        self.assertEqual(queued["https://open.spotify.com/track/three"]["stderr_tail"], [])

        gate.set()
        time.sleep(0.3)
        statuses = supervisor.get_status(
            [
                "https://open.spotify.com/track/one",
                "https://open.spotify.com/track/two",
                "https://open.spotify.com/track/three",
            ]
        )
        self.assertEqual(statuses["https://open.spotify.com/track/one"]["status"], "done")
        self.assertEqual(statuses["https://open.spotify.com/track/two"]["status"], "done")

    def test_cancel_queued_job_returns_to_idle(self) -> None:
        gate = threading.Event()

        def factory(spec):
            return _BlockingMonitor(spec, gate)

        supervisor = DownloadSupervisor(
            _MetadataStub(),
            concurrency_limit=1,
            monitor_factory=factory,
        )
        first = "https://open.spotify.com/track/first"
        second = "https://open.spotify.com/track/second"
        supervisor.start_download(first, self._request())
        supervisor.start_download(second, self._request())
        time.sleep(0.1)

        self.assertTrue(supervisor.cancel_download(second))
        status = supervisor.get_status([second])[second]
        self.assertEqual(status["status"], "idle")
        self.assertEqual(status["detail"], "Cancelled")
        gate.set()


if __name__ == "__main__":
    unittest.main()
