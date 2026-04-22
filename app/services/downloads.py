"""Lean serial download orchestration for the Flask app."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any, Optional

from config import DEFAULT_DOWNLOAD_DIR, QUALITY_OPTIONS

LOGGER = logging.getLogger(__name__)

DEBUG_OUTPUT = os.getenv("SPOTDL_DEBUG", "").lower() in {"1", "true", "yes", "on"}
MUSIC_EXTENSIONS = (".mp3", ".flac", ".m4a", ".opus", ".ogg", ".wav")
STAGING_ROOT_DIRNAME = ".spotdl-cask-staging"
ALLOWED_AUDIO_PROVIDERS = (
    "youtube",
    "youtube-music",
    "soundcloud",
    "bandcamp",
    "piped",
)
DEFAULT_AUDIO_PROVIDERS = ("youtube", "piped")
AUDIO_PROVIDER_ENV_VARS = ("SPOTDL_AUDIO_PROVIDERS", "SPOTDL_AUDIO_PROVIDER")


@dataclass
class DownloadJob:
    """Small per-link state object tracked by the download service."""

    status: str = "idle"
    progress: float = 0.0
    progress_known: bool = False
    error_message: Optional[str] = None
    file_path: Optional[Path] = None
    cancel_requested: bool = False


@dataclass
class AttemptResult:
    """Outcome of one concrete provider attempt."""

    succeeded: bool = False
    cancelled: bool = False
    failure_message: str = "Download failed."
    file_path: Optional[Path] = None


class ErrorMessageFormatter:
    """Convert raw spotDL output into compact user-facing failures."""

    ERROR_PREFIXES = (
        "downloadererror:",
        "audioprovidererror:",
        "spotifyerror:",
        "ffmpegerror:",
        "metadataerror:",
        "indexerror:",
        "jsondecodeerror:",
        "keyerror:",
        "lookuperror:",
    )

    @staticmethod
    def is_rate_limited_output(line: str) -> bool:
        lower_line = line.lower()
        return (
            "rate/request limit" in lower_line
            or "retry will occur after:" in lower_line
            or "http status: 429" in lower_line
        )

    @classmethod
    def is_explicit_error_output(cls, line: str) -> bool:
        stripped = line.strip().strip("│").strip()
        lower_line = stripped.lower()
        return (
            cls.is_rate_limited_output(line)
            or "you are blocked by youtube music" in lower_line
            or any(lower_line.startswith(prefix) for prefix in cls.ERROR_PREFIXES)
        )

    @classmethod
    def format_error_message(cls, line: Optional[str]) -> str:
        if not line:
            return "Download failed."

        stripped = line.strip().strip("│").strip()
        lower_line = stripped.lower()

        if cls.is_rate_limited_output(stripped):
            retry_match = re.search(r"after:\s*(\d+)\s*s", stripped, re.IGNORECASE)
            if retry_match:
                return (
                    "Spotify API rate limited this download. "
                    f"Retry after about {retry_match.group(1)} seconds."
                )
            return "Spotify API rate limited this download."

        if "you are blocked by youtube music" in lower_line:
            return (
                "This network is blocking YouTube Music. "
                "The default automatic chain uses YouTube first and Piped second, "
                "or you can explicitly configure youtube-music if your network allows it."
            )

        for prefix in (
            "downloadererror:",
            "audioprovidererror:",
            "spotifyerror:",
            "ffmpegerror:",
            "metadataerror:",
            "lookuperror:",
        ):
            if lower_line.startswith(prefix):
                message = stripped.split(":", 1)[1].strip()
                return message or "Download failed."

        if lower_line.startswith("jsondecodeerror:"):
            return "The selected audio provider returned invalid data while resolving the stream."

        if lower_line.startswith("keyerror: 'webcommandmetadata'"):
            return (
                "The selected audio provider returned incomplete stream metadata "
                "while resolving the track."
            )

        return stripped or "Download failed."

    @classmethod
    def missing_output_message(
        cls, download_dir: Path, last_output_line: Optional[str]
    ) -> str:
        base_message = (
            f"spotDL exited without creating an audio file in {download_dir}."
        )
        if not last_output_line:
            return base_message

        formatted_output = cls.format_error_message(last_output_line)
        if formatted_output == "Download failed.":
            return base_message

        return f"{formatted_output} {base_message}"

class ProgressParser:
    """Extract real progress percentages from spotDL output."""

    PROGRESS_PATTERNS = (
        r"(\d+(?:\.\d+)?)%",
        r"\[download\]\s*(\d+(?:\.\d+)?)%",
        r"Downloaded\s*(\d+(?:\.\d+)?)%",
        r"Progress:\s*(\d+(?:\.\d+)?)%",
        r"▰+▱*\s*(\d+(?:\.\d+)?)%",
        r"(\d+(?:\.\d+)?)%\s*complete",
        r"(\d+(?:\.\d+)?)%\s*done",
        r"(\d+(?:\.\d+)?)%\s*of",
    )

    def __init__(self, *, debug_output: bool = DEBUG_OUTPUT) -> None:
        self.debug_output = debug_output

    def parse(self, line: str) -> Optional[float]:
        if self.debug_output:
            print(f"DEBUG - Raw line: '{line}'")

        for pattern in self.PROGRESS_PATTERNS:
            match = re.search(pattern, line)
            if not match:
                continue
            try:
                return float(match.group(1))
            except (TypeError, ValueError, IndexError):
                continue

        if self.debug_output and any(
            keyword in line.lower()
            for keyword in (
                "download",
                "processing",
                "converting",
                "complete",
                "done",
                "finished",
            )
        ):
            print(f"DEBUG - Download-related line (no percentage): '{line}'")

        return None


class SpotdlCommandBuilder:
    """Translate UI settings into one explicit spotDL invocation."""

    @staticmethod
    def _spotdl_base_command() -> list[str]:
        return [sys.executable, "-m", "spotdl"]

    @staticmethod
    def _normalize_audio_providers(raw_value: Any) -> list[str]:
        if raw_value is None:
            return []

        if isinstance(raw_value, str):
            candidates = re.split(r"[\s,]+", raw_value)
        elif isinstance(raw_value, (list, tuple, set)):
            candidates = [str(item).strip() for item in raw_value]
        else:
            return []

        providers: list[str] = []
        for candidate in candidates:
            provider = str(candidate).strip()
            if provider not in ALLOWED_AUDIO_PROVIDERS or provider in providers:
                continue
            providers.append(provider)
        return providers

    @classmethod
    def resolve_audio_providers(cls, settings: dict[str, Any]) -> list[str]:
        configured_providers = cls._normalize_audio_providers(
            settings.get("audioProviders") or settings.get("audio_providers")
        )
        if configured_providers:
            return configured_providers

        for env_var in AUDIO_PROVIDER_ENV_VARS:
            configured_providers = cls._normalize_audio_providers(os.getenv(env_var))
            if configured_providers:
                return configured_providers

        return list(DEFAULT_AUDIO_PROVIDERS)

    def build(
        self,
        link: str,
        settings: dict[str, Any],
        *,
        provider: str,
        download_dir: Path,
    ) -> list[str]:
        output_template = str(
            settings.get("output", "{artists} - {title}.{output-ext}")
        )
        cmd = [
            *self._spotdl_base_command(),
            "download",
            link,
            "--max-retries",
            "0",
            "--output",
            f"{download_dir}/{output_template}",
            "--audio",
            provider,
        ]

        quality = str(settings.get("quality", "best"))
        bitrate = QUALITY_OPTIONS.get(quality)
        if bitrate is not None:
            cmd.extend(["--bitrate", bitrate])

        format_type = str(settings.get("format", "mp3"))
        if format_type != "mp3":
            cmd.extend(["--format", format_type])

        if settings.get("playlistNumbering"):
            cmd.append("--playlist-numbering")
        if settings.get("skipExplicit"):
            cmd.append("--skip-explicit")
        if settings.get("generateLrc"):
            cmd.append("--generate-lrc")
        return cmd


class DownloadService:
    """Serial download queue with explicit per-link job state."""

    def __init__(self) -> None:
        self.jobs: dict[str, DownloadJob] = {}
        self.queue: deque[tuple[str, dict[str, Any]]] = deque()
        self.active_link: Optional[str] = None
        self.active_process: Optional[subprocess.Popen[str]] = None
        self._worker_thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()
        self.command_builder = SpotdlCommandBuilder()
        self.progress_parser = ProgressParser(debug_output=DEBUG_OUTPUT)

    def _get_or_create_job(self, link: str) -> DownloadJob:
        job = self.jobs.get(link)
        if job is None:
            job = DownloadJob()
            self.jobs[link] = job
        return job

    @staticmethod
    def _reset_job(job: DownloadJob) -> None:
        job.status = "idle"
        job.progress = 0.0
        job.progress_known = False
        job.error_message = None
        job.file_path = None
        job.cancel_requested = False

    def _is_cancelled(self, link: str) -> bool:
        with self._lock:
            job = self.jobs.get(link)
            return bool(job and job.cancel_requested)

    def _update_progress(self, link: str, progress: float) -> None:
        with self._lock:
            job = self._get_or_create_job(link)
            if progress <= job.progress:
                return
            job.progress = progress
            job.progress_known = True

        if DEBUG_OUTPUT:
            print(f"DEBUG - Progress change for {link}: {progress:.1f}%")

    def _mark_done(self, link: str, file_path: Optional[Path]) -> None:
        with self._lock:
            job = self._get_or_create_job(link)
            job.status = "done"
            job.progress = 100.0
            job.progress_known = True
            job.error_message = None
            job.file_path = file_path
            job.cancel_requested = False

    def get_status(self, links: list[str]) -> dict[str, dict[str, Any]]:
        """Return status payloads for the requested links."""
        result: dict[str, dict[str, Any]] = {}
        with self._lock:
            for link in links:
                job = self.jobs.get(link)
                if job is None:
                    result[link] = {
                        "status": "idle",
                        "progress": 0.0,
                        "progress_known": False,
                        "can_reveal": False,
                    }
                    continue

                if job.status == "done" and (
                    job.file_path is None or not job.file_path.exists()
                ):
                    self._reset_job(job)

                can_reveal = (
                    job.status == "done"
                    and job.file_path is not None
                    and job.file_path.exists()
                )
                payload = {
                    "status": job.status,
                    "progress": 100.0 if job.status == "done" else job.progress,
                    "progress_known": True if job.status == "done" else job.progress_known,
                    "can_reveal": can_reveal,
                }
                if job.status == "error" and job.error_message:
                    payload["error_message"] = job.error_message
                result[link] = payload

        return result

    def start_download(self, link: str, settings: dict[str, Any]) -> bool:
        """Queue a download request and start the single worker if needed."""
        with self._lock:
            job = self._get_or_create_job(link)
            if job.status in {"queued", "downloading", "done"}:
                return False

            job.status = "queued"
            job.progress = 0.0
            job.progress_known = False
            job.error_message = None
            job.file_path = None
            job.cancel_requested = False
            self.queue.append((link, dict(settings)))
            self._ensure_worker_locked()
        return True

    def cancel_download(self, link: str) -> bool:
        """Cancel a queued or active download."""
        with self._lock:
            job = self.jobs.get(link)
            if job is None or job.status not in {"queued", "downloading"}:
                return False

            if job.status == "queued":
                self.queue = deque(
                    (queued_link, settings)
                    for queued_link, settings in self.queue
                    if queued_link != link
                )
                self._reset_job(job)
                return True

            job.cancel_requested = True
            job.status = "idle"
            job.progress = 0.0
            job.progress_known = False
            job.error_message = None
            job.file_path = None
            proc = self.active_process if self.active_link == link else None

        if proc is not None:
            self._terminate_process(proc)

        return True

    def reveal_downloaded_file(self, link: str) -> Path:
        """Reveal a finished file in Finder/File Explorer."""
        with self._lock:
            job = self.jobs.get(link)
            file_path = job.file_path if job else None

        if file_path is None or not file_path.exists():
            raise FileNotFoundError("Downloaded file could not be found.")

        if sys.platform == "darwin":
            command = ["open", "-R", str(file_path)]
        elif sys.platform == "win32":
            command = ["explorer", "/select,", str(file_path)]
        else:
            command = ["xdg-open", str(file_path.parent)]

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            details = (result.stderr or result.stdout or "").strip()
            if details:
                raise RuntimeError(f"Could not reveal downloaded file: {details}")
            raise RuntimeError("Could not reveal downloaded file.")

        return file_path

    def _ensure_worker_locked(self) -> None:
        if self._worker_thread is not None and self._worker_thread.is_alive():
            return

        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            daemon=True,
            name="spotdl-download-worker",
        )
        self._worker_thread.start()

    def _worker_loop(self) -> None:
        while True:
            with self._lock:
                if not self.queue:
                    self._worker_thread = None
                    return

                link, settings = self.queue.popleft()
                job = self._get_or_create_job(link)
                if job.cancel_requested:
                    self._reset_job(job)
                    continue

                self.active_link = link
                self.active_process = None
                job.status = "downloading"
                job.progress = 0.0
                job.progress_known = False
                job.error_message = None

            try:
                self._run_job(link, settings)
            finally:
                with self._lock:
                    self.active_link = None
                    self.active_process = None

    def _run_job(self, link: str, settings: dict[str, Any]) -> None:
        download_dir = Path(
            str(settings.get("_download_directory") or DEFAULT_DOWNLOAD_DIR)
        ).expanduser().resolve()
        download_dir.mkdir(parents=True, exist_ok=True)

        providers = self.command_builder.resolve_audio_providers(settings)
        last_result = AttemptResult(failure_message="Download failed.")
        for provider in providers:
            if self._is_cancelled(link):
                return

            result = self._run_attempt(
                link,
                settings,
                provider=provider,
                download_dir=download_dir,
            )
            last_result = result

            if result.cancelled:
                return

            if result.succeeded:
                self._mark_done(link, result.file_path)
                if DEBUG_OUTPUT:
                    print(f"Successfully downloaded: {link}")
                return

            if ErrorMessageFormatter.is_rate_limited_output(result.failure_message):
                break

        with self._lock:
            job = self._get_or_create_job(link)
            if job.cancel_requested or job.status == "idle":
                job.cancel_requested = False
                return

            job.status = "error"
            job.progress = 0.0
            job.progress_known = False
            job.error_message = last_result.failure_message
            job.file_path = None
            job.cancel_requested = False

        if DEBUG_OUTPUT:
            print(f"Download failed for {link}: {last_result.failure_message}")

    def _run_attempt(
        self,
        link: str,
        settings: dict[str, Any],
        *,
        provider: str,
        download_dir: Path,
    ) -> AttemptResult:
        if self._is_cancelled(link):
            return AttemptResult(cancelled=True)

        staging_dir = self._create_staging_directory(download_dir)
        last_output_line: Optional[str] = None
        last_error_line: Optional[str] = None
        detected_output_path: Optional[Path] = None
        lines_seen = 0

        try:
            cmd = self.command_builder.build(
                link,
                settings,
                provider=provider,
                download_dir=staging_dir,
            )
            if DEBUG_OUTPUT:
                print(f"DEBUG - Running command ({provider}): {' '.join(cmd)}")

            preexec_fn = os.setsid if sys.platform != "win32" else None
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                universal_newlines=True,
                bufsize=1,
                preexec_fn=preexec_fn,
            )
            with self._lock:
                if self.active_link == link:
                    self.active_process = proc

            if proc.stdout:
                for raw_line in proc.stdout:
                    line = raw_line.strip()
                    if not line:
                        continue

                    lines_seen += 1
                    last_output_line = line
                    if ErrorMessageFormatter.is_explicit_error_output(line):
                        last_error_line = line
                    extracted_path = self._extract_output_path_from_line(line, staging_dir)
                    if extracted_path is not None:
                        detected_output_path = extracted_path
                    if DEBUG_OUTPUT:
                        print(f"SpotDL output (line {lines_seen}): {line}")

                    progress = self.progress_parser.parse(line)
                    if progress is not None:
                        self._update_progress(link, progress)

                    if self._is_cancelled(link):
                        self._terminate_process(proc)
                        proc.wait(timeout=5)
                        return AttemptResult(cancelled=True)

            proc.wait()
            if self._is_cancelled(link):
                return AttemptResult(cancelled=True)

            if DEBUG_OUTPUT:
                print(f"DEBUG - Process completed with return code: {proc.returncode}")
                print(f"DEBUG - Total lines seen: {lines_seen}")

            if proc.returncode != 0:
                failure_message = ErrorMessageFormatter.format_error_message(
                    last_error_line or last_output_line
                )
                if last_output_line is None:
                    failure_message = (
                        f"Download subprocess exited with code {proc.returncode} "
                        "without any output."
                    )
                return AttemptResult(failure_message=failure_message)

            audio_file = self._find_staged_audio_file(staging_dir, detected_output_path)
            if audio_file is None:
                failure_message = ErrorMessageFormatter.missing_output_message(
                    download_dir,
                    last_error_line or last_output_line,
                )
                return AttemptResult(failure_message=failure_message)

            finalized_path = self._finalize_staged_download(
                staging_dir,
                audio_file,
                download_dir,
            )
            return AttemptResult(succeeded=True, file_path=finalized_path)
        except Exception as exc:
            if self._is_cancelled(link):
                return AttemptResult(cancelled=True)

            LOGGER.exception("Download attempt error for %s", link)
            failure_message = ErrorMessageFormatter.format_error_message(str(exc))
            return AttemptResult(failure_message=failure_message)
        finally:
            with self._lock:
                if self.active_link == link:
                    self.active_process = None
            self._cleanup_staging_directory(staging_dir)

    @staticmethod
    def _create_staging_directory(download_dir: Path) -> Path:
        staging_root = download_dir / STAGING_ROOT_DIRNAME
        staging_root.mkdir(parents=True, exist_ok=True)
        return Path(tempfile.mkdtemp(prefix="download-", dir=str(staging_root)))

    @staticmethod
    def _cleanup_staging_directory(staging_dir: Path) -> None:
        shutil.rmtree(staging_dir, ignore_errors=True)
        staging_root = staging_dir.parent
        if staging_root.name != STAGING_ROOT_DIRNAME:
            return
        try:
            staging_root.rmdir()
        except OSError:
            pass

    @staticmethod
    def _extract_output_path_from_line(line: str, staging_dir: Path) -> Optional[Path]:
        cleaned_line = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", line)
        extension_pattern = "|".join(re.escape(ext) for ext in MUSIC_EXTENSIONS)
        path_pattern = re.compile(
            rf"({re.escape(str(staging_dir))}.*?(?:{extension_pattern}))",
            re.IGNORECASE,
        )
        match = path_pattern.search(cleaned_line)
        if match is None:
            return None
        return Path(match.group(1).strip().strip("'\""))

    @staticmethod
    def _find_staged_audio_file(
        staging_dir: Path, detected_output_path: Optional[Path]
    ) -> Optional[Path]:
        if detected_output_path is not None and detected_output_path.exists():
            return detected_output_path

        candidates: list[Path] = []
        for ext in MUSIC_EXTENSIONS:
            candidates.extend(path for path in staging_dir.rglob(f"*{ext}") if path.is_file())

        if not candidates:
            return None

        return max(candidates, key=lambda path: path.stat().st_mtime)

    @staticmethod
    def _move_file_to_destination(source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if destination.is_dir():
                shutil.rmtree(destination)
            else:
                destination.unlink()
        shutil.move(str(source), str(destination))

    def _finalize_staged_download(
        self, staging_dir: Path, audio_file: Path, download_dir: Path
    ) -> Path:
        relative_audio_path = audio_file.relative_to(staging_dir)
        moved_audio_path: Optional[Path] = None

        staged_files = sorted(
            (path for path in staging_dir.rglob("*") if path.is_file()),
            key=lambda path: str(path.relative_to(staging_dir)),
        )
        for source_path in staged_files:
            relative_path = source_path.relative_to(staging_dir)
            destination_path = download_dir / relative_path
            self._move_file_to_destination(source_path, destination_path)
            if relative_path == relative_audio_path:
                moved_audio_path = destination_path.resolve()

        if moved_audio_path is None:
            raise FileNotFoundError("Downloaded audio file could not be finalized.")

        return moved_audio_path

    @staticmethod
    def _terminate_process(proc: subprocess.Popen[str]) -> None:
        try:
            if sys.platform != "win32":
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            else:
                proc.terminate()
        except ProcessLookupError:
            return
        except PermissionError:
            return
        except Exception:
            try:
                proc.kill()
            except Exception:
                return
