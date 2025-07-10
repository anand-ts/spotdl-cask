"""Download management and spotDL command building."""

import subprocess
import threading
from typing import Dict, Any
from pathlib import Path

from config import DOWNLOAD_DIR, QUALITY_OPTIONS


class DownloadManager:
    """Manages download processes and status tracking."""
    
    def __init__(self):
        self.status: Dict[str, str] = {}  # link -> idle|downloading|done|error
    
    def get_status(self, links: list[str]) -> Dict[str, str]:
        """Get status for multiple links."""
        return {link: self.status.get(link, "idle") for link in links}
    
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
        
        # Base command
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
    
    def _run_download(self, link: str, settings: Dict[str, Any]) -> None:
        """Execute download in background thread."""
        self.status[link] = "downloading"
        
        try:
            cmd = self.build_command(link, settings)
            print(f"Running command: {' '.join(cmd)}")
            
            proc = subprocess.run(cmd, capture_output=True, text=True)
            
            if proc.returncode == 0:
                self.status[link] = "done"
                print(f"Successfully downloaded: {link}")
            else:
                self.status[link] = "error"
                print(f"Download failed for {link}: {proc.stderr}")
                
        except Exception as e:
            self.status[link] = "error"
            print(f"Download error for {link}: {e}")
    
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
