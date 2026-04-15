"""Binary discovery helpers for bundled and local runtimes."""

from __future__ import annotations

import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Optional

LOGGER = logging.getLogger(__name__)
COMMON_BINARY_DIRS = (
    Path("/opt/homebrew/bin"),
    Path("/usr/local/bin"),
    Path("/opt/local/bin"),
)


def _resource_dir() -> Path:
    """Return the resource root for source and frozen builds."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)

    return Path(__file__).resolve().parent.parent


def _binary_filename(binary_name: str) -> str:
    """Return the platform-specific executable filename for a binary."""
    if sys.platform == "win32":
        return f"{binary_name}.exe"

    return binary_name


def _candidate_path_from_value(value: str, binary_name: str) -> Path:
    """Normalize an env-provided binary path or containing directory."""
    candidate = Path(value).expanduser()
    if candidate.is_dir():
        return candidate / _binary_filename(binary_name)

    return candidate


def _is_executable_file(path: Path) -> bool:
    """Return True when a path exists and can be executed."""
    return path.is_file() and os.access(path, os.X_OK)


def _iter_binary_candidates(binary_name: str):
    """Yield likely binary locations for bundled and GUI-launched app runtimes."""
    seen: set[str] = set()

    env_var_names = (
        f"SPOTDL_{binary_name.upper()}",
        f"{binary_name.upper()}_PATH",
        f"{binary_name.upper()}_BINARY",
    )
    for env_var_name in env_var_names:
        raw_value = os.getenv(env_var_name, "").strip()
        if not raw_value:
            continue

        candidate = _candidate_path_from_value(raw_value, binary_name)
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        yield candidate

    if getattr(sys, "frozen", False):
        executable_dir = Path(sys.executable).resolve().parent
        candidate_dirs = [
            _resource_dir() / "bin",
            _resource_dir(),
            executable_dir / "bin",
            executable_dir,
        ]
        if sys.platform == "darwin":
            contents_dir = executable_dir.parent
            candidate_dirs.extend(
                [
                    contents_dir / "Resources" / "bin",
                    contents_dir / "Frameworks" / "bin",
                ]
            )

        for candidate_dir in candidate_dirs:
            candidate = candidate_dir / _binary_filename(binary_name)
            key = str(candidate)
            if key in seen:
                continue
            seen.add(key)
            yield candidate

    resolved_from_path = shutil.which(binary_name)
    if resolved_from_path:
        candidate = Path(resolved_from_path)
        key = str(candidate)
        if key not in seen:
            seen.add(key)
            yield candidate

    for candidate_dir in COMMON_BINARY_DIRS:
        candidate = candidate_dir / _binary_filename(binary_name)
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        yield candidate

    if binary_name == "ffmpeg":
        try:
            from spotdl.utils.config import get_spotdl_path

            candidate = Path(get_spotdl_path()) / _binary_filename(binary_name)
            key = str(candidate)
            if key not in seen:
                seen.add(key)
                yield candidate
        except Exception:
            LOGGER.debug("Could not resolve spotDL local ffmpeg path", exc_info=True)


def _resolve_binary_path(binary_name: str) -> Optional[Path]:
    """Resolve a bundled/system binary path without depending on shell PATH."""
    for candidate in _iter_binary_candidates(binary_name):
        if _is_executable_file(candidate):
            return candidate.resolve()

    return None


def _prepend_directories_to_path(*directories: Path) -> None:
    """Prepend executable directories to PATH without duplicating entries."""
    existing_entries = [
        entry for entry in os.environ.get("PATH", "").split(os.pathsep) if entry
    ]
    normalized_existing = {
        str(Path(entry).expanduser().resolve()): entry
        for entry in existing_entries
        if Path(entry).exists()
    }

    prepended_entries: list[str] = []
    seen_normalized: set[str] = set()
    for directory in directories:
        try:
            normalized = str(directory.expanduser().resolve())
        except OSError:
            normalized = str(directory)

        if (
            not directory.exists()
            or normalized in normalized_existing
            or normalized in seen_normalized
        ):
            continue

        prepended_entries.append(str(directory))
        seen_normalized.add(normalized)

    if not prepended_entries:
        return

    os.environ["PATH"] = os.pathsep.join([*prepended_entries, *existing_entries])


def _configure_bundled_spotdl_environment() -> None:
    """Make bundled `spotdl` runs find ffmpeg/ffprobe outside an interactive shell."""
    ffmpeg_path = _resolve_binary_path("ffmpeg")
    ffprobe_path = _resolve_binary_path("ffprobe")

    binary_dirs = []
    if ffmpeg_path is not None:
        binary_dirs.append(ffmpeg_path.parent)
    if ffprobe_path is not None:
        binary_dirs.append(ffprobe_path.parent)
    _prepend_directories_to_path(*binary_dirs)

    if ffmpeg_path is None:
        LOGGER.warning(
            "Could not resolve an ffmpeg executable for bundled spotDL runtime."
        )
        return

    if "--ffmpeg" not in sys.argv:
        sys.argv.extend(["--ffmpeg", str(ffmpeg_path)])

    LOGGER.info("Using ffmpeg executable: %s", ffmpeg_path)
