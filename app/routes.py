"""Flask route registration for the desktop/web app."""

from __future__ import annotations

from pathlib import Path

from flask import Flask, jsonify, render_template, request

from app.pickers import best_initial_directory, choose_directory
from app.services.spotify import MetadataError
from config import APP_NAME


def register_routes(
    app: Flask,
    *,
    metadata_service,
    download_service,
    settings_store,
) -> None:
    """Attach all HTTP routes to the Flask application."""

    @app.route("/favicon.ico")
    def favicon():
        """Serve the bundled favicon without emitting a noisy 404."""
        favicon_path = Path(app.static_folder or "") / "favicon.svg"
        return app.response_class(
            favicon_path.read_text(encoding="utf-8"),
            mimetype="image/svg+xml",
        )

    @app.route("/")
    def index():
        """Main page with download interface."""
        return render_template("index.html", app_name=APP_NAME)

    @app.route("/settings")
    def settings_endpoint():
        """Return persisted app settings."""
        return jsonify(settings_store.load())

    @app.route("/settings", methods=["POST"])
    def update_settings_endpoint():
        """Persist app settings updates."""
        data = request.get_json(force=True)
        download_directory = str(data.get("downloadDirectory") or "").strip()
        if not download_directory:
            return jsonify({"error": "Choose a download folder first."}), 400

        settings_store.set_download_dir(download_directory)
        return jsonify(settings_store.load())

    @app.route("/settings/download-directory/pick", methods=["POST"])
    def pick_download_directory_endpoint():
        """Open a native folder picker and persist the selected directory."""
        chosen_dir = choose_directory(
            best_initial_directory(settings_store.get_download_dir())
        )
        if chosen_dir is None:
            payload = settings_store.load()
            payload["cancelled"] = True
            return jsonify(payload)

        settings_store.set_download_dir(chosen_dir)
        return jsonify(settings_store.load())

    @app.route("/meta", methods=["POST"])
    def meta_endpoint():
        """Get song metadata from Spotify/YouTube link."""
        data = request.get_json(force=True)
        link = data.get("link", "")

        if not link:
            return jsonify({"error": "Missing link"}), 400

        try:
            metadata = metadata_service.get_metadata(link)
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

        download_dir = settings_store.get_download_dir()
        if download_dir is None:
            return jsonify(
                {"error": "Choose a download folder before starting downloads."}
            ), 409

        settings = {
            key: value
            for key, value in data.items()
            if key != "link"
        }
        settings["_download_directory"] = str(download_dir)

        download_service.start_download(link, settings)
        return "", 204

    @app.route("/status")
    def status_endpoint():
        """Get download status for multiple links."""
        links_param = request.args.get("links", "")
        links = [link.strip() for link in links_param.split(",") if link.strip()]
        return jsonify(download_service.get_status(links))

    @app.route("/cancel", methods=["POST"])
    def cancel_endpoint():
        """Cancel an active download."""
        data = request.get_json(force=True)
        link = data.get("link", "")

        if not link:
            return "", 400

        success = download_service.cancel_download(link)
        return "", 204 if success else 409

    @app.route("/reveal", methods=["POST"])
    def reveal_endpoint():
        """Reveal a downloaded file in Finder/File Explorer."""
        data = request.get_json(force=True)
        link = data.get("link", "")

        if not link:
            return jsonify({"error": "Missing link"}), 400

        try:
            file_path = download_service.reveal_downloaded_file(link)
        except FileNotFoundError as exc:
            return jsonify({"error": str(exc)}), 404
        except RuntimeError as exc:
            return jsonify({"error": str(exc)}), 500

        return jsonify({"path": str(file_path)})
