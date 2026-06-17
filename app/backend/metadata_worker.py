"""One-shot subprocess for best-effort metadata lookup."""

from __future__ import annotations

import json
import logging
import sys

from spotdl.types.song import Song

from app.backend.inputs import UnsupportedInputError, ensure_supported_single_track
from app.backend.media import (
    build_song_payload_from_external_info,
    extract_external_info,
    metadata_from_song_payload,
)
from app.backend.spotify import SpotifyConfigurationError, configure_spotify_client

LOGGER = logging.getLogger(__name__)


def _emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=True), flush=True)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    try:
        request = json.load(sys.stdin)
        link = str(request.get("link") or "").strip()
        info = ensure_supported_single_track(link)

        if info.kind == "spotify_track":
            configure_spotify_client()
            song = Song.from_url(info.normalized)
            payload = song.json
        else:
            external_info = extract_external_info(info.normalized)
            payload = build_song_payload_from_external_info(info.normalized, external_info)

        _emit(
            {
                "ok": True,
                "metadata": metadata_from_song_payload(payload),
                "song_payload": payload,
            }
        )
    except UnsupportedInputError as exc:
        _emit({"ok": False, "error": str(exc), "code": "unsupported_input"})
    except SpotifyConfigurationError as exc:
        _emit({"ok": False, "error": str(exc), "code": "missing_spotify_credentials"})
    except Exception as exc:
        LOGGER.exception("Metadata lookup failed")
        _emit({"ok": False, "error": str(exc) or "Metadata lookup failed.", "code": "metadata_error"})


if __name__ == "__main__":
    main()

