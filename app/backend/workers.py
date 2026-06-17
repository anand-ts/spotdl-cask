"""Parent-side worker monitoring for per-job subprocess downloads."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from queue import Empty, Queue
from typing import Callable, Optional

from app.backend.protocol import DownloadJobSpec
from config import SETTINGS_DIR

LOGGER = logging.getLogger(__name__)
DEBUG_OUTPUT = os.getenv("SPOTDL_DEBUG", "").strip() == "1"
DOWNLOAD_IDLE_TIMEOUT = max(5, int(os.getenv("SPOTDL_IDLE_TIMEOUT", "60")))
DOWNLOAD_HARD_TIMEOUT = max(
    DOWNLOAD_IDLE_TIMEOUT,
    int(os.getenv("SPOTDL_HARD_TIMEOUT", "900")),
)
JOB_LOG_DIR = SETTINGS_DIR / "logs"


class WorkerProtocolError(RuntimeError):
    """Raised when a worker emits malformed protocol data."""


@dataclass(frozen=True)
class WorkerOutcome:
    """Final result of a monitored worker subprocess."""

    success: bool
    error_message: Optional[str] = None
    file_path: Optional[str] = None
    stderr_tail: tuple[str, ...] = ()
    log_path: Optional[str] = None


def job_log_path(job_id: str) -> Path:
    """Return the persistent log path for one download job."""
    return JOB_LOG_DIR / f"{job_id}.log"


def parse_worker_event(raw_line: str) -> dict[str, object]:
    """Parse one JSON-lines worker event."""
    try:
        payload = json.loads(raw_line)
    except json.JSONDecodeError as exc:
        raise WorkerProtocolError(f"invalid JSON: {raw_line!r}") from exc

    if not isinstance(payload, dict):
        raise WorkerProtocolError("worker event must be a JSON object")

    event_type = payload.get("type")
    if not isinstance(event_type, str) or not event_type:
        raise WorkerProtocolError("worker event is missing a string 'type'")

    return payload


@dataclass
class WorkerMonitor:
    """Spawn and observe a single download worker subprocess."""

    spec: DownloadJobSpec
    idle_timeout: int = DOWNLOAD_IDLE_TIMEOUT
    hard_timeout: int = DOWNLOAD_HARD_TIMEOUT
    _process: Optional[subprocess.Popen[str]] = field(default=None, init=False)
    _stderr_tail: deque[str] = field(default_factory=lambda: deque(maxlen=40), init=False)
    _termination_reason: Optional[str] = field(default=None, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    _log_path: Optional[Path] = field(default=None, init=False)

    def _command(self) -> list[str]:
        return [sys.executable, "-m", "app.backend.download_worker"]

    @staticmethod
    def _pump_stream(stream, sink: Queue[str]) -> None:
        try:
            for line in iter(stream.readline, ""):
                sink.put(line.rstrip("\n"))
        finally:
            stream.close()

    def terminate(self, reason: Optional[str] = None) -> None:
        """Terminate the worker process, escalating to kill if it lingers."""
        with self._lock:
            self._termination_reason = reason or "Worker terminated."
            process = self._process

        if process is None or process.poll() is not None:
            return

        process.terminate()
        deadline = time.monotonic() + 2.0
        while process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)

        if process.poll() is None:
            process.kill()

    def run(self, on_event: Callable[[dict[str, object]], None]) -> WorkerOutcome:
        """Run the worker subprocess until completion, failure, or timeout."""
        stdout_queue: Queue[str] = Queue()
        stderr_queue: Queue[str] = Queue()
        self._log_path = job_log_path(self.spec.job_id)
        self._log_path.parent.mkdir(parents=True, exist_ok=True)

        def log_line(kind: str, message: str) -> None:
            timestamp = datetime.now(timezone.utc).isoformat()
            with self._log_path.open("a", encoding="utf-8") as log_file:
                log_file.write(f"{timestamp} {kind} {message}\n")

        log_line("JOB", f"link={self.spec.link}")
        if self.spec.source_url:
            log_line("JOB", f"source_url={self.spec.source_url}")

        process = subprocess.Popen(
            self._command(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        with self._lock:
            self._process = process

        assert process.stdin is not None
        assert process.stdout is not None
        assert process.stderr is not None

        process.stdin.write(json.dumps(self.spec.to_payload(), ensure_ascii=True))
        process.stdin.close()

        stdout_thread = threading.Thread(
            target=self._pump_stream,
            args=(process.stdout, stdout_queue),
            daemon=True,
            name=f"worker-stdout-{self.spec.job_id[:8]}",
        )
        stderr_thread = threading.Thread(
            target=self._pump_stream,
            args=(process.stderr, stderr_queue),
            daemon=True,
            name=f"worker-stderr-{self.spec.job_id[:8]}",
        )
        stdout_thread.start()
        stderr_thread.start()

        started_at = time.monotonic()
        last_output_at = started_at
        final_event: Optional[dict[str, object]] = None

        while True:
            had_output = False

            while True:
                try:
                    line = stdout_queue.get_nowait()
                except Empty:
                    break
                had_output = True
                last_output_at = time.monotonic()
                if not line:
                    continue
                log_line("STDOUT", line)
                try:
                    event = parse_worker_event(line)
                except WorkerProtocolError as exc:
                    self._stderr_tail.append(str(exc))
                    log_line("PARSE_ERROR", str(exc))
                    continue

                on_event(event)
                if event["type"] in {"completed", "failed"}:
                    final_event = event

            while True:
                try:
                    line = stderr_queue.get_nowait()
                except Empty:
                    break
                had_output = True
                last_output_at = time.monotonic()
                if line:
                    self._stderr_tail.append(line)
                    log_line("STDERR", line)
                    if DEBUG_OUTPUT:
                        LOGGER.info("[worker %s stderr] %s", self.spec.job_id[:8], line)

            return_code = process.poll()
            if return_code is not None and stdout_queue.empty() and stderr_queue.empty():
                break

            now = time.monotonic()
            if return_code is None and self.hard_timeout and (now - started_at) > self.hard_timeout:
                self.terminate(
                    f"spotDL exceeded the hard timeout of {self.hard_timeout} seconds."
                )
                return WorkerOutcome(
                    success=False,
                    error_message=f"spotDL exceeded the hard timeout of {self.hard_timeout} seconds.",
                    stderr_tail=tuple(self._stderr_tail),
                    log_path=str(self._log_path),
                )

            if return_code is None and self.idle_timeout and (now - last_output_at) > self.idle_timeout:
                self.terminate(
                    f"spotDL produced no output for {self.idle_timeout} seconds."
                )
                return WorkerOutcome(
                    success=False,
                    error_message=f"spotDL produced no output for {self.idle_timeout} seconds.",
                    stderr_tail=tuple(self._stderr_tail),
                    log_path=str(self._log_path),
                )

            if not had_output:
                time.sleep(0.05)

        stdout_thread.join(timeout=0.5)
        stderr_thread.join(timeout=0.5)

        if final_event and final_event["type"] == "completed":
            file_path = final_event.get("file_path")
            return WorkerOutcome(
                success=True,
                file_path=str(file_path) if file_path else None,
                stderr_tail=tuple(self._stderr_tail),
                log_path=str(self._log_path),
            )

        if final_event and final_event["type"] == "failed":
            error_message = final_event.get("error")
            return WorkerOutcome(
                success=False,
                error_message=str(error_message) if error_message else "Download failed.",
                stderr_tail=tuple(self._stderr_tail),
                log_path=str(self._log_path),
            )

        if process.returncode == 0:
            return WorkerOutcome(
                success=False,
                error_message="Worker exited without reporting a final result.",
                stderr_tail=tuple(self._stderr_tail),
                log_path=str(self._log_path),
            )

        error_message = self._termination_reason or f"Worker exited with code {process.returncode}."
        if self._stderr_tail:
            error_message = f"{error_message} {' | '.join(self._stderr_tail)}"

        return WorkerOutcome(
            success=False,
            error_message=error_message,
            stderr_tail=tuple(self._stderr_tail),
            log_path=str(self._log_path),
        )
