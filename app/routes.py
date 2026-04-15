"""Flask route registration for the desktop/web app."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template, request

from app.pickers import _best_initial_directory, _choose_directory
from config import APP_NAME


def _clean_metadata_text(value: Any) -> str:
    """Normalize any metadata value into a clean string."""
    if value is None:
        return ""

    return str(value).strip()


def _coalesce_metadata_text(*values: Any) -> str:
    """Return the first non-empty metadata string."""
    for value in values:
        cleaned = _clean_metadata_text(value)
        if cleaned:
            return cleaned

    return ""


def _stringify_artists(value: Any) -> str:
    """Collapse artist list-style payloads into the UI's string shape."""
    if isinstance(value, (list, tuple, set)):
        artists = [
            _clean_metadata_text(artist)
            for artist in value
            if _clean_metadata_text(artist)
        ]
        return ", ".join(artists)

    return _clean_metadata_text(value)


def _normalize_metadata_payload(payload: Any) -> dict[str, str]:
    """Coerce legacy/raw metadata shapes into the route's public contract."""
    if not isinstance(payload, dict):
        return {
            "title": "(unknown)",
            "artist": "",
            "album": "",
            "cover": "",
        }

    title = _coalesce_metadata_text(
        payload.get("title"),
        payload.get("name"),
        payload.get("track"),
        payload.get("fulltitle"),
    )
    artist = _coalesce_metadata_text(
        payload.get("artist"),
        _stringify_artists(payload.get("artists")),
        payload.get("artist_name"),
        payload.get("author_name"),
        payload.get("album_artist"),
        payload.get("creator"),
        payload.get("uploader"),
        payload.get("channel"),
    )
    album = _coalesce_metadata_text(
        payload.get("album"),
        payload.get("album_name"),
        payload.get("album_title"),
        payload.get("playlist_title"),
        payload.get("playlist"),
        payload.get("collection"),
    )
    cover = _coalesce_metadata_text(
        payload.get("cover"),
        payload.get("cover_url"),
        payload.get("thumbnail"),
        payload.get("image"),
    )

    return {
        "title": title or "(unknown)",
        "artist": artist,
        "album": album,
        "cover": cover,
    }


def register_routes(
    app: Flask,
    *,
    metadata_manager,
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
        chosen_dir = _choose_directory(_best_initial_directory())
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
            metadata = metadata_manager.get_metadata(link)
        except metadata_manager.metadata_error_class as exc:
            payload = {"error": str(exc), "code": exc.code}
            if exc.retry_after is not None:
                payload["retry_after"] = exc.retry_after
            return jsonify(payload), 429 if exc.code == "rate_limited" else 502

        return jsonify(_normalize_metadata_payload(metadata))

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

        settings = {key: value for key, value in data.items() if key != "link"}
        download_input = metadata_manager.get_download_input(link)
        settings["_download_directory"] = str(download_dir)
        settings["_download_input"] = download_input["input"]
        settings["_temporary_input_file"] = download_input["temporary_input_file"]
        settings["_fallback_missing_artist"] = download_input["fallback_missing_artist"]

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
