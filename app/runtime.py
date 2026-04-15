"""Runtime entrypoints for development and desktop app modes."""

from __future__ import annotations

import logging
import os
import socket
import sys
import threading

from app.binaries import _configure_bundled_spotdl_environment
from app.diagnostics import _enable_terminal_diagnostics
from app.web import create_app
from config import APP_NAME, PORT, WINDOW_HEIGHT, WINDOW_WIDTH

LOGGER = logging.getLogger(__name__)
SERVER_HOST = "127.0.0.1"


def _ensure_server_can_bind(host: str, port: int) -> None:
    """Fail early with the real socket error instead of Werkzeug's short message."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((host, port))
        except OSError as exc:
            raise RuntimeError(
                f"Cannot start local server at http://{host}:{port}: "
                f"{exc.__class__.__name__}: {exc}"
            ) from exc


def _should_probe_server_socket(*, use_reloader: bool) -> bool:
    """Skip the manual bind probe inside Werkzeug's reloader child process."""
    if not use_reloader:
        return True

    if os.getenv("WERKZEUG_RUN_MAIN") == "true":
        return False

    if os.getenv("WERKZEUG_SERVER_FD"):
        return False

    return True


def run_server(app) -> None:
    """Run Flask server in a separate thread for the desktop window."""
    LOGGER.info("Starting embedded server at http://%s:%s", SERVER_HOST, PORT)
    _ensure_server_can_bind(SERVER_HOST, PORT)
    app.run(
        host=SERVER_HOST,
        port=PORT,
        threaded=True,
        debug=False,
        use_reloader=False,
        load_dotenv=False,
    )


def main() -> None:
    """Main entry point for the application."""
    _enable_terminal_diagnostics()

    if "--run-spotdl" in sys.argv:
        _configure_bundled_spotdl_environment()
        helper_args = [arg for arg in sys.argv[1:] if arg != "--run-spotdl"]
        from spotdl.console import console_entry_point

        sys.argv = [sys.argv[0], *helper_args]
        console_entry_point()
        return

    try:
        import webview
    except ImportError as exc:
        raise SystemExit(
            "Missing desktop app dependencies. Run `./setup`, then `./dev` or `./run`."
        ) from exc

    app = create_app()

    if os.getenv("FLASK_ENV") == "development" or "--dev" in sys.argv:
        use_reloader = True
        LOGGER.info("Starting development server at http://%s:%s", SERVER_HOST, PORT)
        if _should_probe_server_socket(use_reloader=use_reloader):
            _ensure_server_can_bind(SERVER_HOST, PORT)
        app.run(
            host=SERVER_HOST,
            port=PORT,
            debug=True,
            threaded=True,
            use_reloader=use_reloader,
            load_dotenv=False,
        )
        return

    server_thread = threading.Thread(
        target=run_server,
        args=(app,),
        daemon=True,
        name="embedded-flask-server",
    )
    server_thread.start()

    webview.create_window(
        APP_NAME,
        f"http://{SERVER_HOST}:{PORT}",
        width=WINDOW_WIDTH,
        height=WINDOW_HEIGHT,
        resizable=True,
    )
    webview.start()
