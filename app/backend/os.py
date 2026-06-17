"""OS integrations for folder picking and revealing downloaded files."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Optional

from config import DEFAULT_DOWNLOAD_DIR


def best_initial_directory(configured_dir: Optional[Path] = None) -> Path:
    """Return the best existing directory to seed the folder picker."""
    if configured_dir and configured_dir.exists():
        return configured_dir
    if DEFAULT_DOWNLOAD_DIR.exists():
        return DEFAULT_DOWNLOAD_DIR
    if DEFAULT_DOWNLOAD_DIR.parent.exists():
        return DEFAULT_DOWNLOAD_DIR.parent
    return Path.home()


def choose_directory(initial_dir: Optional[Path] = None) -> Optional[Path]:
    """Open a native folder picker and return the chosen directory, if any."""
    initial_dir = initial_dir or best_initial_directory()
    if not initial_dir.exists():
        initial_dir = initial_dir.parent if initial_dir.parent.exists() else Path.home()

    if sys.platform == "darwin":
        prompt = "Choose where spotDL Web Downloader should save downloads"
        escaped_dir = str(initial_dir).replace("\\", "\\\\").replace('"', '\\"')
        escaped_prompt = prompt.replace("\\", "\\\\").replace('"', '\\"')
        script = "\n".join(
            [
                'tell application "Finder"',
                "activate",
                f'set defaultLocation to POSIX file "{escaped_dir}"',
                f'set chosenFolder to choose folder with prompt "{escaped_prompt}" default location defaultLocation',
                "end tell",
                "POSIX path of chosenFolder",
            ]
        )
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            selected_dir = result.stdout.strip()
            if selected_dir:
                return Path(selected_dir).expanduser().resolve()
        if "User canceled" in result.stderr:
            return None

    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        selected_dir = filedialog.askdirectory(
            initialdir=str(initial_dir),
            title="Choose where spotDL Web Downloader should save downloads",
            mustexist=True,
        )
        root.destroy()
        if selected_dir:
            return Path(selected_dir).expanduser().resolve()
    except Exception:
        return None

    return None


def reveal_in_file_manager(file_path: Path) -> None:
    """Reveal a completed file in the platform file manager."""
    file_path = file_path.expanduser().resolve()
    if not file_path.exists():
        raise FileNotFoundError(f"Downloaded file was not found: {file_path}")

    if sys.platform == "darwin":
        result = subprocess.run(["open", "-R", str(file_path)], check=False)
    elif sys.platform == "win32":
        result = subprocess.run(
            ["explorer", "/select,", str(file_path)],
            check=False,
        )
    else:
        result = subprocess.run(["xdg-open", str(file_path.parent)], check=False)

    if result.returncode != 0:
        raise RuntimeError(f"Could not reveal the downloaded file: {file_path}")
