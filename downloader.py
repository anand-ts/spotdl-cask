"""Download management and spotDL command building."""

import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading
import time
from typing import Dict, Any, Optional

from config import DOWNLOAD_DIR, QUALITY_OPTIONS

# Set to False in production to reduce console output
DEBUG_OUTPUT = True
MUSIC_EXTENSIONS = (".mp3", ".flac", ".m4a", ".opus", ".ogg", ".wav")
PRESTART_CANCEL_WINDOW_SECONDS = 1.0


class DownloadManager:
    """Manages download processes and status tracking."""
    
    def __init__(self):
        self.status: Dict[str, str] = {}  # link -> idle|downloading|done|error
        self.progress: Dict[str, float] = {}  # link -> progress percentage (0-100)
        self.progress_callbacks: Dict[str, list] = {}  # link -> list of callback functions
        self.downloaded_files: Dict[str, str] = {}  # link -> actual filename that was downloaded
        self.download_processes: Dict[str, subprocess.Popen] = {}  # link -> process for canceling
        self.cancelled_downloads: set[str] = set()  # track intentionally cancelled downloads
        self.pending_cancel_deadlines: Dict[str, float] = {}
        self.errors: Dict[str, str] = {}  # link -> latest friendly error message
    
    def get_status(self, links: list[str]) -> Dict[str, Dict[str, Any]]:
        """Get status and progress for multiple links with file existence check."""
        result = {}
        for link in links:
            cached_status = self.status.get(link, "idle")
            
            # If status is "done", verify the file actually exists
            if cached_status == "done":
                if self._check_file_exists(link):
                    status = "done"
                    progress = 100.0
                else:
                    # File was deleted, reset status
                    self.status[link] = "idle"
                    status = "idle"
                    progress = 0.0
            else:
                status = cached_status
                progress = self.progress.get(link, 0.0)

            result[link] = {"status": status, "progress": progress}
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
        """Resolve a stored file reference to an absolute path."""
        stored_path = self.downloaded_files.get(link)
        if not stored_path:
            return None

        file_path = Path(stored_path)
        if not file_path.is_absolute():
            file_path = DOWNLOAD_DIR / file_path

        return file_path

    @staticmethod
    def _snapshot_music_files() -> Dict[Path, float]:
        """Capture the current set of audio files and their mtimes."""
        snapshot: Dict[Path, float] = {}
        if not DOWNLOAD_DIR.exists():
            return snapshot

        for ext in MUSIC_EXTENSIONS:
            for file_path in DOWNLOAD_DIR.rglob(f"*{ext}"):
                try:
                    snapshot[file_path] = file_path.stat().st_mtime
                except OSError as exc:
                    if DEBUG_OUTPUT:
                        print(f"DEBUG - Could not stat music file {file_path}: {exc}")

        return snapshot

    @staticmethod
    def _extract_output_path_from_line(line: str) -> Optional[Path]:
        """Extract a downloaded audio path from spotDL/yt-dlp output when present."""
        cleaned_line = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", line)
        extension_pattern = "|".join(re.escape(ext) for ext in MUSIC_EXTENSIONS)
        path_pattern = re.compile(
            rf"({re.escape(str(DOWNLOAD_DIR))}.*?(?:{extension_pattern}))",
            re.IGNORECASE,
        )

        match = path_pattern.search(cleaned_line)
        if match is None:
            return None

        return Path(match.group(1).strip().strip("'\""))

    def _remember_downloaded_file(self, link: str, file_path: Path) -> None:
        """Store a downloaded file path in a reusable form."""
        try:
            stored_path = str(file_path.relative_to(DOWNLOAD_DIR))
        except ValueError:
            stored_path = str(file_path)

        self.downloaded_files[link] = stored_path
        if DEBUG_OUTPUT:
            print(f"DEBUG - Stored filename for {link}: {stored_path}")

    def _store_downloaded_filename(
        self,
        link: str,
        detected_output_path: Optional[Path],
        before_snapshot: Dict[Path, float],
    ) -> None:
        """Try to determine and store the file that was downloaded."""
        try:
            if detected_output_path is not None and detected_output_path.exists():
                self._remember_downloaded_file(link, detected_output_path)
                return

            after_snapshot = self._snapshot_music_files()
            changed_files = [
                path
                for path, mtime in after_snapshot.items()
                if before_snapshot.get(path) is None or mtime > before_snapshot[path]
            ]

            if not changed_files:
                return

            newest_file = max(changed_files, key=lambda file_path: file_path.stat().st_mtime)
            self._remember_downloaded_file(link, newest_file)
        except Exception as e:
            if DEBUG_OUTPUT:
                print(f"DEBUG - Could not determine downloaded filename: {e}")
     
    def add_progress_callback(self, link: str, callback):
        """Add a callback function to be called when progress updates."""
        if link not in self.progress_callbacks:
            self.progress_callbacks[link] = []
        self.progress_callbacks[link].append(callback)
    
    def remove_progress_callbacks(self, link: str):
        """Remove all progress callbacks for a link."""
        self.progress_callbacks.pop(link, None)
    
    def _update_progress(self, link: str, progress: float):
        """Update progress and notify callbacks."""
        old_progress = self.progress.get(link, 0)
        self.progress[link] = progress
        
        # Debug progress changes
        if DEBUG_OUTPUT:
            print(f"DEBUG - Progress change for {link}: {old_progress:.1f}% → {progress:.1f}%")
        
        callbacks = self.progress_callbacks.get(link, [])
        for callback in callbacks:
            try:
                callback(link, progress)
            except Exception as e:
                print(f"Progress callback error: {e}")
    
    def is_busy(self, link: str) -> bool:
        """Check if link is currently downloading or already done."""
        # Treat both queued (legacy) and downloading states as busy so that the same
        # track cannot be enqueued multiple times while we are still spinning up the
        # process.
        return self.status.get(link) in {"queued", "downloading", "done"}
    
    def cancel_download(self, link: str) -> bool:
        """Cancel an active download."""
        current_status = self.status.get(link, "idle")

        # If the download hasn't started yet (idle/queued) we can still honour a cancel
        # request by flagging the link as cancelled so that any later attempt to start
        # the download will be skipped.
        if current_status not in {"downloading", "queued"}:
            # There is nothing to terminate yet, but briefly record the intent so a
            # /cancel request that overtakes /download on the wire can still win.
            self.pending_cancel_deadlines[link] = (
                time.monotonic() + PRESTART_CANCEL_WINDOW_SECONDS
            )
            # Ensure status is reset
            self.status[link] = "idle"
            self.progress[link] = 0.0
            self.errors.pop(link, None)
            if DEBUG_OUTPUT:
                print(f"DEBUG - Pre-download cancellation recorded for: {link}")
            return True

        # From here on we know the status is downloading/queued and a process may exist
        # Mark as intentionally cancelled
        self.cancelled_downloads.add(link)
        self.pending_cancel_deadlines.pop(link, None)
        
        # Get the process handle
        proc = self.download_processes.get(link)
        if proc:
            if sys.platform != "win32":
                try:
                    # Kill the entire process group on non-Windows systems
                    # Use SIGKILL for a more forceful termination
                    pgid = os.getpgid(proc.pid)
                    os.killpg(pgid, signal.SIGKILL)
                    proc.wait(timeout=2)  # Process should terminate quickly
                except (ProcessLookupError, PermissionError):
                    pass  # Process already dead or no permissions
                except Exception as e:
                    if DEBUG_OUTPUT:
                        print(f"DEBUG - Error killing process group for {link}: {e}")
            else:  # On Windows, use original logic
                try:
                    proc.terminate()
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
                except Exception as e:
                    if DEBUG_OUTPUT:
                        print(f"DEBUG - Error terminating process for {link}: {e}")
        
        # Clean up
        self.download_processes.pop(link, None)
        self.status[link] = "idle"
        self.progress[link] = 0.0
        self.errors.pop(link, None)
        self.remove_progress_callbacks(link)
        
        if DEBUG_OUTPUT:
            print(f"DEBUG - Cancelled download for: {link}")
        
        return True
    
    def build_command(self, link: str, settings: Dict[str, Any]) -> list[str]:
        """
        Build spotdl command with user settings.
        
        Args:
            link: URL to download
            settings: User preferences from the UI
            
        Returns:
            List of command arguments for subprocess
        """
        # Ensure download directory exists
        DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
        download_input = str(settings.get("_download_input") or link)
        
        # Base command - SIMPLIFIED to reduce output complexity
        output_template = settings.get('output', '{artists} - {title}.{output-ext}')
        cmd = [
            "spotdl", 
            "download", 
            download_input,
            "--max-retries",
            "0",
            "--output", 
            f"{DOWNLOAD_DIR}/{output_template}"
        ]
        
        # Add quality/bitrate setting
        quality = str(settings.get("quality", "best"))
        bitrate = QUALITY_OPTIONS.get(quality)
        if bitrate is not None:
            cmd.extend(["--bitrate", bitrate])

        # Add format setting
        format_type = str(settings.get("format", "mp3"))
        if format_type != "mp3":
            cmd.extend(["--format", format_type])
        
        # Add advanced options
        if settings.get('playlistNumbering'):
            cmd.append("--playlist-numbering")
        
        if settings.get('skipExplicit'):
            cmd.append("--skip-explicit")
        
        if settings.get('generateLrc'):
            cmd.append("--generate-lrc")
        
        return cmd

    @staticmethod
    def _is_rate_limited_output(line: str) -> bool:
        """Detect spotDL/Spotify rate-limit output lines."""
        lower_line = line.lower()
        return (
            "rate/request limit" in lower_line
            or "retry will occur after:" in lower_line
            or "http status: 429" in lower_line
        )

    @staticmethod
    def _format_error_message(line: Optional[str]) -> str:
        """Convert raw process output into a friendlier UI message."""
        if not line:
            return "Download failed."

        if DownloadManager._is_rate_limited_output(line):
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

        return line

    @staticmethod
    def _terminate_process(proc: subprocess.Popen) -> None:
        """Terminate a spotDL subprocess and its children."""
        if sys.platform != "win32":
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        else:
            proc.terminate()
    
    def _parse_progress_from_output(self, line: str) -> Optional[float]:
        """
        Parse progress percentage from spotdl output.
        
        SpotDL typically outputs progress in formats like:
        - "Downloaded 50.2% of track"
        - "[download] 50.2% of ~5.1MiB at 1.2MiB/s ETA 00:04"
        - "Progress: 50.2%"
        - "▰▰▰▰▰▰▱▱▱▱ 60%"
        """
        # Debug: Print every line to see actual output format (only in debug mode)
        if DEBUG_OUTPUT:
            print(f"DEBUG - Raw line: '{line}'")
        
        # Common progress patterns (expanded)
        patterns = [
            r'(\d+(?:\.\d+)?)%',  # Simple percentage anywhere in line
            r'\[download\]\s*(\d+(?:\.\d+)?)%',  # [download] XX%
            r'Downloaded\s*(\d+(?:\.\d+)?)%',  # Downloaded XX%
            r'Progress:\s*(\d+(?:\.\d+)?)%',  # Progress: XX%
            r'▰+▱*\s*(\d+(?:\.\d+)?)%',  # Progress bar with percentage
            r'(\d+(?:\.\d+)?)%\s*complete',  # XX% complete
            r'(\d+(?:\.\d+)?)%\s*done',  # XX% done
            r'(\d+(?:\.\d+)?)%\s*of',  # XX% of something
        ]
        
        for pattern in patterns:
            match = re.search(pattern, line)
            if match:
                try:
                    progress = float(match.group(1))
                    if DEBUG_OUTPUT:
                        print(f"DEBUG - Found progress: {progress}% using pattern: {pattern}")
                    return progress
                except (ValueError, IndexError):
                    continue
        
        # Check for common download indicators that might suggest progress
        if DEBUG_OUTPUT and any(keyword in line.lower() for keyword in ['download', 'processing', 'converting', 'complete', 'done', 'finished']):
            print(f"DEBUG - Download-related line (no percentage): '{line}'")
        
        return None
    
    def _run_download(self, link: str, settings: Dict[str, Any]) -> None:
        """Execute download in background thread with REALISTIC progress tracking."""
        temporary_input_file = settings.get("_temporary_input_file")
        self.status[link] = "downloading"
        self.progress[link] = 0.0
        # If the user cancelled very quickly (before the worker thread even started),
        # honour that request right away.
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
        before_snapshot = self._snapshot_music_files()
        real_progress_found = False
        last_progress = 0.0
        last_output_line: Optional[str] = None
        detected_output_path: Optional[Path] = None
        failure_reason: Optional[str] = None
        download_phases = {
            'processing': False,
            'downloading': False,
            'completed': False
        }
        
        def realistic_simulation():
            """Realistic progress simulation that adapts to download phases."""
            nonlocal last_progress, real_progress_found, download_phases
            
            time.sleep(0.5)  # Short initial delay
            
            # Phase 1: Initial processing (0-15%)
            for step in range(1, 16):
                if real_progress_found or self.status.get(link) != "downloading":
                    return
                
                if not download_phases['processing']:
                    progress = step
                    if progress > last_progress:
                        last_progress = progress
                        self._update_progress(link, progress)
                        if DEBUG_OUTPUT:
                            print(f"DEBUG - PHASE 1 (Processing): {progress}%")
                
                time.sleep(0.3)  # Faster initial progress
            
            # Phase 2: Main download simulation (15-85%)
            for step in range(16, 86):
                if real_progress_found or self.status.get(link) != "downloading":
                    return
                
                # Speed up if we detect downloading has started
                if download_phases['downloading']:
                    progress = min(step + 10, 85)  # Accelerate when downloading detected
                else:
                    progress = step
                
                if progress > last_progress:
                    last_progress = progress
                    self._update_progress(link, progress)
                    if DEBUG_OUTPUT:
                        print(f"DEBUG - PHASE 2 (Downloading): {progress}%")
                
                # Adaptive timing - slower progress as we get higher
                if progress < 30:
                    time.sleep(0.4)
                elif progress < 60:
                    time.sleep(0.6)
                else:
                    time.sleep(0.8)
            
            # Phase 3: Near completion (85-95%)
            for step in range(86, 96):
                if real_progress_found or self.status.get(link) != "downloading":
                    return
                
                progress = step
                if progress > last_progress:
                    last_progress = progress
                    self._update_progress(link, progress)
                    if DEBUG_OUTPUT:
                        print(f"DEBUG - PHASE 3 (Finalizing): {progress}%")
                
                time.sleep(1.0)  # Slower near completion
        
        # Start realistic simulation
        sim_thread = threading.Thread(target=realistic_simulation, daemon=True)
        sim_thread.start()
        
        try:
            cmd = self.build_command(link, settings)
            if DEBUG_OUTPUT:
                print(f"DEBUG - Running command: {' '.join(cmd)}")
            
            # Start the process
            # For non-Windows, start in a new session to allow killing the whole process tree
            preexec_fn = os.setsid if sys.platform != "win32" else None
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                universal_newlines=True,
                bufsize=0,
                preexec_fn=preexec_fn
            )
            
            # Store process handle for cancellation
            self.download_processes[link] = proc

            # Cancellation could have been requested in the tiny window between the
            # start of this thread and the creation of the subprocess.  Honour it now.
            if link in self.cancelled_downloads:
                if DEBUG_OUTPUT:
                    print(f"DEBUG - Detected cancellation for {link} right after process start. Terminating.")
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
            
            # Read output line by line
            if proc.stdout:
                while True:
                    # Cancellation is now handled by cancel_download which terminates
                    # the process. readline() will then unblock and return an
                    # empty string, breaking the loop.
                    line = proc.stdout.readline()
                    if not line:
                        break
                    
                    line = line.strip()
                    lines_seen += 1
                    
                    if line:
                        last_output_line = line
                        extracted_path = self._extract_output_path_from_line(line)
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
                                print(f"DEBUG - Rate limit detected for {link}: {failure_reason}")
                            try:
                                self._terminate_process(proc)
                            except Exception as terminate_error:
                                if DEBUG_OUTPUT:
                                    print(
                                        "DEBUG - Failed to terminate rate-limited process "
                                        f"for {link}: {terminate_error}"
                                    )
                            break
                        
                        # Detect download phases from SpotDL output
                        lower_line = line.lower()
                        
                        if 'processing' in lower_line or 'query' in lower_line:
                            download_phases['processing'] = True
                            if last_progress < 10:
                                last_progress = 10
                                self._update_progress(link, 10)
                                if DEBUG_OUTPUT:
                                    print("DEBUG - DETECTED: Processing phase")
                        
                        elif any(keyword in lower_line for keyword in ['downloading', 'found', 'fetching']):
                            download_phases['downloading'] = True
                            if last_progress < 40:
                                last_progress = 40
                                self._update_progress(link, 40)
                                if DEBUG_OUTPUT:
                                    print("DEBUG - DETECTED: Download phase")
                        
                        elif 'downloaded' in lower_line and '"' in line:
                            # This is the completion message: Downloaded "Artist - Title": URL
                            download_phases['completed'] = True
                            real_progress_found = True
                            if last_progress < 98:
                                last_progress = 98
                                self._update_progress(link, 98)
                                if DEBUG_OUTPUT:
                                    print("DEBUG - DETECTED: Download completed, setting to 98%")
                        
                        # Try to parse any real progress percentages (just in case)
                        progress = self._parse_progress_from_output(line)
                        if progress is not None and progress > last_progress:
                            if DEBUG_OUTPUT:
                                print(f"DEBUG - REAL PROGRESS DETECTED: {progress}% (was {last_progress}%)")
                            
                            real_progress_found = True
                            last_progress = progress
                            self._update_progress(link, progress)
            
            # Wait for process to complete
            proc.wait()
            
            elapsed_time = time.time() - start_time
            if DEBUG_OUTPUT:
                print(f"DEBUG - Process completed with return code: {proc.returncode}")
                print(f"DEBUG - Total time: {elapsed_time:.1f}s, Lines seen: {lines_seen}")
                print(f"DEBUG - Final progress: {last_progress}%")
                print(f"DEBUG - Phases: {download_phases}")
            
            if proc.returncode == 0:
                self.status[link] = "done"
                self.errors.pop(link, None)
                # Smooth transition to 100%
                if last_progress < 100:
                    self._update_progress(link, 100.0)
                
                # Try to determine what file was downloaded
                self._store_downloaded_filename(
                    link,
                    detected_output_path,
                    before_snapshot,
                )
                print(f"Successfully downloaded: {link}")
            else:
                # Check if this was an intentional cancellation
                if link in self.cancelled_downloads:
                    # Don't overwrite status - it should already be "idle" from cancel_download()
                    if DEBUG_OUTPUT:
                        print(f"DEBUG - Download was cancelled (return code {proc.returncode}), keeping status as-is")
                else:
                    # This was a real error, not a cancellation
                    self.status[link] = "error"
                    failure_reason = failure_reason or self._format_error_message(last_output_line)
                    self.errors[link] = failure_reason
                    print(f"Download failed for {link} with return code: {proc.returncode}")
                    print(f"Download failure reason: {failure_reason}")
                
        except Exception as e:
            # Check if this was an intentional cancellation
            if link in self.cancelled_downloads:
                if DEBUG_OUTPUT:
                    print(f"DEBUG - Download was cancelled (exception: {e}), keeping status as-is")
            else:
                self.status[link] = "error"
                self.errors[link] = self._format_error_message(str(e))
                print(f"Download error for {link}: {e}")
        finally:
            # Clean up callbacks and process handle
            self.remove_progress_callbacks(link)
            self.download_processes.pop(link, None)
            # Clean up cancellation tracking
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
        """
        Start download for a link with given settings.
        
        Args:
            link: URL to download
            settings: User preferences
            
        Returns:
            True if download started, False if already busy
        """
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

        # Reset stale progress early so UI doesn't briefly render an old 100% value
        # before the worker thread initializes it again.
        self.progress[link] = 0.0
        self.errors.pop(link, None)

        # Mark as downloading immediately to avoid a short-lived "queued" state that can
        # cause race conditions with cancel requests coming from the UI before the
        # background thread has a chance to update the status.
        self.status[link] = "downloading"
        thread = threading.Thread(
            target=self._run_download,
            args=(link, settings),
            daemon=True
        )
        thread.start()
        return True


# Global instance
download_manager = DownloadManager()
