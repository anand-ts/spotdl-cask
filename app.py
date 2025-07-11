"""Main Flask application with modular structure."""

import threading
import time
import json
from flask import Flask, request, jsonify, render_template, Response
import webview

from config import APP_NAME, PORT, WINDOW_WIDTH, WINDOW_HEIGHT
from spotify_client import spotify_manager
from downloader import download_manager


def create_app() -> Flask:
    """Create and configure Flask application."""
    app = Flask(__name__)
    
    @app.route("/")
    def index():
        """Main page with download interface."""
        return render_template("index.html", app_name=APP_NAME)
    
    @app.route("/meta", methods=["POST"])
    def meta_endpoint():
        """Get song metadata from Spotify/YouTube link."""
        data = request.get_json(force=True)
        link = data.get("link", "")
        
        if not link:
            return jsonify({"error": "Missing link"}), 400
        
        metadata = spotify_manager.get_metadata(link)
        return jsonify(metadata)
    
    @app.route("/download", methods=["POST"])
    def download_endpoint():
        """Start download with user settings."""
        data = request.get_json(force=True)
        link = data.get("link", "")
        
        if not link:
            return "", 400
        
        if download_manager.is_busy(link):
            return "", 204  # Already downloading or done
        
        # Extract settings from request (excluding the link)
        settings = {k: v for k, v in data.items() if k != "link"}
        
        success = download_manager.start_download(link, settings)
        return "", 204 if success else 409
    
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
        data = request.get_json(force=True)
        link = data.get("link", "")
        
        if not link:
            return "", 400
        
        success = download_manager.cancel_download(link)
        return "", 204 if success else 409
    
    @app.route("/progress/<path:link>")
    def progress_stream(link: str):
        """Server-Sent Events stream for real-time download progress."""
        def generate_progress_events():
            """Generate SSE events for progress updates."""
            # Set up progress callback
            progress_updates = []
            
            def progress_callback(cb_link: str, progress: float):
                if cb_link == link:
                    progress_updates.append(progress)
            
            download_manager.add_progress_callback(link, progress_callback)
            
            try:
                # Send initial progress
                initial_progress = download_manager.get_progress(link)
                yield f"data: {json.dumps({'progress': initial_progress, 'link': link})}\n\n"
                
                # Keep connection alive and send updates
                last_progress = initial_progress
                while True:
                    # Check for new progress updates
                    if progress_updates:
                        current_progress = progress_updates[-1]
                        progress_updates.clear()  # Clear processed updates
                        
                        if current_progress != last_progress:
                            yield f"data: {json.dumps({'progress': current_progress, 'link': link})}\n\n"
                            last_progress = current_progress
                        
                        # If download is complete, send final update and close
                        if current_progress >= 100:
                            yield f"data: {json.dumps({'progress': 100, 'link': link, 'complete': True})}\n\n"
                            break
                    
                    # Check if download is no longer active
                    status = download_manager.status.get(link, "idle")
                    if status in ["done", "error"]:
                        final_progress = 100 if status == "done" else last_progress
                        yield f"data: {json.dumps({'progress': final_progress, 'link': link, 'complete': True, 'status': status})}\n\n"
                        break
                    
                    time.sleep(0.1)  # Small delay to prevent excessive CPU usage
                    
            except GeneratorExit:
                # Client disconnected
                pass
            finally:
                # Clean up callback
                download_manager.remove_progress_callbacks(link)
        
        return Response(
            generate_progress_events(),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'Connection': 'keep-alive',
                'Access-Control-Allow-Origin': '*',
            }
        )
    
    return app


def run_server(app: Flask) -> None:
    """Run Flask server in a separate thread."""
    app.run(port=PORT, threaded=True, debug=True)


def main():
    """Main entry point for the application."""
    import os
    import sys
    
    app = create_app()
    
    # Check if we're in development mode
    if os.getenv('FLASK_ENV') == 'development' or '--dev' in sys.argv:
        # Run Flask directly for development with hot reloading
        app.run(host='127.0.0.1', port=PORT, debug=True)
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
