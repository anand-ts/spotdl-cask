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

from app.backend.jobs import DownloadSupervisor
from app.backend.metadata import MetadataService
from app.backend.settings import default_settings_store
from app.routes import register_routes

LOGGER = logging.getLogger(__name__)


def _project_root() -> Path:
    """Return the source checkout root."""
    return Path(__file__).resolve().parent.parent


def create_app(
    *,
    metadata_service: MetadataService | None = None,
    download_service: DownloadSupervisor | None = None,
    active_settings_store=None,
) -> Flask:
    """Create and configure Flask application."""
    resource_dir = _project_root()
    app = Flask(
        __name__,
        template_folder=str(resource_dir / "templates"),
        static_folder=str(resource_dir / "static"),
    )
    metadata_service = metadata_service or MetadataService()
    download_service = download_service or DownloadSupervisor(metadata_service)
    active_settings_store = active_settings_store or default_settings_store

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
        metadata_service=metadata_service,
        download_service=download_service,
        settings_store=active_settings_store,
    )
    return app
