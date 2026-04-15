"""Flask application factory."""

from __future__ import annotations

import logging
from pathlib import Path

try:
    from flask import Flask, got_request_exception, request
except ImportError as exc:
    raise SystemExit(
        "Missing app dependencies. Run `./setup`, then `./dev` or `./run`."
    ) from exc

from app.routes import register_routes
from config import settings_store
from downloader import download_manager
from spotify_client import MetadataError, spotify_manager

LOGGER = logging.getLogger(__name__)


def _resource_dir() -> Path:
    """Return the resource root for source and frozen builds."""
    import sys

    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)

    return Path(__file__).resolve().parent.parent


def create_app(
    *,
    metadata_manager=spotify_manager,
    download_service=download_manager,
    active_settings_store=settings_store,
) -> Flask:
    """Create and configure Flask application."""
    resource_dir = _resource_dir()
    app = Flask(
        __name__,
        template_folder=str(resource_dir / "templates"),
        static_folder=str(resource_dir / "static"),
    )

    metadata_manager.metadata_error_class = MetadataError

    def _log_request_exception(sender, exception, **extra) -> None:
        LOGGER.exception(
            "Unhandled exception during %s %s",
            request.method,
            request.path,
            exc_info=(type(exception), exception, exception.__traceback__),
        )

    got_request_exception.connect(_log_request_exception, app, weak=False)

    @app.after_request
    def log_error_responses(response):
        """Mirror failing HTTP responses into the terminal."""
        if response.status_code >= 400:
            LOGGER.warning(
                "HTTP %s for %s %s",
                response.status_code,
                request.method,
                request.full_path.rstrip("?"),
            )
        return response

    register_routes(
        app,
        metadata_manager=metadata_manager,
        download_service=download_service,
        settings_store=active_settings_store,
    )
    return app
