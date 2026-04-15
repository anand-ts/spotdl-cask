"""Application package for runtime, routes, and shared infrastructure."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Any, cast

from . import binaries as binaries_module
from .diagnostics import (
    _configure_logging,
    _enable_terminal_diagnostics,
    _install_exception_logging,
    _SpotipyRateLimitFilter,
)
from .runtime import (
    SERVER_HOST,
    _ensure_server_can_bind,
    _should_probe_server_socket,
    main,
    run_server,
)
from .web import create_app


def _resolve_binary_path(binary_name: str) -> Path | None:
    """Compatibility wrapper for tests and legacy imports."""
    mutable_binaries_module = cast(Any, binaries_module)
    original_sys = mutable_binaries_module.sys
    original_shutil = mutable_binaries_module.shutil
    try:
        mutable_binaries_module.sys = sys
        mutable_binaries_module.shutil = shutil
        return binaries_module._resolve_binary_path(binary_name)
    finally:
        mutable_binaries_module.sys = original_sys
        mutable_binaries_module.shutil = original_shutil


def _configure_bundled_spotdl_environment() -> None:
    """Compatibility wrapper that keeps package-level test patching working."""
    mutable_binaries_module = cast(Any, binaries_module)
    original_sys = mutable_binaries_module.sys
    original_shutil = mutable_binaries_module.shutil
    original_resolver = mutable_binaries_module._resolve_binary_path
    try:
        mutable_binaries_module.sys = sys
        mutable_binaries_module.shutil = shutil
        mutable_binaries_module._resolve_binary_path = _resolve_binary_path
        binaries_module._configure_bundled_spotdl_environment()
    finally:
        mutable_binaries_module.sys = original_sys
        mutable_binaries_module.shutil = original_shutil
        mutable_binaries_module._resolve_binary_path = original_resolver


__all__ = [
    "SERVER_HOST",
    "_SpotipyRateLimitFilter",
    "_configure_bundled_spotdl_environment",
    "_configure_logging",
    "_enable_terminal_diagnostics",
    "_ensure_server_can_bind",
    "_install_exception_logging",
    "_resolve_binary_path",
    "_should_probe_server_socket",
    "binaries_module",
    "create_app",
    "main",
    "run_server",
    "shutil",
    "sys",
]
