"""Download management and spotDL command building."""

import subprocess
import threading
import re
from typing import Dict, Any, Optional
from pathlib import Path

from config import DOWNLOAD_DIR, QUALITY_OPTIONS

# Set to False in production to reduce console output
DEBUG_OUTPUT = True


class DownloadManager:
    """Manages download processes and status tracking."""
    
    def __init__(self):
        self.status: Dict[str, str] = {}  # link -> idle|downloading|done|error
        self.progress: Dict[str, float] = {}  # link -> progress percentage (0-100)
        self.progress_callbacks: Dict[str, list] = {}  # link -> list of callback functions
    
    def get_status(self, links: list[str]) -> Dict[str, str]:
        """Get status for multiple links."""
        return {link: self.status.get(link, "idle") for link in links}
    
    def get_progress(self, link: str) -> float:
        """Get current progress for a link (0-100)."""
        return self.progress.get(link, 0.0)
    
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
        return self.status.get(link) in {"downloading", "done"}
    
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
        
        # Base command - SIMPLIFIED to reduce output complexity
        output_template = settings.get('output', '{artists} - {title}.{output-ext}')
        cmd = [
            "spotdl", 
            "download", 
            link, 
            "--output", 
            f"{DOWNLOAD_DIR}/{output_template}"
        ]
        
        # Add quality/bitrate setting
        quality = settings.get('quality', 'best')
        if quality in QUALITY_OPTIONS and QUALITY_OPTIONS[quality] is not None:
            cmd.extend(["--bitrate", QUALITY_OPTIONS[quality]])
        
        # Add format setting
        format_type = settings.get('format', 'mp3')
        if format_type and format_type != 'mp3':
            cmd.extend(["--format", format_type])
        
        # Add advanced options
        if settings.get('playlistNumbering'):
            cmd.append("--playlist-numbering")
        
        if settings.get('skipExplicit'):
            cmd.append("--skip-explicit")
        
        if settings.get('generateLrc'):
            cmd.append("--generate-lrc")
        
        return cmd
    
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
        import time
        import threading
        
        self.status[link] = "downloading"
        self.progress[link] = 0.0
        if DEBUG_OUTPUT:
            print(f"DEBUG - Starting download for: {link}")
        
        start_time = time.time()
        real_progress_found = False
        last_progress = 0.0
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
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                universal_newlines=True,
                bufsize=0
            )
            
            lines_seen = 0
            
            # Read output line by line
            if proc.stdout:
                while True:
                    line = proc.stdout.readline()
                    if not line:
                        break
                    
                    line = line.strip()
                    lines_seen += 1
                    
                    if line:
                        if DEBUG_OUTPUT:
                            print(f"SpotDL output (line {lines_seen}): {line}")
                        
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
                # Smooth transition to 100%
                if last_progress < 100:
                    self._update_progress(link, 100.0)
                print(f"Successfully downloaded: {link}")
            else:
                self.status[link] = "error"
                print(f"Download failed for {link} with return code: {proc.returncode}")
                
        except Exception as e:
            self.status[link] = "error"
            print(f"Download error for {link}: {e}")
        finally:
            # Clean up callbacks
            self.remove_progress_callbacks(link)
    
    def start_download(self, link: str, settings: Dict[str, Any]) -> bool:
        """
        Start download for a link with given settings.
        
        Args:
            link: URL to download
            settings: User preferences
            
        Returns:
            True if download started, False if already busy
        """
        if self.is_busy(link):
            return False
        
        self.status[link] = "queued"
        thread = threading.Thread(
            target=self._run_download, 
            args=(link, settings),
            daemon=True
        )
        thread.start()
        return True


# Global instance
download_manager = DownloadManager()
