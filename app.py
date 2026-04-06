"""Main Flask application with modular structure."""

import os
from pathlib import Path
import subprocess
import sys
import threading
from typing import Optional

try:
    from flask import Flask, jsonify, render_template, request
except ImportError as exc:
    raise SystemExit(
        "Missing app dependencies. Run `uv sync` and then `uv run app.py`."
    ) from exc

from config import (
    APP_NAME,
    DEFAULT_DOWNLOAD_DIR,
    PORT,
    WINDOW_WIDTH,
    WINDOW_HEIGHT,
    get_download_dir,
    load_app_settings,
    set_download_dir,
)
from spotify_client import MetadataError, spotify_manager
from downloader import download_manager


def _resource_dir() -> Path:
    """Return the resource root for source and frozen builds."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)

    return Path(__file__).resolve().parent


def _best_initial_directory() -> Path:
    """Return the best existing directory to seed the folder picker."""
    configured_dir = get_download_dir()
    if configured_dir and configured_dir.exists():
        return configured_dir

    if DEFAULT_DOWNLOAD_DIR.exists():
        return DEFAULT_DOWNLOAD_DIR

    if DEFAULT_DOWNLOAD_DIR.parent.exists():
        return DEFAULT_DOWNLOAD_DIR.parent

    return Path.home()


def _choose_directory(initial_dir: Optional[Path] = None) -> Optional[Path]:
    """Open a native folder picker and return the chosen directory, if any."""
    initial_dir = initial_dir or _best_initial_directory()
    if not initial_dir.exists():
        initial_dir = initial_dir.parent if initial_dir.parent.exists() else Path.home()

    if sys.platform == "darwin":
        prompt = "Choose where spotDL Web Downloader should save downloads"
        escaped_dir = str(initial_dir).replace("\\", "\\\\").replace('"', '\\"')
        escaped_prompt = prompt.replace("\\", "\\\\").replace('"', '\\"')
        script = "\n".join(
            [
                f'set defaultLocation to POSIX file "{escaped_dir}"',
                f'set chosenFolder to choose folder with prompt "{escaped_prompt}" default location defaultLocation',
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


def create_app() -> Flask:
    """Create and configure Flask application."""
    resource_dir = _resource_dir()
    app = Flask(
        __name__,
        template_folder=str(resource_dir / "templates"),
        static_folder=str(resource_dir / "static"),
    )
    
    @app.route("/")
    def index():
        """Main page with download interface."""
        return render_template("index.html", app_name=APP_NAME)

    @app.route("/settings")
    def settings_endpoint():
        """Return persisted app settings."""
        return jsonify(load_app_settings())

    @app.route("/settings", methods=["POST"])
    def update_settings_endpoint():
        """Persist app settings updates."""
        data = request.get_json(force=True)
        download_directory = str(data.get("downloadDirectory") or "").strip()
        if not download_directory:
            return jsonify({"error": "Choose a download folder first."}), 400

        set_download_dir(download_directory)
        return jsonify(load_app_settings())

    @app.route("/settings/download-directory/pick", methods=["POST"])
    def pick_download_directory_endpoint():
        """Open a native folder picker and persist the selected directory."""
        chosen_dir = _choose_directory(_best_initial_directory())
        if chosen_dir is None:
            payload = load_app_settings()
            payload["cancelled"] = True
            return jsonify(payload)

        set_download_dir(chosen_dir)
        return jsonify(load_app_settings())
    
    @app.route("/meta", methods=["POST"])
    def meta_endpoint():
        """Get song metadata from Spotify/YouTube link."""
        data = request.get_json(force=True)
        link = data.get("link", "")
        
        if not link:
            return jsonify({"error": "Missing link"}), 400

        try:
            metadata = spotify_manager.get_metadata(link)
        except MetadataError as exc:
            payload = {"error": str(exc), "code": exc.code}
            if exc.retry_after is not None:
                payload["retry_after"] = exc.retry_after
            return jsonify(payload), 429 if exc.code == "rate_limited" else 502

        return jsonify(metadata)
    
    @app.route("/download", methods=["POST"])
    def download_endpoint():
        """Start download with user settings."""
        data = request.get_json(force=True)
        link = data.get("link", "")
        
        if not link:
            return "", 400

        download_dir = get_download_dir()
        if download_dir is None:
            return jsonify({"error": "Choose a download folder before starting downloads."}), 409

        # Extract settings from request (excluding the link)
        settings = {k: v for k, v in data.items() if k != "link"}
        download_input = spotify_manager.get_download_input(link)
        settings["_download_directory"] = str(download_dir)
        settings["_download_input"] = download_input["input"]
        settings["_temporary_input_file"] = download_input["temporary_input_file"]
        settings["_fallback_missing_artist"] = download_input["fallback_missing_artist"]

        # The download manager treats redundant starts and short-lived
        # pre-start cancellations as idempotent no-ops, so the API stays 204.
        download_manager.start_download(link, settings)
        return "", 204
    
    @app.route("/status")
    def status_endpoint():
        """Get download status for multiple links."""
        links_param = request.args.get("links", "")
        links = [link.strip() for link in links_param.split(",") if link.strip()]
        
        status_data = download_manager.get_status(links)
        return jsonify(status_data)
    
    @app.route("/cancel", methods=["POST"])
    def cancel_endpoint():
        """Cancel an active download."""
        print("CANCEL REQUEST RECEIVED")  # Add this for debugging
        data = request.get_json(force=True)
        link = data.get("link", "")
        
        if not link:
            return "", 400
        
        success = download_manager.cancel_download(link)
        return "", 204 if success else 409
    
    return app


def run_server(app: Flask) -> None:
    """Run Flask server in a separate thread for the desktop window."""
    # The Werkzeug reloader installs signal handlers and must stay on the main
    # thread, so keep the embedded server path non-debug.
    app.run(host="127.0.0.1", port=PORT, threaded=True, debug=False, use_reloader=False)


def main():
    """Main entry point for the application."""
    if "--run-spotdl" in sys.argv:
        helper_args = [arg for arg in sys.argv[1:] if arg != "--run-spotdl"]
        from spotdl.console import console_entry_point

        sys.argv = [sys.argv[0], *helper_args]
        console_entry_point()
        return

    try:
        import webview
    except ImportError as exc:
        raise SystemExit(
            "Missing desktop app dependencies. Run `uv sync` and then `uv run app.py`."
        ) from exc
    
    app = create_app()
    
    # Check if we're in development mode
    if os.getenv('FLASK_ENV') == 'development' or '--dev' in sys.argv:
        # Run Flask directly for development with hot reloading
        # Use threaded=True to handle multiple concurrent requests (e.g., SSE and cancel)
        app.run(host='127.0.0.1', port=PORT, debug=True, threaded=True)
    else:
        # Run in webview for production
        # Start Flask server in background
        server_thread = threading.Thread(target=run_server, args=(app,), daemon=True)
        server_thread.start()
        
        # Create and start webview window
        webview.create_window(
            APP_NAME,
            f"http://127.0.0.1:{PORT}",
            width=WINDOW_WIDTH,
            height=WINDOW_HEIGHT,
            resizable=True
        )
        webview.start()


if __name__ == "__main__":
    main()
