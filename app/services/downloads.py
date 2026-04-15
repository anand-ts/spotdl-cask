"""Download orchestration services and helpers."""

from __future__ import annotations

import logging
import os
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

from config import DEFAULT_DOWNLOAD_DIR, QUALITY_OPTIONS, get_download_dir

DEBUG_OUTPUT = True
MUSIC_EXTENSIONS = (".mp3", ".flac", ".m4a", ".opus", ".ogg", ".wav")
PRESTART_CANCEL_WINDOW_SECONDS = 1.0
ALLOWED_AUDIO_PROVIDERS = (
    "youtube",
    "youtube-music",
    "soundcloud",
    "bandcamp",
    "piped",
)
DEFAULT_AUDIO_PROVIDERS = ("youtube", "piped")
AUDIO_PROVIDER_ENV_VARS = ("SPOTDL_AUDIO_PROVIDERS", "SPOTDL_AUDIO_PROVIDER")
SAFE_FALLBACK_OUTPUT_TEMPLATE = "{title}.{output-ext}"
TITLE_ONLY_SEARCH_QUERY = "{title}"
LOGGER = logging.getLogger(__name__)


class ErrorMessageFormatter:
    """Convert raw process output into user-facing messages."""

    @staticmethod
    def is_rate_limited_output(line: str) -> bool:
        """Detect spotDL/Spotify rate-limit output lines."""
        lower_line = line.lower()
        return (
            "rate/request limit" in lower_line
            or "retry will occur after:" in lower_line
            or "http status: 429" in lower_line
        )

    @classmethod
    def format_error_message(cls, line: Optional[str]) -> str:
        """Convert raw process output into a friendlier UI message."""
        if not line:
            return "Download failed."

        stripped_line = line.strip().strip("│").strip()
        lower_line = stripped_line.lower()

        if cls.is_rate_limited_output(line):
            retry_match = re.search(r"after:\s*(\d+)\s*s", line, re.IGNORECASE)
            if retry_match:
                retry_after = retry_match.group(1)
                return (
                    "Spotify API rate limited this download. "
                    f"Retry after about {retry_after} seconds, or update your spotDL Spotify credentials."
                )
            return (
                "Spotify API rate limited this download. "
                "Wait for the quota reset or update your spotDL Spotify credentials."
            )

        if "you are blocked by youtube music" in lower_line:
            return (
                "This network is blocking the default YouTube Music source. "
                "The app now falls back to Piped and YouTube automatically. "
                "If downloads still fail, try a VPN or set SPOTDL_AUDIO_PROVIDERS "
                "to a custom provider order."
            )

        for error_prefix in (
            "downloadererror:",
            "audioprovidererror:",
            "spotifyerror:",
            "ffmpegerror:",
            "metadataerror:",
        ):
            if lower_line.startswith(error_prefix):
                message = stripped_line.split(":", 1)[1].strip()
                if (
                    error_prefix == "ffmpegerror:"
                    and "not installed" in message.lower()
                ):
                    return (
                        "FFmpeg could not be found by the app. "
                        "If you exported a macOS app, rebuild it with ffmpeg installed "
                        "so the binary can be bundled, or install ffmpeg in a standard "
                        "location like /opt/homebrew/bin."
                    )
                return message or "Download failed."

        if lower_line.startswith("indexerror: list index out of range"):
            return (
                "spotDL hit incomplete fallback metadata while formatting the filename. "
                "Retry the download after the app reloads, or wait for Spotify rate limits to clear."
            )

        if lower_line.startswith("jsondecodeerror:"):
            return "The selected audio provider returned invalid data while resolving the stream."

        return stripped_line

    @classmethod
    def missing_output_message(
        cls, download_dir: Path, last_output_line: Optional[str]
    ) -> str:
        """Explain that spotDL exited without creating a visible output file."""
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
    """Parse download progress from spotDL output lines."""

    def __init__(self, *, debug_output: bool = DEBUG_OUTPUT) -> None:
        self.debug_output = debug_output

    def parse(self, line: str) -> Optional[float]:
        """Parse progress percentage from spotDL output."""
        if self.debug_output:
            print(f"DEBUG - Raw line: '{line}'")

        patterns = [
            r"(\d+(?:\.\d+)?)%",
            r"\[download\]\s*(\d+(?:\.\d+)?)%",
            r"Downloaded\s*(\d+(?:\.\d+)?)%",
            r"Progress:\s*(\d+(?:\.\d+)?)%",
            r"▰+▱*\s*(\d+(?:\.\d+)?)%",
            r"(\d+(?:\.\d+)?)%\s*complete",
            r"(\d+(?:\.\d+)?)%\s*done",
            r"(\d+(?:\.\d+)?)%\s*of",
        ]

        for pattern in patterns:
            match = re.search(pattern, line)
            if match:
                try:
                    progress = float(match.group(1))
                    if self.debug_output:
                        print(
                            f"DEBUG - Found progress: {progress}% using pattern: {pattern}"
                        )
                    return progress
                except (ValueError, IndexError):
                    continue

        if self.debug_output and any(
            keyword in line.lower()
            for keyword in [
                "download",
                "processing",
                "converting",
                "complete",
                "done",
                "finished",
            ]
        ):
            print(f"DEBUG - Download-related line (no percentage): '{line}'")

        return None


class SpotdlCommandBuilder:
    """Build spotDL subprocess commands from app settings."""

    @staticmethod
    def _spotdl_base_command() -> list[str]:
        """Build a spotDL command that works in dev and bundled app builds."""
        if getattr(sys, "frozen", False):
            return [sys.executable, "--run-spotdl"]

        return [sys.executable, "-m", "spotdl"]

    @staticmethod
    def _normalize_audio_providers(raw_value: Any) -> list[str]:
        """Normalize a provider list from UI settings or environment variables."""
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
    def _resolve_audio_providers(cls, settings: Dict[str, Any]) -> list[str]:
        """Choose the provider order, preferring explicit overrides when present."""
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

    @staticmethod
    def _get_download_directory(settings: Optional[Dict[str, Any]] = None) -> Path:
        """Resolve the active download directory for a request or the saved default."""
        if settings is not None:
            raw_directory = str(settings.get("_download_directory") or "").strip()
            if raw_directory:
                return Path(raw_directory).expanduser().resolve()

        return get_download_dir() or DEFAULT_DOWNLOAD_DIR

    @staticmethod
    def _resolve_output_template(settings: Dict[str, Any]) -> str:
        """Pick a filename template that won't crash on partial fallback metadata."""
        output_template = str(
            settings.get("output", "{artists} - {title}.{output-ext}")
        )
        if not settings.get("_temporary_input_file") or not settings.get(
            "_fallback_missing_artist"
        ):
            return output_template

        if "{artist}" not in output_template and "{artists}" not in output_template:
            return output_template

        if DEBUG_OUTPUT:
            print(
                "DEBUG - Fallback metadata is missing artist info; "
                f"using safe output template: {SAFE_FALLBACK_OUTPUT_TEMPLATE}"
            )

        return SAFE_FALLBACK_OUTPUT_TEMPLATE

    @staticmethod
    def _resolve_search_query(settings: Dict[str, Any]) -> Optional[str]:
        """Pick a provider search query override when fallback metadata is incomplete."""
        configured_query = str(
            settings.get("searchQuery") or settings.get("search_query") or ""
        ).strip()
        if configured_query:
            return configured_query

        if settings.get("_temporary_input_file") and settings.get(
            "_fallback_missing_artist"
        ):
            if DEBUG_OUTPUT:
                print(
                    "DEBUG - Fallback metadata is missing artist info; "
                    f"using title-only provider search: {TITLE_ONLY_SEARCH_QUERY}"
                )
            return TITLE_ONLY_SEARCH_QUERY

        return None

    def build(self, link: str, settings: Dict[str, Any]) -> list[str]:
        """Build the full spotDL command for a single download."""
        download_dir = self._get_download_directory(settings)
        download_dir.mkdir(parents=True, exist_ok=True)
        download_input = str(settings.get("_download_input") or link)
        output_template = self._resolve_output_template(settings)
        cmd = [
            *self._spotdl_base_command(),
            "download",
            download_input,
            "--max-retries",
            "0",
            "--output",
            f"{download_dir}/{output_template}",
        ]

        search_query = self._resolve_search_query(settings)
        if search_query:
            cmd.extend(["--search-query", search_query])

        audio_providers = self._resolve_audio_providers(settings)
        if audio_providers:
            cmd.extend(["--audio", *audio_providers])

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


class DownloadFileService:
    """Resolve output files and reveal them in the host file manager."""

    def __init__(
        self,
        downloaded_files: Dict[str, str],
        *,
        debug_output: bool = DEBUG_OUTPUT,
    ) -> None:
        self.downloaded_files = downloaded_files
        self.debug_output = debug_output

    def resolve_downloaded_file_path(self, link: str) -> Optional[Path]:
        """Resolve a stored file reference to an absolute path."""
        stored_path = self.downloaded_files.get(link)
        if not stored_path:
            return None

        file_path = Path(stored_path)
        if not file_path.is_absolute():
            file_path = (get_download_dir() or DEFAULT_DOWNLOAD_DIR) / file_path

        return file_path

    def get_downloaded_file_path(self, link: str) -> Optional[Path]:
        """Return the resolved downloaded file path when it still exists."""
        file_path = self.resolve_downloaded_file_path(link)
        if file_path is None:
            return None

        return file_path if file_path.exists() else None

    def reveal_downloaded_file(self, link: str) -> Path:
        """Reveal the downloaded file in the platform file manager."""
        file_path = self.get_downloaded_file_path(link)
        if file_path is None:
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

    @staticmethod
    def snapshot_music_files(download_dir: Path) -> Dict[Path, float]:
        """Capture the current set of audio files and their mtimes."""
        snapshot: Dict[Path, float] = {}
        if not download_dir.exists():
            return snapshot

        for ext in MUSIC_EXTENSIONS:
            for file_path in download_dir.rglob(f"*{ext}"):
                try:
                    snapshot[file_path] = file_path.stat().st_mtime
                except OSError:
                    continue

        return snapshot

    @staticmethod
    def extract_output_path_from_line(line: str, download_dir: Path) -> Optional[Path]:
        """Extract a downloaded audio path from spotDL/yt-dlp output when present."""
        cleaned_line = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", line)
        extension_pattern = "|".join(re.escape(ext) for ext in MUSIC_EXTENSIONS)
        path_pattern = re.compile(
            rf"({re.escape(str(download_dir))}.*?(?:{extension_pattern}))",
            re.IGNORECASE,
        )

        match = path_pattern.search(cleaned_line)
        if match is None:
            return None

        return Path(match.group(1).strip().strip("'\""))

    def remember_downloaded_file(self, link: str, file_path: Path) -> None:
        """Store a downloaded file path in a reusable form."""
        stored_path = str(file_path.resolve())
        self.downloaded_files[link] = stored_path
        if self.debug_output:
            print(f"DEBUG - Stored filename for {link}: {stored_path}")

    def store_downloaded_filename(
        self,
        link: str,
        detected_output_path: Optional[Path],
        before_snapshot: Dict[Path, float],
        download_dir: Path,
    ) -> Optional[Path]:
        """Try to determine and store the file that was downloaded."""
        try:
            if detected_output_path is not None and detected_output_path.exists():
                self.remember_downloaded_file(link, detected_output_path)
                return detected_output_path

            after_snapshot = self.snapshot_music_files(download_dir)
            changed_files = [
                path
                for path, mtime in after_snapshot.items()
                if before_snapshot.get(path) is None or mtime > before_snapshot[path]
            ]

            if not changed_files:
                if self.debug_output:
                    print(
                        "DEBUG - No new audio files were detected in "
                        f"{download_dir} for {link}"
                    )
                return None

            newest_file = max(
                changed_files, key=lambda file_path: file_path.stat().st_mtime
            )
            self.remember_downloaded_file(link, newest_file)
            return newest_file
        except Exception as e:
            if self.debug_output:
                print(f"DEBUG - Could not determine downloaded filename: {e}")
            return None


class DownloadService:
    """Stateful download orchestration facade for the Flask layer."""

    def __init__(self):
        self.status: Dict[str, str] = {}
        self.progress: Dict[str, float] = {}
        self.progress_callbacks: Dict[str, list] = {}
        self.downloaded_files: Dict[str, str] = {}
        self.download_processes: Dict[str, subprocess.Popen] = {}
        self.cancelled_downloads: set[str] = set()
        self.pending_cancel_deadlines: Dict[str, float] = {}
        self.errors: Dict[str, str] = {}
        self.command_builder = SpotdlCommandBuilder()
        self.progress_parser = ProgressParser(debug_output=DEBUG_OUTPUT)
        self.error_formatter = ErrorMessageFormatter()
        self.file_service = DownloadFileService(
            self.downloaded_files,
            debug_output=DEBUG_OUTPUT,
        )

    def get_status(self, links: list[str]) -> Dict[str, Dict[str, Any]]:
        """Get status and progress for multiple links with file existence check."""
        result = {}
        for link in links:
            cached_status = self.status.get(link, "idle")
            downloaded_file_path = self.get_downloaded_file_path(link)

            if cached_status == "done":
                if downloaded_file_path is not None:
                    status = "done"
                    progress = 100.0
                else:
                    self.status[link] = "idle"
                    status = "idle"
                    progress = 0.0
            else:
                status = cached_status
                progress = self.progress.get(link, 0.0)

            result[link] = {
                "status": status,
                "progress": progress,
                "can_reveal": downloaded_file_path is not None and status == "done",
            }
            if status == "error" and link in self.errors:
                result[link]["error_message"] = self.errors[link]

        return result

    def get_progress(self, link: str) -> float:
        """Get current progress for a link (0-100)."""
        return self.progress.get(link, 0.0)

    def _check_file_exists(self, link: str) -> bool:
        """Check if downloaded file still exists on disk."""
        file_path = self._resolve_downloaded_file_path(link)
        if file_path is None:
            return False

        exists = file_path.exists()
        if DEBUG_OUTPUT and not exists:
            print(f"DEBUG - Stored file not found: {file_path}")
        return exists

    def _resolve_downloaded_file_path(self, link: str) -> Optional[Path]:
        return self.file_service.resolve_downloaded_file_path(link)

    def get_downloaded_file_path(self, link: str) -> Optional[Path]:
        return self.file_service.get_downloaded_file_path(link)

    def reveal_downloaded_file(self, link: str) -> Path:
        return self.file_service.reveal_downloaded_file(link)

    @staticmethod
    def _snapshot_music_files(download_dir: Path) -> Dict[Path, float]:
        return DownloadFileService.snapshot_music_files(download_dir)

    @staticmethod
    def _extract_output_path_from_line(line: str, download_dir: Path) -> Optional[Path]:
        return DownloadFileService.extract_output_path_from_line(line, download_dir)

    def _remember_downloaded_file(self, link: str, file_path: Path) -> None:
        self.file_service.remember_downloaded_file(link, file_path)

    def _store_downloaded_filename(
        self,
        link: str,
        detected_output_path: Optional[Path],
        before_snapshot: Dict[Path, float],
        download_dir: Path,
    ) -> Optional[Path]:
        return self.file_service.store_downloaded_filename(
            link,
            detected_output_path,
            before_snapshot,
            download_dir,
        )

    @staticmethod
    def _missing_output_message(
        download_dir: Path, last_output_line: Optional[str]
    ) -> str:
        return ErrorMessageFormatter.missing_output_message(
            download_dir, last_output_line
        )

    def add_progress_callback(self, link: str, callback):
        if link not in self.progress_callbacks:
            self.progress_callbacks[link] = []
        self.progress_callbacks[link].append(callback)

    def remove_progress_callbacks(self, link: str):
        self.progress_callbacks.pop(link, None)

    def _update_progress(self, link: str, progress: float):
        old_progress = self.progress.get(link, 0)
        self.progress[link] = progress

        if DEBUG_OUTPUT:
            print(
                f"DEBUG - Progress change for {link}: {old_progress:.1f}% → {progress:.1f}%"
            )

        callbacks = self.progress_callbacks.get(link, [])
        for callback in callbacks:
            try:
                callback(link, progress)
            except Exception:
                LOGGER.exception("Progress callback error for %s", link)

    def is_busy(self, link: str) -> bool:
        return self.status.get(link) in {"queued", "downloading", "done"}

    def cancel_download(self, link: str) -> bool:
        current_status = self.status.get(link, "idle")

        if current_status not in {"downloading", "queued"}:
            self.pending_cancel_deadlines[link] = (
                time.monotonic() + PRESTART_CANCEL_WINDOW_SECONDS
            )
            self.status[link] = "idle"
            self.progress[link] = 0.0
            self.errors.pop(link, None)
            if DEBUG_OUTPUT:
                print(f"DEBUG - Pre-download cancellation recorded for: {link}")
            return True

        self.cancelled_downloads.add(link)
        self.pending_cancel_deadlines.pop(link, None)

        proc = self.download_processes.get(link)
        if proc:
            if sys.platform != "win32":
                try:
                    pgid = os.getpgid(proc.pid)
                    os.killpg(pgid, signal.SIGKILL)
                    proc.wait(timeout=2)
                except (ProcessLookupError, PermissionError):
                    pass
                except Exception as e:
                    if DEBUG_OUTPUT:
                        print(f"DEBUG - Error killing process group for {link}: {e}")
            else:
                try:
                    proc.terminate()
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
                except Exception as e:
                    if DEBUG_OUTPUT:
                        print(f"DEBUG - Error terminating process for {link}: {e}")

        self.download_processes.pop(link, None)
        self.status[link] = "idle"
        self.progress[link] = 0.0
        self.errors.pop(link, None)
        self.remove_progress_callbacks(link)

        if DEBUG_OUTPUT:
            print(f"DEBUG - Cancelled download for: {link}")

        return True

    @staticmethod
    def _spotdl_base_command() -> list[str]:
        return SpotdlCommandBuilder._spotdl_base_command()

    @staticmethod
    def _normalize_audio_providers(raw_value: Any) -> list[str]:
        return SpotdlCommandBuilder._normalize_audio_providers(raw_value)

    @classmethod
    def _resolve_audio_providers(cls, settings: Dict[str, Any]) -> list[str]:
        return SpotdlCommandBuilder._resolve_audio_providers(settings)

    @staticmethod
    def _get_download_directory(settings: Optional[Dict[str, Any]] = None) -> Path:
        return SpotdlCommandBuilder._get_download_directory(settings)

    @staticmethod
    def _resolve_output_template(settings: Dict[str, Any]) -> str:
        return SpotdlCommandBuilder._resolve_output_template(settings)

    @staticmethod
    def _resolve_search_query(settings: Dict[str, Any]) -> Optional[str]:
        return SpotdlCommandBuilder._resolve_search_query(settings)

    def build_command(self, link: str, settings: Dict[str, Any]) -> list[str]:
        return self.command_builder.build(link, settings)

    @staticmethod
    def _is_rate_limited_output(line: str) -> bool:
        return ErrorMessageFormatter.is_rate_limited_output(line)

    @staticmethod
    def _format_error_message(line: Optional[str]) -> str:
        return ErrorMessageFormatter.format_error_message(line)

    @staticmethod
    def _terminate_process(proc: subprocess.Popen) -> None:
        if sys.platform != "win32":
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        else:
            proc.terminate()

    def _parse_progress_from_output(self, line: str) -> Optional[float]:
        return self.progress_parser.parse(line)

    def _run_download(self, link: str, settings: Dict[str, Any]) -> None:
        temporary_input_file = settings.get("_temporary_input_file")
        self.status[link] = "downloading"
        self.progress[link] = 0.0
        if link in self.cancelled_downloads:
            if DEBUG_OUTPUT:
                print(f"DEBUG - Download for {link} was cancelled before start.")
            self.status[link] = "idle"
            self.progress[link] = 0.0
            self.remove_progress_callbacks(link)
            self.cancelled_downloads.discard(link)
            return
        if DEBUG_OUTPUT:
            print(f"DEBUG - Starting download for: {link}")

        start_time = time.time()
        download_dir = self._get_download_directory(settings)
        before_snapshot = self._snapshot_music_files(download_dir)
        real_progress_found = False
        last_progress = 0.0
        last_output_line: Optional[str] = None
        detected_output_path: Optional[Path] = None
        failure_reason: Optional[str] = None
        download_phases = {
            "processing": False,
            "downloading": False,
            "completed": False,
        }

        def realistic_simulation():
            nonlocal last_progress, real_progress_found, download_phases

            time.sleep(0.5)
            for step in range(1, 16):
                if real_progress_found or self.status.get(link) != "downloading":
                    return
                if not download_phases["processing"]:
                    progress = step
                    if progress > last_progress:
                        last_progress = progress
                        self._update_progress(link, progress)
                        if DEBUG_OUTPUT:
                            print(f"DEBUG - PHASE 1 (Processing): {progress}%")
                time.sleep(0.3)

            for step in range(16, 86):
                if real_progress_found or self.status.get(link) != "downloading":
                    return

                if download_phases["downloading"]:
                    progress = min(step + 10, 85)
                else:
                    progress = step

                if progress > last_progress:
                    last_progress = progress
                    self._update_progress(link, progress)
                    if DEBUG_OUTPUT:
                        print(f"DEBUG - PHASE 2 (Downloading): {progress}%")

                if progress < 30:
                    time.sleep(0.4)
                elif progress < 60:
                    time.sleep(0.6)
                else:
                    time.sleep(0.8)

            for step in range(86, 96):
                if real_progress_found or self.status.get(link) != "downloading":
                    return
                progress = step
                if progress > last_progress:
                    last_progress = progress
                    self._update_progress(link, progress)
                    if DEBUG_OUTPUT:
                        print(f"DEBUG - PHASE 3 (Finalizing): {progress}%")
                time.sleep(1.0)

        sim_thread = threading.Thread(target=realistic_simulation, daemon=True)
        sim_thread.start()

        try:
            cmd = self.build_command(link, settings)
            if DEBUG_OUTPUT:
                print(f"DEBUG - Running command: {' '.join(cmd)}")

            preexec_fn = os.setsid if sys.platform != "win32" else None
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                universal_newlines=True,
                bufsize=0,
                preexec_fn=preexec_fn,
            )

            self.download_processes[link] = proc

            if link in self.cancelled_downloads:
                if DEBUG_OUTPUT:
                    print(
                        f"DEBUG - Detected cancellation for {link} right after process start. Terminating."
                    )
                try:
                    if sys.platform != "win32":
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    else:
                        proc.terminate()
                except Exception:
                    pass
                proc.wait(timeout=5)
                self.status[link] = "idle"
                self.progress[link] = 0.0
                self.remove_progress_callbacks(link)
                self.download_processes.pop(link, None)
                self.cancelled_downloads.discard(link)
                return

            lines_seen = 0
            if proc.stdout:
                while True:
                    line = proc.stdout.readline()
                    if not line:
                        break

                    line = line.strip()
                    lines_seen += 1

                    if line:
                        last_output_line = line
                        extracted_path = self._extract_output_path_from_line(
                            line, download_dir
                        )
                        if extracted_path is not None:
                            detected_output_path = extracted_path
                        if DEBUG_OUTPUT:
                            print(f"SpotDL output (line {lines_seen}): {line}")

                        if self._is_rate_limited_output(line):
                            failure_reason = self._format_error_message(line)
                            self.errors[link] = failure_reason
                            self.status[link] = "error"
                            self.progress[link] = 0.0
                            if DEBUG_OUTPUT:
                                print(
                                    f"DEBUG - Rate limit detected for {link}: {failure_reason}"
                                )
                            try:
                                self._terminate_process(proc)
                            except Exception as terminate_error:
                                if DEBUG_OUTPUT:
                                    print(
                                        "DEBUG - Failed to terminate rate-limited process "
                                        f"for {link}: {terminate_error}"
                                    )
                            break

                        lower_line = line.lower()
                        if "processing" in lower_line or "query" in lower_line:
                            download_phases["processing"] = True
                            if last_progress < 10:
                                last_progress = 10
                                self._update_progress(link, 10)
                                if DEBUG_OUTPUT:
                                    print("DEBUG - DETECTED: Processing phase")
                        elif any(
                            keyword in lower_line
                            for keyword in ["downloading", "found", "fetching"]
                        ):
                            download_phases["downloading"] = True
                            if last_progress < 40:
                                last_progress = 40
                                self._update_progress(link, 40)
                                if DEBUG_OUTPUT:
                                    print("DEBUG - DETECTED: Download phase")
                        elif "downloaded" in lower_line and '"' in line:
                            download_phases["completed"] = True
                            real_progress_found = True
                            if last_progress < 98:
                                last_progress = 98
                                self._update_progress(link, 98)
                                if DEBUG_OUTPUT:
                                    print(
                                        "DEBUG - DETECTED: Download completed, setting to 98%"
                                    )

                        progress = self._parse_progress_from_output(line)
                        if progress is not None and progress > last_progress:
                            if DEBUG_OUTPUT:
                                print(
                                    f"DEBUG - REAL PROGRESS DETECTED: {progress}% (was {last_progress}%)"
                                )
                            real_progress_found = True
                            last_progress = progress
                            self._update_progress(link, progress)

            proc.wait()

            elapsed_time = time.time() - start_time
            if DEBUG_OUTPUT:
                print(f"DEBUG - Process completed with return code: {proc.returncode}")
                print(
                    f"DEBUG - Total time: {elapsed_time:.1f}s, Lines seen: {lines_seen}"
                )
                print(f"DEBUG - Final progress: {last_progress}%")
                print(f"DEBUG - Phases: {download_phases}")

            if proc.returncode == 0:
                stored_file = self._store_downloaded_filename(
                    link,
                    detected_output_path,
                    before_snapshot,
                    download_dir,
                )
                if stored_file is None or not stored_file.exists():
                    self.status[link] = "error"
                    failure_reason = self._missing_output_message(
                        download_dir, last_output_line
                    )
                    self.errors[link] = failure_reason
                    self.progress[link] = 0.0
                    print(
                        f"Download failed for {link} even though spotDL exited successfully."
                    )
                    print(f"Download failure reason: {failure_reason}")
                else:
                    self.status[link] = "done"
                    self.errors.pop(link, None)
                    if last_progress < 100:
                        self._update_progress(link, 100.0)
                    print(f"Successfully downloaded: {link}")
            else:
                if link in self.cancelled_downloads:
                    if DEBUG_OUTPUT:
                        print(
                            f"DEBUG - Download was cancelled (return code {proc.returncode}), keeping status as-is"
                        )
                else:
                    self.status[link] = "error"
                    failure_reason = failure_reason or self._format_error_message(
                        last_output_line
                    )
                    if last_output_line is None:
                        failure_reason = (
                            f"Download subprocess exited with code {proc.returncode} "
                            "without any output."
                        )
                    self.errors[link] = failure_reason
                    print(
                        f"Download failed for {link} with return code: {proc.returncode}"
                    )
                    print(f"Download failure reason: {failure_reason}")

        except Exception as e:
            if link in self.cancelled_downloads:
                if DEBUG_OUTPUT:
                    print(
                        f"DEBUG - Download was cancelled (exception: {e}), keeping status as-is"
                    )
            else:
                self.status[link] = "error"
                self.errors[link] = self._format_error_message(str(e))
                LOGGER.exception("Download error for %s", link)
                print(f"Download error for {link}: {e}")
        finally:
            self.remove_progress_callbacks(link)
            self.download_processes.pop(link, None)
            self.cancelled_downloads.discard(link)
            self.pending_cancel_deadlines.pop(link, None)
            if temporary_input_file:
                try:
                    Path(str(temporary_input_file)).unlink(missing_ok=True)
                except OSError as exc:
                    if DEBUG_OUTPUT:
                        print(
                            "DEBUG - Could not remove temporary spotdl save file "
                            f"for {link}: {exc}"
                        )

    def start_download(self, link: str, settings: Dict[str, Any]) -> bool:
        pending_deadline = self.pending_cancel_deadlines.get(link)
        if pending_deadline is not None:
            if time.monotonic() <= pending_deadline:
                if DEBUG_OUTPUT:
                    print(
                        f"DEBUG - Download for {link} was skipped because a "
                        "pre-start cancel request arrived first."
                    )
                self.pending_cancel_deadlines.pop(link, None)
                self.status[link] = "idle"
                self.progress[link] = 0.0
                self.errors.pop(link, None)
                return False

            self.pending_cancel_deadlines.pop(link, None)

        if self.is_busy(link):
            return False

        self.progress[link] = 0.0
        self.errors.pop(link, None)
        self.status[link] = "downloading"
        thread = threading.Thread(
            target=self._run_download,
            args=(link, settings),
            daemon=True,
        )
        thread.start()
        return True


DownloadManager = DownloadService
download_manager = DownloadService()
