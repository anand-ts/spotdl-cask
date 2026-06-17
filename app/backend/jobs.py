"""In-memory job store and queue supervisor for per-job worker subprocesses."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from app.backend.inputs import ensure_supported_single_track
from app.backend.metadata import MetadataService
from app.backend.os import reveal_in_file_manager
from app.backend.protocol import DownloadJobSpec
from app.backend.settings import DownloadRequest
from app.backend.workers import WorkerMonitor, WorkerOutcome, job_log_path

LOGGER = logging.getLogger(__name__)


@dataclass
class JobSnapshot:
    """Public per-link job state exposed through `/status`."""

    job_id: str
    link: str
    status: str = "idle"
    phase: str = "idle"
    detail: str = ""
    progress: float = 0.0
    progress_known: bool = False
    error_message: Optional[str] = None
    file_path: Optional[str] = None
    log_path: Optional[str] = None
    stderr_tail: tuple[str, ...] = ()
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


@dataclass
class _StoredJob:
    snapshot: JobSnapshot
    events: deque[str] = field(default_factory=lambda: deque(maxlen=20))


class JobStore:
    """Authoritative in-memory store for the latest job per link."""

    def __init__(self) -> None:
        self._jobs: dict[str, _StoredJob] = {}
        self._lock = threading.RLock()

    def _append_event(self, stored: _StoredJob, message: str) -> None:
        cleaned = str(message).strip()
        if cleaned:
            stored.events.append(cleaned)

    @staticmethod
    def _payload(snapshot: JobSnapshot) -> dict[str, object]:
        file_path = snapshot.file_path
        can_reveal = bool(file_path and Path(file_path).exists())
        return {
            "job_id": snapshot.job_id,
            "link": snapshot.link,
            "status": snapshot.status,
            "phase": snapshot.phase,
            "detail": snapshot.detail,
            "progress": snapshot.progress,
            "progress_known": snapshot.progress_known,
            "error_message": snapshot.error_message,
            "file_path": file_path,
            "can_reveal": can_reveal,
            "log_path": snapshot.log_path,
            "stderr_tail": list(snapshot.stderr_tail),
            "created_at": snapshot.created_at,
            "updated_at": snapshot.updated_at,
        }

    def snapshot(self, link: str) -> Optional[JobSnapshot]:
        with self._lock:
            stored = self._jobs.get(link)
            return None if stored is None else stored.snapshot

    def queue_job(self, link: str, job_id: str) -> None:
        with self._lock:
            snapshot = JobSnapshot(
                job_id=job_id,
                link=link,
                status="queued",
                phase="queued",
                detail="Queued",
                log_path=str(job_log_path(job_id)),
            )
            stored = _StoredJob(snapshot=snapshot)
            stored.events.append("Queued")
            self._jobs[link] = stored

    def mark_launching(self, link: str, job_id: str) -> None:
        with self._lock:
            stored = self._jobs.get(link)
            if stored is None or stored.snapshot.job_id != job_id:
                return
            snapshot = stored.snapshot
            snapshot.status = "downloading"
            snapshot.phase = "starting"
            snapshot.detail = "Launching worker"
            snapshot.updated_at = time.time()
            self._append_event(stored, snapshot.detail)

    def apply_worker_event(self, link: str, job_id: str, event: dict[str, object]) -> None:
        with self._lock:
            stored = self._jobs.get(link)
            if stored is None or stored.snapshot.job_id != job_id:
                return

            snapshot = stored.snapshot
            event_type = str(event.get("type") or "")
            detail = str(event.get("detail") or "").strip()

            if event_type == "phase":
                snapshot.status = "downloading"
                snapshot.phase = str(event.get("phase") or snapshot.phase or "starting")
                snapshot.detail = detail or snapshot.detail or snapshot.phase.title()
                snapshot.progress_known = False
            elif event_type == "progress":
                snapshot.status = "downloading"
                snapshot.phase = str(event.get("phase") or snapshot.phase or "downloading")
                snapshot.detail = detail or snapshot.detail or "Downloading"
                try:
                    snapshot.progress = float(event.get("progress") or 0.0)
                except (TypeError, ValueError):
                    snapshot.progress = 0.0
                snapshot.progress_known = bool(event.get("progress_known"))
            elif event_type == "log":
                self._append_event(stored, detail)

            snapshot.updated_at = time.time()
            if snapshot.detail:
                self._append_event(stored, snapshot.detail)

    def mark_done(
        self,
        link: str,
        job_id: str,
        file_path: str,
        *,
        log_path: Optional[str] = None,
        stderr_tail: tuple[str, ...] = (),
    ) -> None:
        with self._lock:
            stored = self._jobs.get(link)
            if stored is None or stored.snapshot.job_id != job_id:
                return
            snapshot = stored.snapshot
            snapshot.status = "done"
            snapshot.phase = "completed"
            snapshot.detail = "Completed"
            snapshot.progress = 100.0
            snapshot.progress_known = True
            snapshot.error_message = None
            snapshot.file_path = file_path
            snapshot.log_path = log_path or snapshot.log_path
            snapshot.stderr_tail = tuple(stderr_tail)
            snapshot.updated_at = time.time()
            self._append_event(stored, f"Completed: {file_path}")

    def mark_failed(
        self,
        link: str,
        job_id: str,
        message: str,
        *,
        log_path: Optional[str] = None,
        stderr_tail: tuple[str, ...] = (),
    ) -> None:
        with self._lock:
            stored = self._jobs.get(link)
            if stored is None or stored.snapshot.job_id != job_id:
                return
            snapshot = stored.snapshot
            snapshot.status = "error"
            snapshot.phase = "failed"
            snapshot.detail = message
            snapshot.error_message = message
            snapshot.log_path = log_path or snapshot.log_path
            snapshot.stderr_tail = tuple(stderr_tail)
            snapshot.progress_known = False
            snapshot.updated_at = time.time()
            self._append_event(stored, f"Failed: {message}")

    def mark_cancelled(self, link: str, job_id: str) -> None:
        with self._lock:
            stored = self._jobs.get(link)
            if stored is None or stored.snapshot.job_id != job_id:
                return
            snapshot = stored.snapshot
            snapshot.status = "idle"
            snapshot.phase = "idle"
            snapshot.detail = "Cancelled"
            snapshot.progress = 0.0
            snapshot.progress_known = False
            snapshot.error_message = None
            snapshot.file_path = None
            snapshot.updated_at = time.time()
            self._append_event(stored, "Cancelled")

    def status_payloads(self, links: list[str]) -> dict[str, dict[str, object]]:
        with self._lock:
            result: dict[str, dict[str, object]] = {}
            for link in links:
                stored = self._jobs.get(link)
                if stored is not None:
                    result[link] = self._payload(stored.snapshot)
            return result

    def reveal_path(self, link: str) -> Path:
        with self._lock:
            stored = self._jobs.get(link)
            if stored is None or not stored.snapshot.file_path:
                raise FileNotFoundError("This track has not finished downloading yet.")
            file_path = Path(stored.snapshot.file_path).expanduser().resolve()

        if not file_path.exists():
            raise FileNotFoundError(f"Downloaded file was not found: {file_path}")
        return file_path


@dataclass
class _QueueEntry:
    link: str
    job_id: str
    spec: DownloadJobSpec


@dataclass
class _ActiveExecution:
    job_id: str
    monitor: WorkerMonitor
    thread: threading.Thread
    cancel_requested: bool = False


class DownloadSupervisor:
    """Queue downloads, launch per-job workers, and expose current job state."""

    def __init__(
        self,
        metadata_service: MetadataService,
        *,
        concurrency_limit: int = 2,
        job_store: Optional[JobStore] = None,
        monitor_factory: Callable[[DownloadJobSpec], WorkerMonitor] = WorkerMonitor,
    ) -> None:
        self.metadata_service = metadata_service
        self.concurrency_limit = concurrency_limit
        self.job_store = job_store or JobStore()
        self.monitor_factory = monitor_factory
        self._queue: deque[_QueueEntry] = deque()
        self._active: dict[str, _ActiveExecution] = {}
        self._lock = threading.RLock()

    def start_download(self, link: str, request: DownloadRequest) -> None:
        """Queue a download request without blocking on provider resolution."""
        info = ensure_supported_single_track(link)
        song_payload = self.metadata_service.get_cached_song_payload(info.normalized)

        with self._lock:
            if link in self._active or any(entry.link == link for entry in self._queue):
                LOGGER.info("Download already active or queued for %s", link)
                return

            job_id = uuid.uuid4().hex
            spec = DownloadJobSpec(
                job_id=job_id,
                link=info.normalized,
                download_directory=str(request.download_directory),
                format=request.format,
                bitrate=request.bitrate,
                song_payload=song_payload,
                source_url=request.source_url,
            )
            self.job_store.queue_job(link, job_id)
            self._queue.append(_QueueEntry(link=link, job_id=job_id, spec=spec))
            LOGGER.info(
                "Queued download %s at position %s",
                link,
                len(self._active) + len(self._queue),
            )
            self._dispatch_locked()

    def _dispatch_locked(self) -> None:
        while len(self._active) < self.concurrency_limit and self._queue:
            entry = self._queue.popleft()
            self.job_store.mark_launching(entry.link, entry.job_id)
            monitor = self.monitor_factory(entry.spec)
            thread = threading.Thread(
                target=self._run_job,
                args=(entry.link, entry.job_id, monitor),
                daemon=True,
                name=f"download-{entry.job_id[:8]}",
            )
            self._active[entry.link] = _ActiveExecution(
                job_id=entry.job_id,
                monitor=monitor,
                thread=thread,
            )
            LOGGER.info("Starting download %s", entry.link)
            thread.start()

    def _run_job(self, link: str, job_id: str, monitor: WorkerMonitor) -> None:
        last_logged_detail: Optional[str] = None

        def handle_event(event: dict[str, object]) -> None:
            nonlocal last_logged_detail
            self.job_store.apply_worker_event(link, job_id, event)
            detail = str(event.get("detail") or "").strip()
            if detail and detail != last_logged_detail:
                LOGGER.info("%s: %s", link, detail)
                last_logged_detail = detail

        try:
            outcome = monitor.run(handle_event)
        except Exception as exc:
            LOGGER.exception("Worker monitor crashed for %s", link)
            outcome = WorkerOutcome(success=False, error_message=str(exc))

        with self._lock:
            active = self._active.get(link)
            cancel_requested = bool(
                active is not None
                and active.job_id == job_id
                and active.cancel_requested
            )
            self._active.pop(link, None)

            if cancel_requested:
                self.job_store.mark_cancelled(link, job_id)
                LOGGER.info("Cancelled download %s", link)
            elif outcome.success and outcome.file_path:
                self.job_store.mark_done(
                    link,
                    job_id,
                    outcome.file_path,
                    log_path=outcome.log_path,
                    stderr_tail=outcome.stderr_tail,
                )
                LOGGER.info("Completed download %s", link)
            else:
                error_message = outcome.error_message or "Download failed."
                self.job_store.mark_failed(
                    link,
                    job_id,
                    error_message,
                    log_path=outcome.log_path,
                    stderr_tail=outcome.stderr_tail,
                )
                LOGGER.warning("Download failed for %s: %s", link, error_message)

            self._dispatch_locked()

    def cancel_download(self, link: str) -> bool:
        """Cancel a queued or active download."""
        with self._lock:
            for entry in list(self._queue):
                if entry.link != link:
                    continue
                self._queue.remove(entry)
                self.job_store.mark_cancelled(link, entry.job_id)
                LOGGER.info("Cancelled queued download %s", link)
                return True

            active = self._active.get(link)
            if active is None:
                return False
            active.cancel_requested = True
            job_id = active.job_id
            monitor = active.monitor

        self.job_store.mark_cancelled(link, job_id)
        monitor.terminate("Cancelled by user.")
        return True

    def get_status(self, links: list[str]) -> dict[str, dict[str, object]]:
        """Return status snapshots for the requested links."""
        return self.job_store.status_payloads(links)

    def reveal_downloaded_file(self, link: str) -> Path:
        """Reveal the completed file for a given row."""
        file_path = self.job_store.reveal_path(link)
        reveal_in_file_manager(file_path)
        return file_path

    def shutdown(self) -> None:
        """Terminate any active worker processes during app shutdown."""
        with self._lock:
            active_jobs = list(self._active.values())

        for active in active_jobs:
            active.cancel_requested = True
            active.monitor.terminate("Application shutdown.")
